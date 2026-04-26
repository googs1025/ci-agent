"""Write-confirmation panel and diff viewer."""
# 架构角色：TUI 层的 Rich 渲染组件，专门负责"写入确认"这一交互环节。
# 核心职责：
#   1. 将 SSE write_proposal 数据结构化为 WriteAction / FileChange 数据类
#   2. 用 Rich Panel 渲染变更摘要（红色边框警示用户即将落盘）
#   3. 阻塞式等待用户输入 y/n/d/e，支持循环展示 diff 后再选择
# 与其他模块的关系：
#   - app.py 的 _handle_write_proposals() 构建 WriteAction 并调用 confirm_action()
#   - 返回的 ConfirmChoice 枚举决定 app.py 是否以及以何种方式调用 /api/chat/apply

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax


class ConfirmChoice(Enum):
    """用户在写入确认面板中的选择。
    EDIT_ONLY 表示只写文件、跳过 git commit 和 PR，适合用户想手动控制提交的场景。
    """

    YES = "y"
    NO = "n"
    DIFF = "d"
    EDIT_ONLY = "e"


@dataclass
class FileChange:
    """单个文件的变更描述，由 SSE write_proposal 事件的 proposals 列表中解析而来。"""

    path: str
    added: int = 0
    removed: int = 0
    diff: str = ""


@dataclass
class WriteAction:
    """需要用户二次确认的写入操作集合，可同时包含文件修改和 git commit。"""

    files: list[FileChange] = field(default_factory=list)
    commit_message: str | None = None
    branch: str | None = None
    create_pr: bool = False


async def confirm_action(action: WriteAction, console: Console | None = None) -> ConfirmChoice:
    """显示红色边框确认面板，阻塞等待用户输入并返回选择。
    选择 'd' 时展示 unified diff 后重新提示，不退出循环——这是唯一的循环出口条件。
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
