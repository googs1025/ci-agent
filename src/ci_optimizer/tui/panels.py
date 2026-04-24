"""Write-confirmation panel and diff viewer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax


class ConfirmChoice(Enum):
    YES = "y"
    NO = "n"
    DIFF = "d"
    EDIT_ONLY = "e"


@dataclass
class FileChange:
    """A single file modification."""

    path: str
    added: int = 0
    removed: int = 0
    diff: str = ""


@dataclass
class WriteAction:
    """An action that modifies the repo and needs confirmation."""

    files: list[FileChange] = field(default_factory=list)
    commit_message: str | None = None
    branch: str | None = None
    create_pr: bool = False


async def confirm_action(action: WriteAction, console: Console | None = None) -> ConfirmChoice:
    """Show a red-bordered confirmation panel for a write action.

    Returns the user's choice. If the user picks 'd' (diff), the diff is
    shown inline and the prompt re-appears.
    """
    from prompt_toolkit import PromptSession

    console = console or Console()
    session = PromptSession()

    while True:
        lines: list[str] = []

        if action.files:
            lines.append("[bold]📝 修改文件[/bold]")
            for f in action.files:
                lines.append(f"   {f.path}  (+{f.added} 行, -{f.removed} 行)")

        if action.commit_message:
            lines.append("[bold]📦 Git commit[/bold]")
            lines.append(f"   {action.commit_message}")

        if action.create_pr and action.branch:
            lines.append("[bold]🔀 Pull Request → main[/bold]")
            lines.append(f"   {action.branch}")

        body = "\n".join(lines)

        console.print()
        console.print(
            Panel(
                body,
                title="⚠  即将执行以下操作",
                border_style="red",
            )
        )
        console.print("[bold][y][/bold] 确认执行   [bold][n][/bold] 取消   [bold][d][/bold] 查看 diff   [bold][e][/bold] 只修改不提 PR")

        answer = (await session.prompt_async("请输入 y/n/d/e > ")).strip().lower()

        if answer in ("d", "diff", "查看", "查看diff", "查看 diff"):
            _show_diffs(action, console)
            continue
        if answer in ("y", "yes", "确认", "确认执行"):
            return ConfirmChoice.YES
        if answer in ("e", "edit", "只修改"):
            return ConfirmChoice.EDIT_ONLY
        if answer in ("n", "no", "取消"):
            return ConfirmChoice.NO
        # 无效输入 → 提示重新选择
        console.print(f"[yellow]无效输入 '{answer}'，请输入 y/n/d/e[/yellow]")


def _show_diffs(action: WriteAction, console: Console) -> None:
    """Display unified diffs for all changed files."""
    for f in action.files:
        if f.diff:
            console.print()
            console.print(f"[bold]{f.path}[/bold]")
            console.print(Syntax(f.diff, "diff", theme="monokai"))
        else:
            console.print(f"[dim]  {f.path}: no diff available[/dim]")
