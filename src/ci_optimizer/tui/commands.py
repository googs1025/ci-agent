"""Slash command parser and handlers."""
# 架构角色：斜杠命令的统一解析与分发层，与业务逻辑完全解耦。
# 核心职责：识别 / 开头的用户输入，路由到对应处理函数，返回 CommandResult 告知调用方后续动作。
# 与其他模块的关系：
#   - app.py 在 REPL 循环中调用 is_command() + execute()，根据 CommandResult.quit 决定是否退出
#   - renderer.py 的 StreamRenderer 作为参数传入，用于 /cost 命令展示统计

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from ci_optimizer.tui.renderer import StreamRenderer


@dataclass
class CommandResult:
    """斜杠命令执行结果，供 app.py 的 REPL 循环读取后续动作标志。
    quit=True 时 REPL 立即退出；clear_history=True 时 app.py 可选择清理 UI 状态。
    """

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
    """解析并执行斜杠命令，返回 CommandResult。
    app.py 已保证只在 is_command() 为 True 时调用此函数，无需重复校验。
    """
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
        # 注：实际写入 config.model 的逻辑在 app.py 的 REPL 中，此处只打印提示。
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
    """保留最近 KEEP 条消息，丢弃更早的历史，释放上下文窗口占用。
    直接对 conversation 列表原地截断，避免创建新列表引用失效。
    """
    KEEP = 6
    total = len(conversation)
    if total <= KEEP:
        console.print(f"[dim]对话历史较短（{total} 条），无需压缩[/dim]")
        return CommandResult()
    dropped = total - KEEP
    del conversation[:-KEEP]
    console.print(f"[dim]已压缩：保留最近 {KEEP} 条消息，丢弃 {dropped} 条[/dim]")
    return CommandResult()
