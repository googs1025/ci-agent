"""Report formatter — converts analysis results to Markdown and JSON."""
# 架构角色：分析结果的序列化层，将 AnalysisResult 转换为多种可消费格式。
# 核心职责：
#   1. format_summary_markdown()  — 为 Web UI 顶部摘要区生成精简 Markdown（不含 findings 明细）
#   2. format_markdown()          — 为 CLI 导出生成含完整 findings 表格和代码片段的详细报告
#   3. format_json()              — 生成机器可读的 JSON 结构，供 API 或后续处理使用
#   4. I18N 字典                  — 支持 en / zh 两种输出语言，通过 language 参数在调用时选择
# 与其他模块的关系：
#   - orchestrator.AnalysisResult 是输入数据结构，包含 findings、executive_summary、stats 等字段
#   - prefetch.AnalysisContext 提供仓库元数据（owner/repo、workflow 文件列表、过滤条件）
#   - API 层和 CLI 命令各自调用对应的 format_* 函数，formatter 本身无副作用

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

# i18n strings
I18N = {
    "en": {
        "title": "CI Pipeline Analysis Report",
        "repository": "Repository",
        "date": "Date",
        "workflows": "Workflows",
        "duration": "Duration",
        "findings": "Findings",
        "executive_summary": "Executive Summary",
        "no_summary": "_No summary available._",
        "no_findings": "_No findings in this dimension._",
        "severity": "Severity",
        "finding": "Finding",
        "file": "File",
        "suggestion": "Suggestion",
        "impact": "Impact",
        "current_code": "Current code",
        "suggested_code": "Suggested code",
        "filters_applied": "Filters Applied",
        "dimensions": {
            "efficiency": "Execution Efficiency",
            "security": "Security & Best Practices",
            "cost": "Cost Optimization",
            "error": "Error Analysis",
        },
    },
    "zh": {
        "title": "CI 流水线分析报告",
        "repository": "仓库",
        "date": "日期",
        "workflows": "工作流",
        "duration": "耗时",
        "findings": "发现",
        "executive_summary": "总结摘要",
        "no_summary": "_暂无摘要。_",
        "no_findings": "_该维度暂无发现。_",
        "severity": "严重度",
        "finding": "发现",
        "file": "文件",
        "suggestion": "建议",
        "impact": "影响",
        "current_code": "当前代码",
        "suggested_code": "建议代码",
        "filters_applied": "已应用的过滤条件",
        "dimensions": {
            "efficiency": "执行效率",
            "security": "安全与最佳实践",
            "cost": "成本优化",
            "error": "错误分析",
        },
    },
}


def _get_i18n(language: str) -> dict:
    return I18N.get(language, I18N["en"])


