"""First-run setup wizard and config review for TUI."""

from __future__ import annotations

from ci_optimizer.config import CONFIG_FILE, AgentConfig


def needs_setup() -> bool:
    """Return True if config.json does not exist (first run)."""
    return not CONFIG_FILE.exists()


def mask_key(value: str | None) -> str:
    """Mask a sensitive value for display."""
    if not value:
        return "(未设置)"
    if len(value) > 12:
        return f"{value[:8]}...{value[-4:]}"
    return "***"
