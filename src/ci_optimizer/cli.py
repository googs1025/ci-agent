"""CLI entry point for ci-agent."""

import argparse
import asyncio
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
    analyze.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # serve command
    serve = subparsers.add_parser("serve", help="Start the API server")
    serve.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    serve.add_argument("--port", "-p", type=int, default=8000, help="Port to bind (default: 8000)")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    return parser.parse_args()


async def run_analyze(args):
    from ci_optimizer.filters import AnalysisFilters
    from ci_optimizer.resolver import resolve_input
    from ci_optimizer.prefetch import prepare_context
    from ci_optimizer.agents.orchestrator import run_analysis
    from ci_optimizer.report.formatter import format_markdown, format_json

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
    result = await run_analysis(ctx)

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


def main():
    load_dotenv()
    args = parse_args()

    if args.command == "analyze":
        asyncio.run(run_analyze(args))
    elif args.command == "serve":
        run_serve(args)
    else:
        print("Usage: ci-agent {analyze|serve} [options]")
        print("Run 'ci-agent --help' for more information.")
        sys.exit(1)


if __name__ == "__main__":
    main()
