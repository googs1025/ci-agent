"""Slash command parser and handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from ci_optimizer.tui.renderer import StreamRenderer


@dataclass
class CommandResult:
    """Result of executing a slash command."""

    handled: bool = True
    clear_history: bool = False
    quit: bool = False


def is_command(text: str) -> bool:
    """Check if the input is a slash command."""
    return text.startswith("/")


def execute(
    text: str,
    *,
    console: Console,
    renderer: "StreamRenderer",
    conversation: list,
    model: str,
) -> CommandResult:
    """Parse and execute a slash command. Returns a CommandResult."""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        return _cmd_help(console)
    if cmd == "/clear":
        return _cmd_clear(console, conversation)
    if cmd == "/cost":
        return _cmd_cost(console, renderer)
    if cmd == "/model":
        return _cmd_model(console, arg, model)
    if cmd == "/skills":
        return _cmd_skills(console)
    if cmd == "/repo":
        return _cmd_repo(console, arg)
    if cmd == "/compact":
        return _cmd_compact(console, conversation)
    if cmd == "/quit" or cmd == "/exit":
        return CommandResult(quit=True)

    console.print(f"[red]未知命令: {cmd}[/red]  输入 /help 查看所有命令")
    return CommandResult()


def _cmd_help(console: Console) -> CommandResult:
    table = Table(title="可用命令", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="bold")
    table.add_column("说明")
    table.add_row("/help", "显示所有命令")
    table.add_row("/repo [path]", "切换工作仓库")
    table.add_row("/skills", "列出分析技能")
    table.add_row("/clear", "清空对话历史")
    table.add_row("/compact", "压缩对话历史（保留最近 6 条消息）")
    table.add_row("/cost", "显示会话 Token 用量和花费")
    table.add_row("/model [name]", "切换模型")
    table.add_row("/quit", "退出 ci-agent")
    table.add_row("Ctrl+C", "清空当前输入")
    table.add_row("Ctrl+D", "退出")
    console.print(table)
    return CommandResult()


def _cmd_clear(console: Console, conversation: list) -> CommandResult:
    conversation.clear()
    console.print("[dim]对话历史已清空[/dim]")
    return CommandResult(clear_history=True)


def _cmd_cost(console: Console, renderer: "StreamRenderer") -> CommandResult:
    renderer.print_stats()
    return CommandResult()


def _cmd_model(console: Console, arg: str, current: str) -> CommandResult:
    if not arg:
        console.print(f"当前模型: [bold]{current}[/bold]")
    else:
        console.print(f"模型已切换为: [bold]{arg}[/bold]")
        # The caller is responsible for actually updating the model in config.
    return CommandResult()


def _cmd_skills(console: Console) -> CommandResult:
    from ci_optimizer.agents.skill_registry import SkillRegistry

    registry = SkillRegistry().load()
    skills = registry.get_active_skills()
    if not skills:
        console.print("[dim]没有发现可用技能[/dim]")
        return CommandResult()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("维度", style="bold")
    table.add_column("名称")
    table.add_column("来源")
    for s in skills:
        table.add_row(s.dimension, s.name, s.source)
    console.print(table)
    return CommandResult()


def _cmd_repo(console: Console, arg: str) -> CommandResult:
    if not arg:
        console.print("[dim]用法: /repo <path>  切换到指定仓库[/dim]")
        return CommandResult()

    from pathlib import Path

    from ci_optimizer.tui.context import detect_repo

    ctx = detect_repo(Path(arg))
    if ctx:
        console.print(f"[green]已切换到仓库: {ctx.display_name}[/green]")
        console.print(f"  分支: {ctx.branch}  路径: {ctx.local_path}")
    else:
        console.print(f"[red]未检测到 Git 仓库: {arg}[/red]")
    return CommandResult()


def _cmd_compact(console: Console, conversation: list) -> CommandResult:
    """Keep only the most recent 6 messages to free context window."""
    KEEP = 6
    total = len(conversation)
    if total <= KEEP:
        console.print(f"[dim]对话历史较短（{total} 条），无需压缩[/dim]")
        return CommandResult()
    dropped = total - KEEP
    del conversation[:-KEEP]
    console.print(f"[dim]已压缩：保留最近 {KEEP} 条消息，丢弃 {dropped} 条[/dim]")
    return CommandResult()
