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


from datetime import datetime, timedelta, timezone


def _issue(**overrides) -> dict:
    base = {
        "number": 1,
        "state": "open",
        "comments": 0,
        "labels": [],
        "user": {"type": "User", "login": "alice"},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": "Test",
        "body": "Body",
    }
    base.update(overrides)
    return base


def test_is_eligible_happy_path():
    assert issue_triage.is_eligible(_issue()) is True


def test_is_eligible_rejects_pull_request():
    assert issue_triage.is_eligible(_issue(pull_request={"url": "..."})) is False


def test_is_eligible_rejects_closed():
    assert issue_triage.is_eligible(_issue(state="closed")) is False


def test_is_eligible_rejects_with_comments():
    assert issue_triage.is_eligible(_issue(comments=1)) is False


def test_is_eligible_rejects_ai_replied_label():
    assert issue_triage.is_eligible(_issue(labels=[{"name": "ai-replied"}])) is False


def test_is_eligible_rejects_no_bot_label():
    assert issue_triage.is_eligible(_issue(labels=[{"name": "no-bot"}])) is False


def test_is_eligible_rejects_bot_author():
    assert issue_triage.is_eligible(_issue(user={"type": "Bot", "login": "dependabot[bot]"})) is False


def test_is_eligible_rejects_stale_issue():
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    assert issue_triage.is_eligible(_issue(created_at=old)) is False


def test_parse_result_valid_question():
    raw = '{"category":"question","needs_info":false,"missing_info":[],"answer":"Run `make install`.","confidence":"high"}'
    result = issue_triage.parse_result(raw)
    assert result["category"] == "question"
    assert result["answer"] == "Run `make install`."
    assert result["confidence"] == "high"
    assert result["_parse_failed"] is False


def test_parse_result_low_confidence_drops_answer():
    raw = '{"category":"question","needs_info":false,"missing_info":[],"answer":"maybe this","confidence":"low"}'
    result = issue_triage.parse_result(raw)
    assert result["answer"] is None


def test_parse_result_non_json_falls_back_to_unknown():
    result = issue_triage.parse_result("Sorry, I can't help with that.")
    assert result["category"] == "unknown"
    assert result["answer"] is None
    assert result["_parse_failed"] is True


def test_parse_result_invalid_category_falls_back():
    raw = '{"category":"FIXME","needs_info":false,"missing_info":[],"answer":null,"confidence":"high"}'
    result = issue_triage.parse_result(raw)
    assert result["category"] == "unknown"
    assert result["_parse_failed"] is True


def test_parse_result_strips_markdown_fences():
    raw = '```json\n{"category":"bug","needs_info":true,"missing_info":["version"],"answer":null,"confidence":"high"}\n```'
    result = issue_triage.parse_result(raw)
    assert result["category"] == "bug"
    assert result["missing_info"] == ["version"]


def test_render_comment_marker_always_present():
    result = {"category": "bug", "needs_info": False, "missing_info": [], "answer": None, "confidence": "high"}
    body = issue_triage.render_comment(result, "en")
    assert body.startswith("<!-- ci-agent-issue-bot v1 -->")


def test_render_comment_needs_info_zh_lists_missing():
    result = {
        "category": "bug",
        "needs_info": True,
        "missing_info": ["版本号", "复现步骤"],
        "answer": None,
        "confidence": "high",
    }
    body = issue_triage.render_comment(result, "zh")
    assert "版本号" in body
    assert "复现步骤" in body
    assert "感谢提交" in body


def test_render_comment_needs_info_en_lists_missing():
    result = {
        "category": "bug",
        "needs_info": True,
        "missing_info": ["version", "reproduction steps"],
        "answer": None,
        "confidence": "high",
    }
    body = issue_triage.render_comment(result, "en")
    assert "version" in body
    assert "reproduction steps" in body
    assert "Thanks for opening" in body


def test_render_comment_question_answer_zh():
    result = {
        "category": "question",
        "needs_info": False,
        "missing_info": [],
        "answer": "用 `pip install -e .` 安装。",
        "confidence": "high",
    }
    body = issue_triage.render_comment(result, "zh")
    assert "用 `pip install -e .` 安装。" in body
    assert "自动生成" in body


def test_render_comment_question_answer_en():
    result = {
        "category": "question",
        "needs_info": False,
        "missing_info": [],
        "answer": "Run `pip install -e .`.",
        "confidence": "high",
    }
    body = issue_triage.render_comment(result, "en")
    assert "Run `pip install -e .`." in body
    assert "automatically generated" in body.lower()


def test_render_comment_short_ack_for_feature_en():
    result = {"category": "feature", "needs_info": False, "missing_info": [], "answer": None, "confidence": "medium"}
    body = issue_triage.render_comment(result, "en")
    assert "feature" in body.lower()
    assert "maintainer" in body.lower()


def test_render_comment_escapes_html_comment_in_answer():
    result = {
        "category": "question",
        "needs_info": False,
        "missing_info": [],
        "answer": "Try this: <!-- evil -->",
        "confidence": "high",
    }
    body = issue_triage.render_comment(result, "en")
    assert "<!-- evil -->" not in body
    assert "evil" in body


def test_derive_labels_bug_with_needs_info():
    result = {"category": "bug", "needs_info": True, "missing_info": ["x"], "answer": None, "confidence": "high", "_parse_failed": False}
    labels = issue_triage.derive_labels(result)
    assert set(labels) == {"ai-replied", "type:bug", "needs-info"}


def test_derive_labels_question_no_needs_info():
    result = {"category": "question", "needs_info": False, "missing_info": [], "answer": "x", "confidence": "high", "_parse_failed": False}
    labels = issue_triage.derive_labels(result)
    assert set(labels) == {"ai-replied", "type:question"}


def test_derive_labels_parse_failed():
    result = {"category": "unknown", "needs_info": False, "missing_info": [], "answer": None, "confidence": "low", "_parse_failed": True}
    labels = issue_triage.derive_labels(result)
    assert set(labels) == {"ai-replied", "ai-parse-failed"}