def format_summary_markdown(result: AnalysisResult, ctx: AnalysisContext, language: str = "en") -> str:
    """为 Web UI 顶部摘要区生成精简 Markdown，只含元数据头部和 executive_summary 文本。
    有意省略 per-dimension findings——Web UI 会将它们渲染为下方的可交互卡片，
    在此处重复会导致摘要区过长。
    """
    t = _get_i18n(language)
    repo_name = f"{ctx.owner}/{ctx.repo}" if ctx.owner else str(ctx.local_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stats = result.stats or {}

    lines = [
        f"**{t['repository']}:** {repo_name}  ",
        f"**{t['date']}:** {now}  ",
        f"**{t['workflows']}:** {len(ctx.workflow_files)} files  ",
        f"**{t['duration']}:** {result.duration_ms / 1000:.1f}s  ",
        f"**{t['findings']}:** {stats.get('total_findings', 0)} "
        f"({stats.get('critical', 0)} critical, "
        f"{stats.get('major', 0)} major, "
        f"{stats.get('minor', 0)} minor, "
        f"{stats.get('info', 0)} info)",
        "",
    ]

    if result.executive_summary:
        lines.append(result.executive_summary.strip())
    else:
        lines.append(t["no_summary"])

    return "\n".join(lines)


def format_markdown(result: AnalysisResult, ctx: AnalysisContext, language: str = "en") -> str:
    """生成含完整 findings 表格和代码对比片段的详细 Markdown 报告，供 CLI 导出使用。
    findings 先按 dimension 分组，每组先输出汇总表格，再输出带代码片段的详细描述。
    表格单元格中的竖线字符需转义（\\|），防止破坏 Markdown 表格格式。
    """
    t = _get_i18n(language)
    repo_name = f"{ctx.owner}/{ctx.repo}" if ctx.owner else str(ctx.local_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# {t['title']}",
        "",
        f"**{t['repository']}:** {repo_name}",
        f"**{t['date']}:** {now}",
        f"**{t['workflows']}:** {len(ctx.workflow_files)} files",
        f"**{t['duration']}:** {result.duration_ms / 1000:.1f}s",
        f"**{t['findings']}:** {result.stats.get('total_findings', 0)} "
        f"({result.stats.get('critical', 0)} critical, "
        f"{result.stats.get('major', 0)} major, "
        f"{result.stats.get('minor', 0)} minor, "
        f"{result.stats.get('info', 0)} info)",
        "",
        "---",
        "",
        f"## {t['executive_summary']}",
        "",
        result.executive_summary or t["no_summary"],
        "",
    ]

    # Group findings by dimension
    dim_titles = t["dimensions"]
    dimensions = {
        "efficiency": (dim_titles["efficiency"], []),
        "security": (dim_titles["security"], []),
        "cost": (dim_titles["cost"], []),
        "error": (dim_titles["error"], []),
    }

    for f in result.findings:
        dim = f.get("dimension", "info")
        if dim in dimensions:
            dimensions[dim][1].append(f)

    for dim_key, (dim_title, findings) in dimensions.items():
        lines.append(f"## {dim_title}")
        lines.append("")

        if not findings:
            lines.append(t["no_findings"])
            lines.append("")
            continue

        lines.append(f"| # | {t['severity']} | {t['finding']} | {t['file']} | {t['suggestion']} |")
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

        # Add detailed descriptions with code snippets
        for i, f in enumerate(findings, 1):
            if f.get("description") or f.get("code_snippet") or f.get("suggested_code"):
                file_ref = f"`{f['file']}:{f['line']}`" if f.get("file") and f.get("line") else ""
                lines.append(f"**{i}. {f.get('title', '')}** {file_ref}")
                lines.append("")
                if f.get("description"):
                    lines.append(f"{f['description']}")
                    lines.append("")
                if f.get("code_snippet"):
                    lines.append(f"**{t.get('current_code', 'Current code')}:**")
                    lines.append("```yaml")
                    lines.append(f"{f['code_snippet']}")
                    lines.append("```")
                    lines.append("")
                if f.get("suggested_code"):
                    lines.append(f"**{t.get('suggested_code', 'Suggested code')}:**")
                    lines.append("```yaml")
                    lines.append(f"{f['suggested_code']}")
                    lines.append("```")
                    lines.append("")
                if f.get("impact"):
                    lines.append(f"**{t['impact']}:** {f['impact']}")
                    lines.append("")

    # Filters applied
    if ctx.filters:
        filter_dict = ctx.filters.to_dict()
        if filter_dict:
            lines.append("---")
            lines.append("")
            lines.append(f"## {t['filters_applied']}")
            lines.append("")
            for k, v in filter_dict.items():
                lines.append(f"- **{k}:** {v}")
            lines.append("")

    return "\n".join(lines)


def format_json(result: AnalysisResult, ctx: AnalysisContext, language: str = "en") -> str:
    """将分析结果序列化为 JSON 字符串，供 API 响应或机器消费使用。
    若 ctx.usage_stats_json_path 存在，将其内容合并进输出（用于携带 token 用量统计）。
    """
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
        "language": language,
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
