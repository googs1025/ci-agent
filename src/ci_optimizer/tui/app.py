"""TUI entry point: startup banner, repo confirm, REPL loop."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
from pathlib import Path

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ci_optimizer.config import AgentConfig

from .commands import execute, is_command
from .context import RepoContext, confirm_repo, detect_repo
from .renderer import StreamRenderer
from .repl import build_session

VERSION = "0.2.0"

DEFAULT_SERVER_URL = "http://localhost:8000"

_COST_TABLE = {
    # (input $/1M tokens, output $/1M tokens)
    "claude-opus":   (15.0, 75.0),
    "claude-sonnet": (3.0,  15.0),
    "claude-haiku":  (0.25, 1.25),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Rough USD cost estimate based on model name prefix."""
    model_lower = model.lower()
    for key, (in_price, out_price) in _COST_TABLE.items():
        if key in model_lower:
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return 0.0


def _get_server_url() -> str:
    return os.getenv("CI_AGENT_API_URL", DEFAULT_SERVER_URL).rstrip("/")


def _print_banner(console: Console) -> None:
    console.print(
        Panel(
            Text.from_markup(f"[bold]🤖  CI Agent[/bold]  v{VERSION}"),
            border_style="cyan",
        )
    )


def _print_connected(console: Console, ctx: RepoContext, config: AgentConfig, server_url: str) -> None:
    console.print(f"[green]✓[/green] 已连接 [bold]{ctx.display_name}[/bold]")
    console.print(f"  Model: {config.model} · Server: {server_url}")
    console.print("  输入 /help 查看命令，Ctrl+C 清空输入，Ctrl+D 退出")
    console.print()


