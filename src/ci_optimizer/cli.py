"""CLI entry point for ci-agent."""
# 架构角色：用户交互的最外层入口，所有子命令（analyze/serve/config/skills/chat）
#           均在此文件中注册和分发，是系统各功能模块的"粘合层"。
# 核心职责：解析命令行参数、合并配置、将执行流路由到对应的运行函数
#           （run_analyze / run_serve / run_config / run_skills / run_chat）。
# 关联模块：依赖 config.py 构建 AgentConfig，依赖 resolver/prefetch/filters
#           完成数据准备，最终将 ctx 交给 agents/orchestrator 执行分析。

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


def parse_args():
    parser = argparse.ArgumentParser(
        prog="ci-agent",
        description="AI-powered GitHub CI pipeline analyzer and optimizer",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # chat command (TUI mode)
    chat = subparsers.add_parser("chat", help="Interactive TUI mode (default when no command given)")
    chat.add_argument("--repo", help="Repository path (default: current directory)")
    chat.add_argument("--model", "-m", help="Model to use")

    # analyze command
    analyze = subparsers.add_parser("analyze", help="Analyze a repository's CI pipelines")
    analyze.add_argument("repo", help="Local path or GitHub URL of the repository")
    analyze.add_argument("--since", help="Start date for run history (YYYY-MM-DD)")
    analyze.add_argument("--until", help="End date for run history (YYYY-MM-DD)")
    analyze.add_argument("--workflow", action="append", dest="workflows", help="Filter by workflow filename (can repeat)")
    analyze.add_argument("--status", action="append", help="Filter by run status: success/failure/cancelled (can repeat)")
    analyze.add_argument("--branch", action="append", dest="branches", help="Filter by branch name (can repeat)")
    analyze.add_argument("--output", "-o", help="Output file path (default: stdout)")
    analyze.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown", help="Output format")
    analyze.add_argument("--model", "-m", help="Model to use (e.g. claude-sonnet-4-20250514, claude-opus-4-20250514)")
    analyze.add_argument("--api-key", help="Anthropic API key (overrides config and env)")
    analyze.add_argument("--lang", choices=["en", "zh"], help="Report language: en (English) or zh (Chinese)")
    analyze.add_argument("--provider", choices=["anthropic", "openai"], help="AI provider: anthropic or openai")
    analyze.add_argument("--base-url", help="Custom API base URL (for OpenAI-compatible endpoints)")
    analyze.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    analyze.add_argument("--skills", help="Comma-separated list of dimensions to run (e.g. security,cost). Default: all")

    # serve command
    serve = subparsers.add_parser("serve", help="Start the API server")
    serve.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    serve.add_argument("--port", "-p", type=int, default=8000, help="Port to bind (default: 8000)")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    # config command
    config_cmd = subparsers.add_parser("config", help="View or update configuration")
    config_sub = config_cmd.add_subparsers(dest="config_action")

    config_sub.add_parser("show", help="Show current configuration")

    config_set = config_sub.add_parser("set", help="Set a configuration value")
    config_set.add_argument("key", help="Config key (model, fallback_model, anthropic_api_key, github_token, max_turns)")
    config_set.add_argument("value", help="Config value")

    config_sub.add_parser("path", help="Show config file path")

    # skills command
    skills_cmd = subparsers.add_parser("skills", help="List and inspect available analysis skills")
    skills_sub = skills_cmd.add_subparsers(dest="skills_action")

    skills_sub.add_parser("list", help="List all discovered skills")

    skills_show = skills_sub.add_parser("show", help="Show details of a specific skill")
    skills_show.add_argument("name", help="Skill name (e.g. security-analyst)")

    skills_validate = skills_sub.add_parser(
        "validate",
        help="Validate a SKILL.md file or a directory containing SKILL.md files",
    )
    skills_validate.add_argument(
        "path",
        help="Path to a SKILL.md file or a directory containing one or more skill subdirs",
    )

    skills_sub.add_parser(
        "reload",
        help="Tell the running API server to reload skills (POST /api/skills/reload)",
    )

    # skills import — from Claude Code / OpenCode / local path
    skills_import = skills_sub.add_parser(
        "import",
        help="Import a skill from Claude Code, OpenCode, or a local directory",
    )
    skills_import.add_argument(
        "--from",
        dest="source",
        required=True,
        choices=["claude-code", "opencode", "path"],
        help="Source type",
    )
    skills_import.add_argument(
        "target",
        help="Skill name (for claude-code/opencode) or directory path (for path)",
    )
    skills_import.add_argument(
        "--dimension",
        required=True,
        help="Dimension to assign (e.g. efficiency, security, cost, errors, or custom)",
    )
    skills_import.add_argument(
        "--requires-data",
        help="Comma-separated data deps (default: workflows). Valid: workflows,runs,jobs,logs,usage_stats,action_shas",
    )
    skills_import.add_argument(
        "--name",
        help="Override the skill name (default: taken from source SKILL.md)",
    )

    # skills install — from git URL
    skills_install = skills_sub.add_parser(
        "install",
        help="Install a skill from a GitHub repository",
    )
    skills_install.add_argument(
        "url",
        help="Repository URL (https://github.com/owner/repo or gh:owner/repo)",
    )
    skills_install.add_argument("--dimension", required=True, help="Dimension to assign")
    skills_install.add_argument("--requires-data", help="Comma-separated data deps")

    # skills uninstall
    skills_uninstall = skills_sub.add_parser(
        "uninstall",
        help="Remove an installed user skill",
    )
    skills_uninstall.add_argument("name", help="Skill directory name")

    return parser.parse_args()


def _build_config(args) -> "AgentConfig":
    """Build AgentConfig from saved config + CLI overrides.

    先从文件/环境变量加载基础配置，再用 CLI 标志做最终覆盖，
    确保命令行参数拥有最高优先级（高于环境变量）。
    """
    from ci_optimizer.config import AgentConfig

    config = AgentConfig.load()

    # CLI flags override config
    if hasattr(args, "model") and args.model:
        config.model = args.model
    if hasattr(args, "api_key") and args.api_key:
        config.anthropic_api_key = args.api_key
    if hasattr(args, "lang") and args.lang:
        config.language = args.lang
    if hasattr(args, "provider") and args.provider:
        config.provider = args.provider
    if hasattr(args, "base_url") and args.base_url:
        config.base_url = args.base_url

    return config


async def run_analyze(args):
    """执行单次 CI 分析的完整流程：配置构建 → 仓库解析 → 数据预取 → Agent 分析 → 报告输出。"""
    from ci_optimizer.agents.orchestrator import run_analysis
    from ci_optimizer.filters import AnalysisFilters
    from ci_optimizer.prefetch import prepare_context
    from ci_optimizer.report.formatter import format_json, format_markdown
    from ci_optimizer.resolver import resolve_input

    config = _build_config(args)

    # Validate API key
    if not config.get_api_key():
        if config.provider == "openai":
            print(
                "Error: No OpenAI API key configured.\n"
                "Set it via one of:\n"
                "  ci-agent config set openai_api_key sk-...\n"
                "  export OPENAI_API_KEY=sk-...\n"
                "  ci-agent config set provider openai",
                file=sys.stderr,
            )
        else:
            print(
                "Error: No Anthropic API key configured.\n"
                "Set it via one of:\n"
                "  ci-agent config set anthropic_api_key sk-ant-...\n"
                "  export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  ci-agent analyze --api-key sk-ant-... <repo>",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"Using provider: {config.provider}, model: {config.model}", file=sys.stderr)

    # Build filters
    time_range = None
    if args.since and args.until:
        time_range = (
            datetime.fromisoformat(args.since),
            datetime.fromisoformat(args.until),
        )
    elif args.since:
        time_range = (datetime.fromisoformat(args.since), datetime.now(timezone.utc))

    filters = AnalysisFilters(
        time_range=time_range,
        workflows=args.workflows,
        status=args.status,
        branches=args.branches,
    )

    # Resolve input
    print(f"Resolving repository: {args.repo}", file=sys.stderr)
    try:
        resolved = resolve_input(args.repo)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if resolved.owner and resolved.repo:
        print(f"Repository: {resolved.owner}/{resolved.repo}", file=sys.stderr)
    print(f"Local path: {resolved.local_path}", file=sys.stderr)

    # Prefetch data
    print("Fetching CI data...", file=sys.stderr)
    try:
        ctx = await prepare_context(resolved, filters)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(ctx.workflow_files)} workflow files", file=sys.stderr)

    # Run analysis
    print("Running analysis (this may take a few minutes)...", file=sys.stderr)
    selected = args.skills.split(",") if args.skills else None
    result = await run_analysis(ctx, config=config, selected_skills=selected)

    # Format output
    if args.format == "json":
        output = format_json(result, ctx, language=config.language)
    else:
        output = format_markdown(result, ctx, language=config.language)

    # Write output
    if args.output:
        Path(args.output).write_text(output)
        print(f"Report saved to: {args.output}", file=sys.stderr)
    else:
        print(output)

    print(
        f"\nAnalysis complete: {result.stats.get('total_findings', 0)} findings in {result.duration_ms / 1000:.1f}s",
        file=sys.stderr,
    )


