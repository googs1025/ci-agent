"""Tests for tui.commands — slash command parsing and dispatch."""

from unittest.mock import MagicMock

import pytest

from ci_optimizer.tui.commands import execute, is_command


class TestIsCommand:
    def test_slash_prefix(self):
        assert is_command("/help") is True
        assert is_command("/model gpt-4") is True

    def test_not_command(self):
        assert is_command("hello") is False
        assert is_command("") is False
        assert is_command("analyze my CI") is False


class TestExecute:
    @pytest.fixture()
    def deps(self):
        """Common dependencies for execute()."""
        console = MagicMock()
        renderer = MagicMock()
        renderer.stats = MagicMock(total_cost_usd=0.123, query_count=3)
        return {
            "console": console,
            "renderer": renderer,
            "conversation": [{"role": "user", "content": "hi"}],
            "model": "claude-sonnet-4-20250514",
        }

    def test_help(self, deps):
        result = execute("/help", **deps)
        assert result.handled is True
        assert result.quit is False

    def test_clear(self, deps):
        result = execute("/clear", **deps)
        assert result.clear_history is True
        assert deps["conversation"] == []

    def test_cost(self, deps):
        result = execute("/cost", **deps)
        assert result.handled is True
        deps["renderer"].print_stats.assert_called_once()

    def test_model_show(self, deps):
        result = execute("/model", **deps)
        assert result.handled is True

    def test_model_switch(self, deps):
        result = execute("/model claude-opus-4-20250514", **deps)
        assert result.handled is True

    def test_quit(self, deps):
        result = execute("/quit", **deps)
        assert result.quit is True

    def test_exit(self, deps):
        result = execute("/exit", **deps)
        assert result.quit is True

    def test_unknown_command(self, deps):
        result = execute("/foobar", **deps)
        assert result.handled is True  # still handled, just prints error

    def test_compact_trims_conversation(self, deps):
        from io import StringIO

        from rich.console import Console

        console = Console(file=StringIO())
        conversation = [{"role": "user", "content": f"msg {i}"} for i in range(20)]

        result = execute(
            "/compact",
            console=console,
            renderer=deps["renderer"],
            conversation=conversation,
            model=deps["model"],
        )

        assert result.handled
        assert len(conversation) == 6
        output = console.file.getvalue()
        assert "压缩" in output

    def test_compact_no_op_on_short_conversation(self, deps):
        from io import StringIO

        from rich.console import Console

        console = Console(file=StringIO())
        conversation = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        result = execute(
            "/compact",
            console=console,
            renderer=deps["renderer"],
            conversation=conversation,
            model=deps["model"],
        )

        assert result.handled
        assert len(conversation) == 2