async def _check_server(server_url: str) -> bool:
    """Check if the CI Agent server is reachable."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{server_url}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


def _start_server_background(port: int = 8000) -> subprocess.Popen:
    """Start the CI Agent server as a background process."""
    import sys

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ci_optimizer.api.app:app", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


async def _ensure_server(server_url: str, console: Console) -> subprocess.Popen | None:
    """Ensure the server is running. Start it automatically if not."""
    if await _check_server(server_url):
        return None  # already running externally

    # Extract port from URL
    from urllib.parse import urlparse

    parsed = urlparse(server_url)
    port = parsed.port or 8000

    console.print(f"[dim]  正在启动 CI Agent Server (port {port})...[/dim]")
    proc = _start_server_background(port)

    # Wait for server to be ready (up to 10s)
    for _ in range(20):
        await asyncio.sleep(0.5)
        if await _check_server(server_url):
            console.print("[green]  ✓ Server 已启动[/green]")
            return proc

    proc.terminate()
    raise RuntimeError("Server 启动超时，请手动运行: ci-agent serve")


def _tool_status(name: str, inputs: dict) -> str:
    """工具调用的中文状态描述。"""
    if name == "read_file":
        return f"读取 {inputs.get('path', '...')}"
    if name == "glob_files":
        return f"搜索文件 {inputs.get('pattern', '...')}"
    if name == "grep_content":
        return f"搜索内容 {inputs.get('pattern', '...')}"
    if name == "list_workflows":
        return "列出 workflow 文件"
    if name == "run_command":
        cmd = inputs.get("command", "")
        return f"执行 {cmd[:50]}{'...' if len(cmd) > 50 else ''}"
    if name == "write_file":
        return f"写入 {inputs.get('path', '...')}"
    if name == "edit_file":
        return f"编辑 {inputs.get('path', '...')}"
    if name == "git_commit":
        return f"提交 {inputs.get('message', '...')[:40]}"
    return f"{name} ..."


async def _handle_write_proposals(
    proposals: list[dict],
    ctx: RepoContext,
    renderer: StreamRenderer,
    server_url: str,
) -> None:
    """Claude Code 风格：先展示每个文件的 diff，再问确认。"""
    from prompt_toolkit import PromptSession
    from rich.syntax import Syntax

    console = renderer.console
    session = PromptSession()

    file_proposals = [p for p in proposals if p.get("action") in ("write_file", "edit_file")]
    git_proposals = [p for p in proposals if p.get("action") == "git_commit"]

    if not file_proposals and not git_proposals:
        return

    # ── 逐个文件展示 diff ──
    for p in file_proposals:
        path = p.get("path", "?")
        diff = p.get("diff", "")
        added = p.get("added", 0)
        removed = p.get("removed", 0)

        console.print()
        console.print(f"[bold yellow]✎ {path}[/bold yellow]  [dim](+{added}, -{removed})[/dim]")
        if diff:
            console.print(Syntax(diff, "diff", theme="monokai", line_numbers=False))
        else:
            console.print("[dim]  (no diff available)[/dim]")

    if git_proposals:
        for gp in git_proposals:
            console.print(f"\n[bold]📦 Git commit:[/bold] {gp.get('message', '?')}")

    # ── 确认 ──
    console.print()
    console.print("[bold][y][/bold] 应用修改   [bold][n][/bold] 取消   [bold][e][/bold] 只改文件不 commit")

    while True:
        answer = (await session.prompt_async("请输入 y/n/e > ")).strip().lower()
        if answer in ("y", "yes", "确认"):
            break
        if answer in ("n", "no", "取消"):
            console.print("[dim]已取消写入操作[/dim]")
            return
        if answer in ("e", "edit", "只修改"):
            # 去掉 git_commit
            proposals = [p for p in proposals if p.get("action") != "git_commit"]
            break
        console.print("[yellow]请输入 y/n/e[/yellow]")

    # ── 执行 ──
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{server_url}/api/chat/apply",
            json={"proposals": proposals, "repo_root": str(ctx.local_path)},
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for r in results:
                console.print(f"  [green]✓[/green] {r['tool_name']} → {r['result'][:80]}")
            console.print("[green]写入操作已完成[/green]")
        else:
            console.print(f"[red]写入失败: {resp.text}[/red]")


async def _query_via_server(
    user_input: str,
    ctx: RepoContext,
    config: AgentConfig,
    renderer: StreamRenderer,
    conversation: list[dict],
    server_url: str,
) -> None:
    """Send user input to the server's /api/chat SSE endpoint and stream output."""
    conversation.append({"role": "user", "content": user_input})

    payload = {
        "messages": conversation,
        "repo": ctx.display_name,
        "branch": ctx.branch,
        "model": config.model,
        "repo_root": str(ctx.local_path),
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)) as client:
        async with client.stream(
            "POST",
            f"{server_url}/api/chat",
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"Server 返回 {resp.status_code}: {body.decode()}")

            collected_text = ""
            pending_proposals = []
            _streaming_started = False
            event_type = None

            async for line in resp.aiter_lines():
                line = line.rstrip()
                if not line:
                    continue

                if line.startswith("event: "):
                    event_type = line[7:]
                    continue

                if line.startswith("data: ") and event_type:
                    data = json.loads(line[6:])

                    if event_type == "text":
                        text_chunk = data.get("content", "")
                        collected_text += text_chunk
                        if not _streaming_started:
                            renderer.console.print()
                            _streaming_started = True
                        renderer.console.print("·", end="", highlight=False)

                    elif event_type == "tool_use":
                        tool_name = data.get("name", "?")
                        tool_input = data.get("input", {})
                        desc = _tool_status(tool_name, tool_input)
                        renderer.console.print()
                        renderer.console.print(f"  [dim]⠸ {desc}[/dim]")

                    elif event_type == "tool_result":
                        tool_name = data.get("name", "?")
                        preview = data.get("result_preview", "")
                        if preview:
                            preview_short = preview[:60] + "…" if len(preview) > 60 else preview
                            renderer.console.print(f"  [green]✓[/green] [dim]{tool_name} → {preview_short}[/dim]")
                        else:
                            renderer.console.print(f"  [green]✓[/green] [dim]{tool_name}[/dim]")

                    elif event_type == "write_proposal":
                        pending_proposals = data.get("proposals", [])

                    elif event_type == "done":
                        if _streaming_started:
                            renderer.console.print()
                        if collected_text:
                            from rich.markdown import Markdown
                            renderer.console.print(Markdown(collected_text))
                        usage = data.get("usage", {})
                        model_used = data.get("model", config.model)
                        input_t = usage.get("input_tokens", 0)
                        output_t = usage.get("output_tokens", 0)
                        turns = data.get("turns", 1)
                        cost_usd = _estimate_cost(model_used, input_t, output_t)
                        renderer.stats.query_count += 1
                        renderer.stats.total_cost_usd += cost_usd
                        turns_str = f" · {turns} 轮" if turns > 1 else ""
                        cost_str = f" · ${cost_usd:.4f}" if cost_usd > 0 else ""
                        renderer.console.print(
                            f"[dim]{model_used} · {input_t}↑ {output_t}↓{turns_str}{cost_str}[/dim]"
                        )

                    elif event_type == "error":
                        raise RuntimeError(data.get("message", "Unknown server error"))

    # 处理待确认的写入操作
    if pending_proposals:
        await _handle_write_proposals(pending_proposals, ctx, renderer, server_url)

    if collected_text:
        conversation.append({"role": "assistant", "content": collected_text})


