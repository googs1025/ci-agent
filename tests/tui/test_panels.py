"""Tests for tui.panels — confirmation panel input parsing."""

from unittest.mock import AsyncMock, MagicMock, patch

from ci_optimizer.tui.panels import (
    ConfirmChoice,
    FileChange,
    WriteAction,
    confirm_action,
)


class TestConfirmChoice:
    def test_enum_values(self):
        assert ConfirmChoice.YES.value == "y"
        assert ConfirmChoice.NO.value == "n"
        assert ConfirmChoice.DIFF.value == "d"
        assert ConfirmChoice.EDIT_ONLY.value == "e"


class TestWriteAction:
    def test_defaults(self):
        action = WriteAction()
        assert action.files == []
        assert action.commit_message is None
        assert action.create_pr is False


class TestConfirmAction:
    def _make_action(self) -> WriteAction:
        return WriteAction(
            files=[FileChange(path=".github/workflows/ci.yml", added=3, removed=3, diff="--- a\n+++ b")],
            commit_message="fix: pin action SHAs",
            branch="fix/pin-shas",
            create_pr=True,
        )

    @patch("prompt_toolkit.PromptSession")
    async def test_yes(self, mock_session_cls):
        mock_session_cls.return_value.prompt_async = AsyncMock(return_value="y")
        result = await confirm_action(self._make_action(), console=MagicMock())
        assert result == ConfirmChoice.YES

    @patch("prompt_toolkit.PromptSession")
    async def test_no(self, mock_session_cls):
        mock_session_cls.return_value.prompt_async = AsyncMock(return_value="n")
        result = await confirm_action(self._make_action(), console=MagicMock())
        assert result == ConfirmChoice.NO

    @patch("prompt_toolkit.PromptSession")
    async def test_edit_only(self, mock_session_cls):
        mock_session_cls.return_value.prompt_async = AsyncMock(return_value="e")
        result = await confirm_action(self._make_action(), console=MagicMock())
        assert result == ConfirmChoice.EDIT_ONLY

    @patch("prompt_toolkit.PromptSession")
    async def test_diff_then_yes(self, mock_session_cls):
        """Pressing 'd' shows diff, then re-prompts — second 'y' confirms."""
        mock_session_cls.return_value.prompt_async = AsyncMock(side_effect=["d", "y"])
        result = await confirm_action(self._make_action(), console=MagicMock())
        assert result == ConfirmChoice.YES
        assert mock_session_cls.return_value.prompt_async.call_count == 2

    @patch("prompt_toolkit.PromptSession")
    async def test_invalid_then_no(self, mock_session_cls):
        """Invalid input loops and re-prompts; 'n' then exits cleanly."""
        mock_session_cls.return_value.prompt_async = AsyncMock(side_effect=["anything-else", "n"])
        result = await confirm_action(self._make_action(), console=MagicMock())
        assert result == ConfirmChoice.NO
        assert mock_session_cls.return_value.prompt_async.call_count == 2