def run_serve(args):
    import uvicorn

    uvicorn.run(
        "ci_optimizer.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def run_config(args):
    from ci_optimizer.config import CONFIG_FILE, AgentConfig

    if args.config_action == "show":
        config = AgentConfig.load()
        print(json.dumps(config.to_display_dict(), indent=2))

    elif args.config_action == "set":
        config = AgentConfig.load()
        key = args.key
        value = args.value

        if not hasattr(config, key):
            print(f"Error: Unknown config key '{key}'", file=sys.stderr)
            print("Available keys: model, fallback_model, anthropic_api_key, github_token, max_turns", file=sys.stderr)
            sys.exit(1)

        # Type conversion
        if key == "max_turns":
            value = int(value)

        setattr(config, key, value)
        config.save()
        print(f"Set {key} = {value if key not in ('anthropic_api_key', 'github_token') else '***'}")
        print(f"Config saved to {CONFIG_FILE}")

    elif args.config_action == "path":
        print(CONFIG_FILE)

    else:
        print("Usage: ci-agent config {show|set|path}")
        sys.exit(1)


def _validate_skill_path(path: Path) -> int:
    """Validate one or more SKILL.md files. Returns 0 on success, 1 on failure.

    支持三种输入形式：单个 SKILL.md 文件、包含 SKILL.md 的技能目录、
    或内含多个子技能目录的父目录。对 requires_data 字段错误还会给出"你是否想写 X？"的提示。
    """
    from ci_optimizer.agents.skill_registry import (
        VALID_REQUIRES_DATA,
        SkillRegistry,
    )

    # Collect candidate SKILL.md files
    candidates: list[Path] = []
    if path.is_file() and path.name == "SKILL.md":
        candidates.append(path)
    elif path.is_dir():
        # Could be a skill dir itself, or a parent of skill dirs
        direct = path / "SKILL.md"
        if direct.is_file():
            candidates.append(direct)
        else:
            for sub in sorted(path.iterdir()):
                if sub.is_dir():
                    s = sub / "SKILL.md"
                    if s.is_file():
                        candidates.append(s)
    else:
        print(f"✗ Path not found or not a valid skill target: {path}", file=sys.stderr)
        return 1

    if not candidates:
        print(f"✗ No SKILL.md files found under: {path}", file=sys.stderr)
        return 1

    # "did you mean" for unknown requires_data values
    # 用字符共现度做轻量相似度匹配，不引入 difflib 依赖
    def _suggest(bad: str) -> str | None:
        best: tuple[int, str] | None = None
        for candidate in VALID_REQUIRES_DATA:
            # simple character-level distance (Levenshtein-lite)
            a, b = bad.lower(), candidate.lower()
            if a == b:
                return candidate
            # common substring / prefix heuristic
            score = sum(1 for c in a if c in b)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best and best[0] >= max(1, len(bad) // 2):
            return best[1]
        return None

    total_errors = 0
    for skill_file in candidates:
        rel = skill_file.parent.name
        try:
            skill = SkillRegistry._parse_skill_md(skill_file, source="validate")
        except Exception as e:
            print(f"✗ {rel}/SKILL.md")
            print(f"    parse error: {e}")
            total_errors += 1
            continue

        errors = SkillRegistry._validate_skill(skill)
        if errors:
            print(f"✗ {rel}/SKILL.md")
            for err in errors:
                # Enhance requires_data errors with "did you mean"
                if "unknown requires_data" in err:
                    bad_set = err.split(": ", 1)[1].strip("{} ")
                    enhanced_parts = []
                    for bad in bad_set.replace("'", "").split(","):
                        bad = bad.strip()
                        if not bad:
                            continue
                        suggestion = _suggest(bad)
                        if suggestion:
                            enhanced_parts.append(f"'{bad}' (did you mean '{suggestion}'?)")
                        else:
                            enhanced_parts.append(f"'{bad}'")
                    print(f"    ✗ unknown requires_data: {', '.join(enhanced_parts)}")
                else:
                    print(f"    ✗ {err}")
            total_errors += len(errors)
        else:
            print(f"✓ {rel}/SKILL.md")
            print(f"    name:          {skill.name}")
            print(f"    dimension:     {skill.dimension}")
            print(f"    requires_data: {', '.join(skill.requires_data)}")
            print(f"    prompt body:   {len(skill.prompt)} chars")
            print(f"    tools:         {', '.join(skill.tools)}")

    print()
    if total_errors == 0:
        print(f"Validated {len(candidates)} skill{'s' if len(candidates) != 1 else ''} — all OK")
        return 0
    else:
        print(
            f"Validated {len(candidates)} skill{'s' if len(candidates) != 1 else ''}, {total_errors} error{'s' if total_errors != 1 else ''}"
        )
        return 1


def _run_skills_import(args):
    from ci_optimizer.agents.skill_importer import (
        SkillImportError,
        import_from_claude_code,
        import_from_opencode,
        import_from_path,
    )

    rd = None
    if args.requires_data:
        rd = [x.strip() for x in args.requires_data.split(",") if x.strip()]

    try:
        if args.source == "claude-code":
            result = import_from_claude_code(args.target, dimension=args.dimension, requires_data=rd)
        elif args.source == "opencode":
            result = import_from_opencode(args.target, dimension=args.dimension, requires_data=rd)
        else:  # path
            result = import_from_path(
                Path(args.target),
                dimension=args.dimension,
                requires_data=rd,
                name_override=args.name,
                source_kind="path",
            )
    except SkillImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Imported skill '{result.name}' from {result.source_kind}")
    print(f"  Dimension: {result.dimension}")
    print(f"  Target:    {result.target_path}")
    for w in result.warnings:
        print(f"  ⚠ {w}")
    print()
    print("⚠  Imported skill prompts are sent to the LLM. Only import skills")
    print("   from sources you trust. Run 'ci-agent skills show {name}' to review.")
    print("\nTip: Restart the API server or run 'ci-agent skills reload' to activate.")


def _run_skills_install(args):
    from ci_optimizer.agents.skill_importer import SkillImportError, install_from_github

    rd = None
    if args.requires_data:
        rd = [x.strip() for x in args.requires_data.split(",") if x.strip()]

    try:
        result = install_from_github(args.url, dimension=args.dimension, requires_data=rd)
    except SkillImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Installed skill '{result.name}' from {result.source_ref}")
    print(f"  Dimension: {result.dimension}")
    print(f"  Target:    {result.target_path}")
    for w in result.warnings:
        print(f"  ⚠ {w}")
    print()
    print("⚠  Installed skill prompts are sent to the LLM. Only install from")
    print("   sources you trust.")


def _run_skills_uninstall(args):
    from ci_optimizer.agents.skill_importer import SkillImportError, uninstall_skill

    try:
        path = uninstall_skill(args.name)
    except SkillImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ Removed {path}")


def run_skills(args):
    from ci_optimizer.agents.skill_registry import SkillRegistry

    if args.skills_action == "validate":
        exit_code = _validate_skill_path(Path(args.path))
        sys.exit(exit_code)

    if args.skills_action == "import":
        _run_skills_import(args)
        return

    if args.skills_action == "install":
        _run_skills_install(args)
        return

    if args.skills_action == "uninstall":
        _run_skills_uninstall(args)
        return

    if args.skills_action == "reload":
        # Ping the running server to reload its singleton registry.
        import urllib.error
        import urllib.request

        # Default to local dev server; users can override via CI_AGENT_API_URL.
        api_url = os.getenv("CI_AGENT_API_URL", "http://localhost:8000").rstrip("/")
        url = f"{api_url}/api/skills/reload"
        req = urllib.request.Request(url, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            print(f"Reloaded {data.get('active_count', 0)} skill(s) on {api_url}")
            for s in data.get("skills", []):
                print(f"  - {s['dimension']:<16} {s['name']:<24} ({s['source']})")
            sys.exit(0)
        except urllib.error.URLError as e:
            print(f"Error: could not reach {url}: {e.reason}", file=sys.stderr)
            print("Is the API server running? Start it with: ci-agent serve", file=sys.stderr)
            sys.exit(1)

    registry = SkillRegistry().load()

    if args.skills_action == "list":
        skills = registry.get_active_skills()
        if not skills:
            print("No skills found.")
            return

        print(f"{'DIMENSION':<16} {'NAME':<24} {'SOURCE':<10} {'ENABLED':<10} {'PRIORITY'}")
        for s in skills:
            print(f"{s.dimension:<16} {s.name:<24} {s.source:<10} {str(s.enabled):<10} {s.priority}")

    elif args.skills_action == "show":
        skills = registry.get_active_skills()
        skill = next((s for s in skills if s.name == args.name), None)
        # Also check disabled skills
        if not skill:
            all_skills = list(registry._skills.values())
            skill = next((s for s in all_skills if s.name == args.name), None)
        if not skill:
            print(f"Skill not found: {args.name}", file=sys.stderr)
            sys.exit(1)

        print(f"Name:          {skill.name}")
        print(f"Description:   {skill.description}")
        print(f"Dimension:     {skill.dimension}")
        print(f"Source:        {skill.source} ({skill.source_path})")
        print(f"Tools:         {', '.join(skill.tools)}")
        print(f"Requires Data: {', '.join(skill.requires_data)}")
        print(f"Enabled:       {skill.enabled}")
        print(f"Priority:      {skill.priority}")

    else:
        print("Usage: ci-agent skills {list|show|validate|reload|import|install|uninstall}")
        sys.exit(1)


def run_chat(args):
    """启动 TUI 交互模式。

    通过设置环境变量来传递 model override，而非直接修改 config 对象，
    这样 run_tui() 内部再次调用 AgentConfig.load() 时能自动感知。
    """
    from pathlib import Path

    from ci_optimizer.tui.app import run_tui

    repo_path = Path(args.repo) if hasattr(args, "repo") and args.repo else None

    # Apply model override
    if hasattr(args, "model") and args.model:
        os.environ["CI_AGENT_MODEL"] = args.model

    asyncio.run(run_tui(repo_path=repo_path))


def main():
    load_dotenv()
    args = parse_args()

    if args.command == "analyze":
        asyncio.run(run_analyze(args))
    elif args.command == "serve":
        run_serve(args)
    elif args.command == "config":
        run_config(args)
    elif args.command == "skills":
        run_skills(args)
    elif args.command == "chat":
        run_chat(args)
    else:
        # No command given → show usage guide
        print("🤖 CI Agent — AI-powered CI/CD pipeline analyzer\n")
        print("使用方式:")
        print("  ci-agent serve              启动后端 Server (TUI 和 Web 都需要)")
        print("  ci-agent chat               启动 TUI 交互模式 (连接 Server)")
        print("  ci-agent analyze <repo>     一次性分析 (不需要 Server)")
        print("  ci-agent config show        查看配置")
        print("  ci-agent skills list        查看分析技能")
        print()
        print("快速开始:")
        print("  1. 启动 Server:   ci-agent serve")
        print("  2. 新终端启动 TUI: ci-agent chat")
        print("  3. 或启动 Web:    cd web && npm run dev")
        print()
        print("运行 'ci-agent --help' 查看所有命令")


if __name__ == "__main__":
    main()