async def run_tui(repo_path: Path | None = None) -> None:
    """Main TUI entry point: banner → repo confirm → REPL loop."""
    console = Console()
    renderer = StreamRenderer(console=console)

    _print_banner(console)

    # Detect and confirm repo
    ctx = detect_repo(repo_path)
    try:
        ctx = await confirm_repo(ctx)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]已退出[/dim]")
        return

    config = AgentConfig.load()
    server_url = _get_server_url()

    # Auto-start server if not running
    server_proc = None
    try:
        server_proc = await _ensure_server(server_url, console)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        return

    _print_connected(console, ctx, config, server_url)

    # REPL
    session = build_session()
    conversation: list[dict] = []

    try:
        while True:
            try:
                user_input = await session.prompt_async()
            except KeyboardInterrupt:
                continue
            except EOFError:
                console.print("\n[dim]再见！[/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Handle bare exit/quit without slash
            if user_input.lower() in ("exit", "quit", "q"):
                console.print("[dim]再见！[/dim]")
                break

            # Slash commands
            if is_command(user_input):
                result = execute(
                    user_input,
                    console=console,
                    renderer=renderer,
                    conversation=conversation,
                    model=config.model,
                )
                if result.quit:
                    console.print("[dim]再见！[/dim]")
                    break
                # Handle /model switch
                if user_input.startswith("/model "):
                    new_model = user_input.split(maxsplit=1)[1].strip()
                    if new_model:
                        config.model = new_model
                # Handle /repo switch
                if user_input.startswith("/repo "):
                    new_path = user_input.split(maxsplit=1)[1].strip()
                    new_ctx = detect_repo(Path(new_path))
                    if new_ctx:
                        ctx = new_ctx
                continue

            # Natural language → server /api/chat
            _query_task = None
            try:
                _query_task = asyncio.create_task(
                    _query_via_server(user_input, ctx, config, renderer, conversation, server_url)
                )
                await _query_task
            except KeyboardInterrupt:
                if _query_task and not _query_task.done():
                    _query_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await _query_task
                console.print("\n[dim]已中断[/dim]")
            except asyncio.CancelledError:
                console.print("\n[dim]已中断[/dim]")
            except Exception as e:
                console.print(f"\n[red]错误: {e}[/red]")
    finally:
        # Cleanup: stop server if we started it
        if server_proc:
            console.print("[dim]  正在停止 Server...[/dim]")
            server_proc.terminate()
            server_proc.wait(timeout=5)
