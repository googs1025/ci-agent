"""Shared prompt text and language instructions for all agent engines."""

LANGUAGE_INSTRUCTIONS = {
    "zh": (
        "\n## 语言要求\n"
        "你必须使用**中文**输出所有内容，包括 executive_summary、每个 finding 的 "
        "title、description、suggestion 和 impact 字段。JSON key 保持英文不变。\n"
        "code_snippet 和 suggested_code 字段保留原始代码（YAML/shell），不翻译。"
    ),
    "en": (
        "\n## Language\n"
        "Output all content in **English**, including executive_summary and all "
        "finding fields (title, description, suggestion, impact). JSON keys stay as-is."
    ),
}

FINDING_JSON_FORMAT = """
## Output Format

Return ONLY a JSON object (no markdown, no explanation outside the JSON).

CRITICAL: For every finding, you MUST include `code_snippet` (the current problematic code) and `suggested_code` (your recommended replacement). Quote the exact YAML/shell from the workflow file. If the finding is about missing code, leave `code_snippet` as "" and put the code to add in `suggested_code`.

```json
{
  "findings": [
    {
      "severity": "critical|major|minor|info",
      "title": "Short description of the finding",
      "description": "Detailed explanation of WHY this is a problem",
      "file": ".github/workflows/ci.yml",
      "line": 42,
      "code_snippet": "- uses: actions/checkout@main",
      "suggested_code": "- uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11 # v4.1.7",
      "suggestion": "Pin action to full SHA commit instead of mutable branch ref",
      "impact": "Prevents supply chain attacks via tag/branch mutation"
    }
  ]
}
```

Field rules:
- `file`: Relative path from repo root (e.g. `.github/workflows/ci.yml`)
- `line`: The line number in the file where the issue starts. Use your best estimate.
- `code_snippet`: Copy the EXACT current code from the file (multi-line OK, use \\n for newlines)
- `suggested_code`: The replacement code. For new code to add, show the full block.
- Both code fields must be valid YAML/shell — the user should be able to copy-paste directly.

Severity guide:
- critical: Severe issue with major impact
- major: Significant issue (20-50% improvement potential)
- minor: Small improvement (5-20%)
- info: Best practice suggestion
"""

