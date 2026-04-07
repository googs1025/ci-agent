"""CLI entry point for ci-agent."""

import argparse
import asyncio
import json
import sys
from datetime import datetime
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
    analyze.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

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
    if not config.anthropic_api_key:
        print(
            "Error: No Anthropic API key configured.\n"
            "Set it via one of:\n"
            "  ci-agent config set anthropic_api_key sk-ant-...\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  ci-agent analyze --api-key sk-ant-... <repo>",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Using model: {config.model}", file=sys.stderr)

    # Build filters
    time_range = None
    if args.since and args.until:
        time_range = (
            datetime.fromisoformat(args.since),
            datetime.fromisoformat(args.until),
        )
    elif args.since:
        time_range = (datetime.fromisoformat(args.since), datetime.now())

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
    result = await run_analysis(ctx, config=config)

    # Format output
    if args.format == "json":
        output = format_json(result, ctx)
    else:
        output = format_markdown(result, ctx)

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


def main():
    load_dotenv()
    args = parse_args()

    if args.command == "analyze":
        asyncio.run(run_analyze(args))
    elif args.command == "serve":
        run_serve(args)
    elif args.command == "config":
        run_config(args)
    else:
        print("Usage: ci-agent {analyze|serve|config} [options]")
        print("Run 'ci-agent --help' for more information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
