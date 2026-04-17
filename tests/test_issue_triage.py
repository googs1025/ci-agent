"""Unit tests for .github/scripts/issue_triage.py (pure functions only)."""
from __future__ import annotations

import importlib.util
import pathlib

_SCRIPT = pathlib.Path(__file__).parent.parent / ".github" / "scripts" / "issue_triage.py"
_spec = importlib.util.spec_from_file_location("issue_triage", _SCRIPT)
assert _spec and _spec.loader
issue_triage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(issue_triage)


def test_module_loads():
    assert issue_triage.MODEL == "gpt-4o-mini"
    assert issue_triage.DEDUP_LABEL == "ai-replied"


def test_detect_language_pure_english():
    assert issue_triage.detect_language("Why does the build fail?") == "en"


def test_detect_language_pure_chinese():
    assert issue_triage.detect_language("构建为什么会失败？") == "zh"


def test_detect_language_mixed_majority_en():
    text = "The build fails with a weird 中 character in the log."
    assert issue_triage.detect_language(text) == "en"


def test_detect_language_mixed_over_threshold_is_zh():
    assert issue_triage.detect_language("build 构建失败了 why") == "zh"


def test_detect_language_empty_defaults_to_en():
    assert issue_triage.detect_language("") == "en"


_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "issue_triage_docs"


def test_load_context_en_includes_readme_and_guides():
    ctx = issue_triage.load_context("en", repo_root=_FIXTURE)
    assert "Fake Project" in ctx
    assert "Usage (EN)" in ctx
    assert "Contributing" in ctx
    assert "使用指南" not in ctx


def test_load_context_zh_uses_chinese_guides():
    ctx = issue_triage.load_context("zh", repo_root=_FIXTURE)
    assert "使用指南" in ctx
    assert "Usage (EN)" not in ctx
    assert "Fake Project" in ctx


def test_load_context_missing_files_soft_fail(tmp_path):
    (tmp_path / "README.md").write_text("Only README")
    ctx = issue_triage.load_context("en", repo_root=tmp_path)
    assert "Only README" in ctx


def test_load_context_truncates_to_max_chars(tmp_path):
    (tmp_path / "README.md").write_text("X" * 50_000)
    ctx = issue_triage.load_context("en", repo_root=tmp_path)
    assert len(ctx) <= issue_triage.MAX_CONTEXT_CHARS