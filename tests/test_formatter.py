"""Tests for report formatter."""

import json

import pytest

from ci_optimizer.agents.orchestrator import AnalysisResult
from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.prefetch import AnalysisContext
from ci_optimizer.report.formatter import format_json, format_markdown


@pytest.fixture
def sample_result():
    return AnalysisResult(
        executive_summary="Top priority: pin actions to SHA commits.",
        findings=[
            {
                "dimension": "efficiency",
                "severity": "major",
                "title": "Missing dependency cache",
                "description": "No caching configured for npm dependencies",
                "file": ".github/workflows/ci.yml",
                "line": 15,
                "suggestion": "Add actions/cache with npm lock file hash",
                "impact": "30% faster builds",
            },
            {
                "dimension": "security",
                "severity": "critical",
                "title": "Unpinned action version",
                "description": "Using @main instead of SHA for third-party action",
                "file": ".github/workflows/deploy.yml",
                "line": 8,
                "suggestion": "Pin to full SHA commit",
                "impact": "Prevents supply chain attacks",
            },
            {
                "dimension": "cost",
                "severity": "minor",
                "title": "macOS runner unnecessary",
                "description": "Deploy job uses macos-latest but only runs npm commands",
                "file": ".github/workflows/deploy.yml",
                "line": 12,
                "suggestion": "Switch to ubuntu-latest",
                "impact": "10x cost reduction for this job",
            },
        ],
        stats={
            "total_findings": 3,
            "critical": 1,
            "major": 1,
            "minor": 1,
            "info": 0,
        },
        duration_ms=5000,
        cost_usd=0.05,
    )


@pytest.fixture
def sample_context(tmp_path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text("name: CI")
    (wf_dir / "deploy.yml").write_text("name: Deploy")

    return AnalysisContext(
        local_path=tmp_path,
        owner="octocat",
        repo="hello-world",
        workflow_files=[wf_dir / "ci.yml", wf_dir / "deploy.yml"],
    )


class TestFormatMarkdown:
    def test_contains_header(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "# CI Pipeline Analysis Report" in md
        assert "octocat/hello-world" in md

    def test_contains_summary(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "Executive Summary" in md
        assert "pin actions to SHA" in md

    def test_contains_all_dimensions(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "Execution Efficiency" in md
        assert "Security & Best Practices" in md
        assert "Cost Optimization" in md
        assert "Error Analysis" in md

    def test_contains_findings(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "Missing dependency cache" in md
        assert "Unpinned action version" in md
        assert "macOS runner unnecessary" in md

    def test_contains_stats(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "3" in md  # total findings
        assert "1 critical" in md

    def test_empty_dimension_shows_message(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "No findings in this dimension" in md  # error dimension is empty

    def test_with_filters(self, sample_result, sample_context):
        sample_context.filters = AnalysisFilters(
            workflows=["ci.yml"], branches=["main"]
        )
        md = format_markdown(sample_result, sample_context)
        assert "Filters Applied" in md
        assert "ci.yml" in md
        assert "main" in md

    def test_escapes_pipes(self, sample_context):
        result = AnalysisResult(
            findings=[{
                "dimension": "efficiency",
                "severity": "info",
                "title": "Use A | B pattern",
                "description": "test",
                "file": "ci.yml",
                "suggestion": "Do X | Y",
            }],
            stats={"total_findings": 1, "critical": 0, "major": 0, "minor": 0, "info": 1},
            duration_ms=100,
        )
        md = format_markdown(result, sample_context)
        assert "Use A \\| B pattern" in md


class TestFormatJson:
    def test_valid_json(self, sample_result, sample_context):
        output = format_json(sample_result, sample_context)
        data = json.loads(output)
        assert data["repository"] == "octocat/hello-world"

    def test_contains_findings(self, sample_result, sample_context):
        output = format_json(sample_result, sample_context)
        data = json.loads(output)
        assert len(data["findings"]) == 3

    def test_contains_stats(self, sample_result, sample_context):
        output = format_json(sample_result, sample_context)
        data = json.loads(output)
        assert data["stats"]["total_findings"] == 3
        assert data["stats"]["critical"] == 1

    def test_contains_metadata(self, sample_result, sample_context):
        output = format_json(sample_result, sample_context)
        data = json.loads(output)
        assert data["workflow_count"] == 2
        assert data["duration_ms"] == 5000
        assert "date" in data

    def test_with_filters(self, sample_result, sample_context):
        sample_context.filters = AnalysisFilters(branches=["main"])
        output = format_json(sample_result, sample_context)
        data = json.loads(output)
        assert "filters" in data
        assert data["filters"]["branches"] == ["main"]

    def test_local_path_fallback(self, sample_result, tmp_path):
        ctx = AnalysisContext(local_path=tmp_path, workflow_files=[])
        output = format_json(sample_result, ctx)
        data = json.loads(output)
        assert str(tmp_path) in data["repository"]

    def test_json_includes_language(self, sample_result, sample_context):
        output = format_json(sample_result, sample_context, language="zh")
        data = json.loads(output)
        assert data["language"] == "zh"


class TestChineseOutput:
    """Test Chinese language output."""

    def test_markdown_chinese_headers(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context, language="zh")
        assert "# CI 流水线分析报告" in md
        assert "**仓库:**" in md
        assert "**日期:**" in md
        assert "总结摘要" in md

    def test_markdown_chinese_dimensions(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context, language="zh")
        assert "执行效率" in md
        assert "安全与最佳实践" in md
        assert "成本优化" in md
        assert "错误分析" in md

    def test_markdown_chinese_empty_dimension(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context, language="zh")
        assert "该维度暂无发现" in md  # error dimension has no findings

    def test_markdown_chinese_filters(self, sample_result, sample_context):
        sample_context.filters = AnalysisFilters(branches=["main"])
        md = format_markdown(sample_result, sample_context, language="zh")
        assert "已应用的过滤条件" in md

    def test_english_is_default(self, sample_result, sample_context):
        md = format_markdown(sample_result, sample_context)
        assert "# CI Pipeline Analysis Report" in md
        assert "Executive Summary" in md
