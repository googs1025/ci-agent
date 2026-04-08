"""Shared prompt text and language instructions for all agent engines."""

LANGUAGE_INSTRUCTIONS = {
    "zh": (
        "\n## 语言要求\n"
        "你必须使用**中文**输出所有内容，包括 executive_summary、每个 finding 的 "
        "title、description、suggestion 和 impact 字段。JSON key 保持英文不变。"
    ),
    "en": (
        "\n## Language\n"
        "Output all content in **English**, including executive_summary and all "
        "finding fields (title, description, suggestion, impact). JSON keys stay as-is."
    ),
}

FINDING_JSON_FORMAT = """
Return ONLY a JSON object (no markdown, no explanation outside the JSON):

```json
{
  "findings": [
    {
      "severity": "critical|major|minor|info",
      "title": "Short description of the finding",
      "description": "Detailed explanation",
      "file": "relative/path/to/workflow.yml",
      "line": 42,
      "suggestion": "Specific change to make",
      "impact": "Estimated improvement"
    }
  ]
}
```

Severity guide:
- critical: Severe issue with major impact
- major: Significant issue (20-50% improvement potential)
- minor: Small improvement (5-20%)
- info: Best practice suggestion
"""

ORCHESTRATOR_PROMPT = """You are a CI pipeline analysis orchestrator. Your role is to coordinate analysis across 4 dimensions and produce a comprehensive report.

## Dimensions
1. **Execution Efficiency**: parallelization, caching, conditional execution, matrix strategy
2. **Security & Best Practices**: permissions, action pinning, secrets, supply chain
3. **Cost Optimization**: runner selection, trigger optimization, job consolidation
4. **Error Analysis**: failure patterns, flaky tests, root causes

## Output Format

Produce a JSON object:

```json
{
  "executive_summary": "Top 5 most impactful recommendations across all dimensions, ordered by priority",
  "dimensions": {
    "efficiency": { "findings": [...] },
    "security": { "findings": [...] },
    "cost": { "findings": [...] },
    "error": { "findings": [...] }
  },
  "stats": {
    "total_findings": 0,
    "critical": 0,
    "major": 0,
    "minor": 0,
    "info": 0
  }
}
```

Each finding: {severity, title, description, file, line, suggestion, impact, dimension}
"""
