"""Report formatter — converts analysis results to Markdown and JSON."""

import json
from datetime import datetime, timezone

from ci_optimizer.agents.orchestrator import AnalysisResult
from ci_optimizer.prefetch import AnalysisContext


SEVERITY_ICONS = {
    "critical": "🔴",
    "major": "🟠",
    "minor": "🟡",
    "info": "🔵",
}


def format_markdown(result: AnalysisResult, ctx: AnalysisContext) -> str:
    """Format analysis result as a Markdown report."""
    repo_name = f"{ctx.owner}/{ctx.repo}" if ctx.owner else str(ctx.local_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# CI Pipeline Analysis Report",
        f"",
        f"**Repository:** {repo_name}",
        f"**Date:** {now}",
        f"**Workflows:** {len(ctx.workflow_files)} files",
        f"**Duration:** {result.duration_ms / 1000:.1f}s",
        f"**Findings:** {result.stats.get('total_findings', 0)} "
        f"({result.stats.get('critical', 0)} critical, "
        f"{result.stats.get('major', 0)} major, "
        f"{result.stats.get('minor', 0)} minor, "
        f"{result.stats.get('info', 0)} info)",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        result.executive_summary or "_No summary available._",
        "",
    ]

    # Group findings by dimension
    dimensions = {
        "efficiency": ("Execution Efficiency", []),
        "security": ("Security & Best Practices", []),
        "cost": ("Cost Optimization", []),
        "error": ("Error Analysis", []),
    }

    for f in result.findings:
        dim = f.get("dimension", "info")
        if dim in dimensions:
            dimensions[dim][1].append(f)

    for dim_key, (dim_title, findings) in dimensions.items():
        lines.append(f"## {dim_title}")
        lines.append("")

        if not findings:
            lines.append("_No findings in this dimension._")
            lines.append("")
            continue

        lines.append("| # | Severity | Finding | File | Suggestion |")
        lines.append("|---|----------|---------|------|------------|")

        for i, f in enumerate(findings, 1):
            sev = f.get("severity", "info")
            icon = SEVERITY_ICONS.get(sev, "⚪")
            title = f.get("title", "")
            file_path = f.get("file", "-")
            suggestion = f.get("suggestion", "-")
            # Escape pipes in table cells
            title = title.replace("|", "\\|")
            suggestion = suggestion.replace("|", "\\|")
            lines.append(f"| {i} | {icon} {sev} | {title} | `{file_path}` | {suggestion} |")

        lines.append("")

        # Add detailed descriptions
        for i, f in enumerate(findings, 1):
            if f.get("description"):
                lines.append(f"**{i}. {f.get('title', '')}**")
                lines.append(f"")
                lines.append(f"{f['description']}")
                if f.get("impact"):
                    lines.append(f"")
                    lines.append(f"**Impact:** {f['impact']}")
                lines.append("")

    # Filters applied
    if ctx.filters:
        filter_dict = ctx.filters.to_dict()
        if filter_dict:
            lines.append("---")
            lines.append("")
            lines.append("## Filters Applied")
            lines.append("")
            for k, v in filter_dict.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

    return "\n".join(lines)


def format_json(result: AnalysisResult, ctx: AnalysisContext) -> str:
    """Format analysis result as JSON."""
    repo_name = f"{ctx.owner}/{ctx.repo}" if ctx.owner else str(ctx.local_path)

    # Load usage stats if available
    usage_stats = None
    if ctx.usage_stats_json_path and ctx.usage_stats_json_path.exists():
        try:
            usage_stats = json.loads(ctx.usage_stats_json_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    output = {
        "repository": repo_name,
        "date": datetime.now(timezone.utc).isoformat(),
        "workflow_count": len(ctx.workflow_files),
        "duration_ms": result.duration_ms,
        "cost_usd": result.cost_usd,
        "executive_summary": result.executive_summary,
        "stats": result.stats,
        "findings": result.findings,
    }

    if usage_stats:
        output["usage_stats"] = usage_stats
    if ctx.filters:
        output["filters"] = ctx.filters.to_dict()

    return json.dumps(output, indent=2, default=str)
