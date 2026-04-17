"""GitHub Issue Triage Bot.

Polled by .github/workflows/issue-triage.yml every 6 hours. Classifies
open issues, answers doc-grounded questions, and applies labels.
See docs/superpowers/specs/2026-04-16-issue-triage-bot-design.md.
"""
from __future__ import annotations

import os
import pathlib
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


def main() -> int:
    print("issue_triage: placeholder main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
