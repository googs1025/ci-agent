"""GitHub Issue Triage Bot.

Polled by .github/workflows/issue-triage.yml every 6 hours. Classifies
open issues, answers doc-grounded questions, and applies labels.
See docs/superpowers/specs/2026-04-16-issue-triage-bot-design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import pathlib
import re
import sys

# ─── Config ────────────────────────────────────────────────
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
DRY_RUN = os.environ.get("DRY_RUN") == "true"
MAX_ISSUES = int(os.environ.get("MAX_ISSUES", "10"))

MODEL = "gpt-4o-mini"
MODELS_ENDPOINT = "https://models.github.ai/inference/chat/completions"
DEDUP_LABEL = "ai-replied"
BOT_MARKER = "<!-- ci-agent-issue-bot v1 -->"
MAX_ISSUE_AGE_DAYS = 30
MAX_BODY_CHARS = 6000
MAX_CONTEXT_CHARS = 20_000

# ─── Language detection ────────────────────────────────────
def detect_language(text: str) -> str:
    """Return 'zh' if >= 15% of chars are CJK, else 'en'."""
    if not text:
        return "en"
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if cjk / len(text) >= 0.15 else "en"


# ─── Context loader ────────────────────────────────────────


def load_context(lang: str, repo_root: pathlib.Path | None = None) -> str:
    """Concat README + docs/guides/{lang}/*.md + CONTRIBUTING.

    Truncates to MAX_CONTEXT_CHARS. Missing files are logged and skipped.
    """
    root = repo_root or pathlib.Path(__file__).resolve().parents[2]
    chunks: list[str] = []

    def _read(path: pathlib.Path, label: str) -> None:
        if not path.exists():
            print(f"[context] missing: {path}", file=sys.stderr)
            return
        chunks.append(f"\n\n## {label}\n\n{path.read_text(encoding='utf-8')}")

    _read(root / "README.md", "README")

    guides_dir = root / "docs" / "guides" / lang
    if guides_dir.is_dir():
        for md in sorted(guides_dir.glob("*.md")):
            _read(md, f"docs/guides/{lang}/{md.name}")
    else:
        print(f"[context] missing: {guides_dir}", file=sys.stderr)

    _read(root / "CONTRIBUTING.md", "CONTRIBUTING")

    joined = "".join(chunks)
    if len(joined) > MAX_CONTEXT_CHARS:
        truncation_msg = "\n\n[... truncated ...]"
        max_content = MAX_CONTEXT_CHARS - len(truncation_msg)
        joined = joined[:max_content] + truncation_msg
    return joined


# ─── Issue eligibility filter ──────────────────────────────
SKIP_LABELS = {"ai-replied", "no-bot", "spam"}


def is_eligible(issue: dict) -> bool:
    """Apply the 6-point filter from spec §7."""
    if "pull_request" in issue:
        return False
    if issue.get("state") != "open":
        return False
    if issue.get("comments", 0) > 0:
        return False
    label_names = {lbl["name"] for lbl in issue.get("labels") or []}
    if label_names & SKIP_LABELS:
        return False
    if (issue.get("user") or {}).get("type") == "Bot":
        return False
    created = issue.get("created_at")
    if created:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - dt > timedelta(days=MAX_ISSUE_AGE_DAYS):
            return False
    return True


# ─── LLM output parsing ────────────────────────────────────
VALID_CATEGORIES = {"bug", "question", "feature", "duplicate", "unknown"}
VALID_CONFIDENCE = {"high", "medium", "low"}

_FALLBACK = {
    "category": "unknown",
    "needs_info": False,
    "missing_info": [],
    "answer": None,
    "confidence": "low",
    "_parse_failed": True,
}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_result(raw: str) -> dict:
    """Parse LLM output into the diagnosis dict, with fallback on any error."""
    if not raw:
        return dict(_FALLBACK)

    cleaned = _FENCE_RE.sub("", raw).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return dict(_FALLBACK)

    if not isinstance(data, dict):
        return dict(_FALLBACK)

    category = data.get("category")
    confidence = data.get("confidence", "low")
    if category not in VALID_CATEGORIES or confidence not in VALID_CONFIDENCE:
        return dict(_FALLBACK)

    answer = data.get("answer")
    if confidence == "low":
        answer = None

    return {
        "category": category,
        "needs_info": bool(data.get("needs_info", False)),
        "missing_info": list(data.get("missing_info") or []),
        "answer": answer,
        "confidence": confidence,
        "_parse_failed": False,
    }


# ─── Comment rendering ─────────────────────────────────────

_CATEGORY_LABELS_ZH = {
    "bug": "bug",
    "question": "question",
    "feature": "feature",
    "duplicate": "duplicate",
    "unknown": "issue",
}
_CATEGORY_LABELS_EN = _CATEGORY_LABELS_ZH

_FOOTER_ZH = "此回复由机器人自动生成。"
_FOOTER_ZH_WITH_DOCS = (
    "此回复由机器人根据仓库文档自动生成，可能不完全准确。相关文档："
    "[使用指南](docs/guides/zh/usage-guide.md) · [部署指南](docs/guides/zh/deployment.md)"
)
_FOOTER_EN = "This reply was automatically generated."
_FOOTER_EN_WITH_DOCS = (
    "This reply was automatically generated from the repo's docs and may not be fully accurate. "
    "Relevant docs: [Usage Guide](docs/guides/en/usage-guide.md) · "
    "[Deployment Guide](docs/guides/en/deployment.md)"
)


def _escape_answer(text: str) -> str:
    """Neutralize HTML comments to prevent tampering with BOT_MARKER."""
    return text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")


def render_comment(result: dict, lang: str) -> str:
    """Render the final comment body. Always starts with BOT_MARKER."""
    category = result["category"]
    lines = [BOT_MARKER, ""]

    if result.get("needs_info") and result.get("missing_info"):
        if lang == "zh":
            lines.append("感谢提交 issue。为了更快排查，请补充以下信息：")
            lines.append("")
            for item in result["missing_info"]:
                lines.append(f"- {item}")
            lines.append("")
            lines.append("补充后维护者会尽快响应。")
            lines.append("")
            lines.append("---")
            lines.append(f"> {_FOOTER_ZH}")
        else:
            lines.append("Thanks for opening this issue. Before we can dig in, we need a bit more info:")
            lines.append("")
            for item in result["missing_info"]:
                lines.append(f"- {item}")
            lines.append("")
            lines.append("Once you've added these, a maintainer will follow up.")
            lines.append("")
            lines.append("---")
            lines.append(f"> {_FOOTER_EN}")

    elif category == "question" and result.get("answer"):
        lines.append(_escape_answer(result["answer"]))
        lines.append("")
        lines.append("---")
        lines.append(f"> {_FOOTER_ZH_WITH_DOCS if lang == 'zh' else _FOOTER_EN_WITH_DOCS}")

    else:
        cat_label = (_CATEGORY_LABELS_ZH if lang == "zh" else _CATEGORY_LABELS_EN).get(category, category)
        if lang == "zh":
            lines.append(f"收到，已分类为 **{cat_label}**，维护者会尽快查看。")
            lines.append("")
            lines.append("---")
            lines.append(f"> {_FOOTER_ZH}")
        else:
            lines.append(f"Received — classified as **{cat_label}**. A maintainer will take a look soon.")
            lines.append("")
            lines.append("---")
            lines.append(f"> {_FOOTER_EN}")

    return "\n".join(lines)


def main() -> int:
    print("issue_triage: placeholder main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
