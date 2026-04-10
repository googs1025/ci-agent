"""CLI entry point for ci-agent."""

import argparse
import asyncio
import json
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

    config_show = config_sub.add_parser("show", help="Show current configuration")

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

    return parser.parse_args()


def _build_config(args) -> "AgentConfig":
    """Build AgentConfig from saved config + CLI overrides."""
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
    from ci_optimizer.config import AgentConfig
    from ci_optimizer.filters import AnalysisFilters
    from ci_optimizer.resolver import resolve_input
    from ci_optimizer.prefetch import prepare_context
    from ci_optimizer.agents.orchestrator import run_analysis
    from ci_optimizer.report.formatter import format_markdown, format_json

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
        f"\nAnalysis complete: {result.stats.get('total_findings', 0)} findings "
        f"in {result.duration_ms / 1000:.1f}s",
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
    from ci_optimizer.config import AgentConfig, CONFIG_FILE

    if args.config_action == "show":
        config = AgentConfig.load()
        print(json.dumps(config.to_display_dict(), indent=2))

    elif args.config_action == "set":
        config = AgentConfig.load()
        key = args.key
        value = args.value

        if not hasattr(config, key):
            print(f"Error: Unknown config key '{key}'", file=sys.stderr)
            print(f"Available keys: model, fallback_model, anthropic_api_key, github_token, max_turns", file=sys.stderr)
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


def run_skills(args):
    from ci_optimizer.agents.skill_registry import SkillRegistry

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
        print("Usage: ci-agent skills {list|show}")
        sys.exit(1)


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
    else:
        print("Usage: ci-agent {analyze|serve|config|skills} [options]")
        print("Run 'ci-agent --help' for more information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
