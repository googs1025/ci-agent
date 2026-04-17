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