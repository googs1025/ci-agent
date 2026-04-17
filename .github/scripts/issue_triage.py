"""GitHub Issue Triage Bot.

Polled by .github/workflows/issue-triage.yml every 6 hours. Classifies
open issues, answers doc-grounded questions, and applies labels.
See docs/superpowers/specs/2026-04-16-issue-triage-bot-design.md.
"""
from __future__ import annotations

import os
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


def main() -> int:
    print("issue_triage: placeholder main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
