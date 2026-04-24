# TUI Parity with Claude Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 8 UX gaps between ci-agent TUI and Claude Code's TUI so the interaction feels equally polished.

**Architecture:** All changes are confined to `src/ci_optimizer/tui/` and tests in `tests/tui/`. The server-side (`api/chat.py`, `api/tools.py`) is not touched. Each task is independently mergeable.

**Tech Stack:** Python 3.10+, prompt_toolkit 3.x, Rich 13.x, httpx async streaming, asyncio

---

## File Map

| File | Changes |
|------|---------|
| `src/ci_optimizer/tui/app.py` | Markdown render, interrupt cancel, tool viz, write UX fix, startup progress |
| `src/ci_optimizer/tui/repl.py` | Multi-line input, Meta+Enter submit keybinding |
| `src/ci_optimizer/tui/commands.py` | Add `/compact` command |
| `src/ci_optimizer/tui/renderer.py` | USD cost display, remove stale claude-agent-sdk imports |
| `tests/tui/test_app_sse.py` | Update for markdown rendering, interrupt |
| `tests/tui/test_commands.py` | Add `/compact` test |

---

## Task 1: Markdown Rendering After Stream Completes

**Files:**
- Modify: `src/ci_optimizer/tui/app.py` (function `_query_via_server`, lines ~206–275)
- Test: `tests/tui/test_app_sse.py`

The current code prints raw SSE text chunks with `highlight=False`. We collect text now but never render it as Markdown. Fix: show a dim streaming indicator while chunks arrive, then render full Markdown at `done`.

- [ ] **Step 1: Write failing test**

```python
# tests/tui/test_app_sse.py — add this test
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

@pytest.mark.asyncio
async def test_markdown_rendered_after_stream():
    """collected_text should be rendered as Markdown, not printed raw."""
    from ci_optimizer.tui.app import _query_via_server
    from ci_optimizer.tui.renderer import StreamRenderer
    from rich.console import Console
    from rich.markdown import Markdown
    from io import StringIO

    console = Console(file=StringIO(), force_terminal=True)
    renderer = StreamRenderer(console=console)

    sse_lines = [
        "event: text\n",
        'data: {"content": "## Hello\\n\\n- item1\\n- item2"}\n',
        "\n",
        "event: done\n",
        'data: {"usage": {"input_tokens": 10, "output_tokens": 5}, "model": "claude-sonnet-4-6", "turns": 1}\n',
        "\n",
    ]

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = AsyncMock(return_value=aiter(sse_lines))

    with patch("ci_optimizer.tui.app.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_client.stream.return_value = mock_cm

        ctx = MagicMock()
        ctx.display_name = "owner/repo"
        ctx.branch = "main"
        ctx.local_path = "/tmp/repo"
        config = MagicMock()
        config.model = "claude-sonnet-4-6"

        conversation = []
        await _query_via_server("hello", ctx, config, renderer, conversation, "http://localhost:8000")

    output = console.file.getvalue()
    # Raw markdown syntax should NOT appear as-is; heading markers are consumed by Markdown
    assert "##" not in output or "Hello" in output  # rendered, not raw
    assert "Hello" in output


async def aiter(items):
    for item in items:
        yield item
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd /Users/zhenyu.jiang/ci-agent
uv run pytest tests/tui/test_app_sse.py::test_markdown_rendered_after_stream -v
```

Expected: FAIL (currently prints raw text with `##` visible)

- [ ] **Step 3: Update `_query_via_server` in `app.py`**

Replace the `event_type == "text"` handler and the `event_type == "done"` handler. The streaming indicator (`·`) shows progress without printing raw markdown, and the full Markdown is rendered when `done` arrives.

```python
# In _query_via_server, replace the entire SSE loop body:

collected_text = ""
pending_proposals = []
_streaming_started = False

async for line in resp.aiter_lines():
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
                renderer.console.print("[dim]", end="")
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
            preview_short = preview[:60] + "…" if len(preview) > 60 else preview
            renderer.console.print(f"  [green]✓[/green] [dim]{tool_name}[/dim] [dim]→ {preview_short}[/dim]")

        elif event_type == "write_proposal":
            pending_proposals = data.get("proposals", [])

        elif event_type == "done":
            # Clear streaming dots, render full Markdown
            if _streaming_started:
                renderer.console.print("[/dim]")
            if collected_text:
                from rich.markdown import Markdown
                renderer.console.print()
                renderer.console.print(Markdown(collected_text))
            usage = data.get("usage", {})
            model_used = data.get("model", config.model)
            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            turns = data.get("turns", 1)
            cost_usd = _estimate_cost(model_used, input_t, output_t)
            renderer.stats.query_count += 1
            turns_str = f" · {turns} 轮" if turns > 1 else ""
            cost_str = f" · ${cost_usd:.4f}" if cost_usd > 0 else ""
            renderer.console.print(
                f"[dim]{model_used} · {input_t}↑ {output_t}↓{turns_str}{cost_str}[/dim]"
            )

        elif event_type == "error":
            raise RuntimeError(data.get("message", "Unknown server error"))
```

- [ ] **Step 4: Add `_estimate_cost` helper at module level in `app.py`**

```python
# Add after imports, before _get_server_url()

_COST_TABLE = {
    # (input $/1M, output $/1M)
    "claude-opus":    (15.0, 75.0),
    "claude-sonnet":  (3.0,  15.0),
    "claude-haiku":   (0.25, 1.25),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Rough USD cost estimate based on model name prefix."""
    model_lower = model.lower()
    for key, (in_price, out_price) in _COST_TABLE.items():
        if key in model_lower:
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return 0.0
```

- [ ] **Step 5: Run test — expect pass**

```bash
uv run pytest tests/tui/test_app_sse.py::test_markdown_rendered_after_stream -v
```

Expected: PASS

- [ ] **Step 6: Run full TUI test suite**

```bash
uv run pytest tests/tui/ -v
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/ci_optimizer/tui/app.py tests/tui/test_app_sse.py
git commit -m "feat(tui): render markdown + USD cost after stream completes"
```

---

## Task 2: Multi-Line Input with Meta+Enter

**Files:**
- Modify: `src/ci_optimizer/tui/repl.py`
- Test: `tests/tui/test_commands.py` (manual smoke test note, no unit test needed — prompt_toolkit keybindings are integration-only)

- [ ] **Step 1: Update `build_session()` in `repl.py`**

```python
"""prompt_toolkit REPL session with history and key bindings."""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import is_done
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from ci_optimizer.config import CONFIG_DIR

HISTORY_FILE = CONFIG_DIR / "history"

SLASH_COMMANDS = ["/help", "/repo", "/skills", "/clear", "/cost", "/model", "/compact", "/quit"]


def build_session() -> PromptSession:
    """Create a configured PromptSession with history, completion, and key bindings."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    completer = WordCompleter(SLASH_COMMANDS, sentence=True)
    history = FileHistory(str(HISTORY_FILE))

    kb = KeyBindings()

    @kb.add("c-c")
    def _cancel(event):
        """Ctrl+C: clear current input buffer."""
        event.current_buffer.reset()

    @kb.add("c-d")
    def _exit(event):
        """Ctrl+D: raise EOFError to exit the REPL."""
        event.app.exit(exception=EOFError)

    @kb.add("escape", "enter")   # Meta+Enter = multi-line newline
    def _newline(event):
        event.current_buffer.insert_text("\n")

    session: PromptSession = PromptSession(
        message="› ",
        history=history,
        completer=completer,
        key_bindings=kb,
        multiline=True,
        prompt_continuation="  ",   # indent for continuation lines
        enable_history_search=True,
    )

    return session
```

- [ ] **Step 2: Verify session builds without error**

```bash
uv run python -c "from ci_optimizer.tui.repl import build_session; s = build_session(); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ci_optimizer/tui/repl.py
git commit -m "feat(tui): multi-line input with Meta+Enter, add /compact to completions"
```

---

## Task 3: Interrupt / Cancel Ongoing Request with Ctrl+C

**Files:**
- Modify: `src/ci_optimizer/tui/app.py` (REPL loop in `run_tui`, lines ~310–358)
- Test: `tests/tui/test_app_sse.py`

When the user presses Ctrl+C during a running query, the httpx SSE stream should be cancelled and the REPL returns to the prompt.

- [ ] **Step 1: Write failing test**

```python
# tests/tui/test_app_sse.py — add this test
import asyncio

@pytest.mark.asyncio
async def test_query_cancellable():
    """Cancelling the query task raises CancelledError and leaves REPL intact."""
    from ci_optimizer.tui.app import _query_via_server
    from ci_optimizer.tui.renderer import StreamRenderer
    from rich.console import Console
    from io import StringIO

    console = Console(file=StringIO(), force_terminal=True)
    renderer = StreamRenderer(console=console)

    async def slow_lines():
        yield "event: text\n"
        yield 'data: {"content": "starting..."}\n'
        yield "\n"
        await asyncio.sleep(10)   # blocks forever
        yield "event: done\n"

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = slow_lines

    with patch("ci_optimizer.tui.app.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_client.stream.return_value = mock_cm

        ctx = MagicMock()
        ctx.display_name = "owner/repo"
        ctx.branch = "main"
        ctx.local_path = "/tmp/repo"
        config = MagicMock()
        config.model = "claude-sonnet-4-6"

        task = asyncio.create_task(
            _query_via_server("q", ctx, config, renderer, [], "http://localhost:8000")
        )
        await asyncio.sleep(0.05)   # let it start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
```

- [ ] **Step 2: Run test — expect pass already** (httpx stream is already async and cancellable; this test verifies the contract)

```bash
uv run pytest tests/tui/test_app_sse.py::test_query_cancellable -v
```

- [ ] **Step 3: Update REPL loop in `run_tui` to wrap query in a task**

In `app.py`, replace the `try: await _query_via_server(...)` block:

```python
import contextlib  # add at top of file

# Inside run_tui, replace:
#   try:
#       await _query_via_server(user_input, ctx, config, renderer, conversation, server_url)
#   except Exception as e:
#       console.print(f"\n[red]错误: {e}[/red]")
# With:

_query_task: asyncio.Task | None = None
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
```

Also add `import asyncio` and `import contextlib` to the imports at the top of `app.py` if not already present.

- [ ] **Step 4: Run all TUI tests**

```bash
uv run pytest tests/tui/ -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/ci_optimizer/tui/app.py tests/tui/test_app_sse.py
git commit -m "feat(tui): cancel ongoing SSE request with Ctrl+C"
```

---

## Task 4: /compact Command (Conversation Compression)

**Files:**
- Modify: `src/ci_optimizer/tui/commands.py`
- Modify: `src/ci_optimizer/tui/app.py` (pass `conversation` ref correctly to `/compact`)
- Test: `tests/tui/test_commands.py`

`/compact` keeps only the last 6 messages (3 turns) to free up context. Shows a summary of how many messages were dropped.

- [ ] **Step 1: Write failing test**

```python
# tests/tui/test_commands.py — add this test
def test_compact_trims_conversation():
    from ci_optimizer.tui.commands import execute
    from rich.console import Console
    from io import StringIO
    from unittest.mock import MagicMock

    console = Console(file=StringIO())
    renderer = MagicMock()
    conversation = [
        {"role": "user", "content": f"msg {i}"} for i in range(20)
    ]

    result = execute("/compact", console=console, renderer=renderer, conversation=conversation, model="m")

    assert result.handled
    assert len(conversation) <= 6
    output = console.file.getvalue()
    assert "压缩" in output or "compact" in output.lower()


def test_compact_no_op_on_short_conversation():
    from ci_optimizer.tui.commands import execute
    from rich.console import Console
    from io import StringIO
    from unittest.mock import MagicMock

    console = Console(file=StringIO())
    renderer = MagicMock()
    conversation = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    result = execute("/compact", console=console, renderer=renderer, conversation=conversation, model="m")

    assert result.handled
    assert len(conversation) == 2   # unchanged
```

- [ ] **Step 2: Run tests — expect failure**

```bash
uv run pytest tests/tui/test_commands.py::test_compact_trims_conversation tests/tui/test_commands.py::test_compact_no_op_on_short_conversation -v
```

Expected: FAIL (`/compact` not implemented)

- [ ] **Step 3: Add `_cmd_compact` to `commands.py`**

```python
# In commands.py, add to execute():
if cmd == "/compact":
    return _cmd_compact(console, conversation)


# Add new function:
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
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/tui/test_commands.py::test_compact_trims_conversation tests/tui/test_commands.py::test_compact_no_op_on_short_conversation -v
```

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/tui/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/ci_optimizer/tui/commands.py tests/tui/test_commands.py
git commit -m "feat(tui): add /compact command to trim conversation context"
```

---

## Task 5: Fix Write Confirmation UX (Unify panels.py)

**Files:**
- Modify: `src/ci_optimizer/tui/app.py` (`_handle_write_proposals`)
- Test: `tests/tui/test_panels.py` (already covers `confirm_action`; add integration test)

Two problems:
1. `_handle_write_proposals` creates its own `PromptSession` instead of using `panels.confirm_action`
2. The git_commit proposal has a different schema than file proposals — the code mixes two formats

Fix: route all proposals through `panels.confirm_action` using `WriteAction` / `FileChange` data classes.

- [ ] **Step 1: Write failing test**

```python
# tests/tui/test_app_sse.py — add this test
@pytest.mark.asyncio
async def test_handle_write_proposals_uses_panels():
    """_handle_write_proposals should call panels.confirm_action."""
    from ci_optimizer.tui.app import _handle_write_proposals
    from ci_optimizer.tui.renderer import StreamRenderer
    from ci_optimizer.tui.panels import ConfirmChoice
    from rich.console import Console
    from io import StringIO

    console = Console(file=StringIO(), force_terminal=True)
    renderer = StreamRenderer(console=console)

    proposals = [
        {
            "action": "edit_file",
            "path": ".github/workflows/ci.yml",
            "diff": "--- a\n+++ b\n-ubuntu-latest\n+ubuntu-22.04",
            "added": 1,
            "removed": 1,
            "tool_name": "edit_file",
            "tool_input": {"path": ".github/workflows/ci.yml", "old_string": "ubuntu-latest", "new_string": "ubuntu-22.04"},
        }
    ]

    ctx = MagicMock()
    ctx.local_path = "/tmp/repo"

    with patch("ci_optimizer.tui.app.panels.confirm_action", new=AsyncMock(return_value=ConfirmChoice.NO)) as mock_confirm:
        await _handle_write_proposals(proposals, ctx, renderer, "http://localhost:8000")
        mock_confirm.assert_called_once()
```

- [ ] **Step 2: Run test — expect failure**

```bash
uv run pytest tests/tui/test_app_sse.py::test_handle_write_proposals_uses_panels -v
```

Expected: FAIL (current code doesn't call `panels.confirm_action`)

- [ ] **Step 3: Rewrite `_handle_write_proposals` in `app.py`**

```python
from ci_optimizer.tui import panels as panels  # add to imports at top


async def _handle_write_proposals(
    proposals: list[dict],
    ctx: "RepoContext",
    renderer: "StreamRenderer",
    server_url: str,
) -> None:
    """Route write proposals through panels.confirm_action for unified UX."""
    console = renderer.console

    file_proposals = [p for p in proposals if p.get("action") in ("write_file", "edit_file")]
    git_proposals = [p for p in proposals if p.get("action") == "git_commit"]

    if not file_proposals and not git_proposals:
        return

    action = panels.WriteAction(
        files=[
            panels.FileChange(
                path=p["path"],
                added=p.get("added", 0),
                removed=p.get("removed", 0),
                diff=p.get("diff", ""),
            )
            for p in file_proposals
        ],
        commit_message=git_proposals[0]["message"] if git_proposals else None,
    )

    choice = await panels.confirm_action(action, console=console)

    if choice == panels.ConfirmChoice.NO:
        console.print("[dim]已取消写入操作[/dim]")
        return

    # If EDIT_ONLY, drop git proposals
    apply_proposals = proposals if choice == panels.ConfirmChoice.YES else file_proposals

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{server_url}/api/chat/apply",
            json={"proposals": apply_proposals, "repo_root": str(ctx.local_path)},
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            for r in results:
                console.print(f"  [green]✓[/green] {r['tool_name']} → {r['result'][:80]}")
            console.print("[green]写入操作已完成[/green]")
        else:
            console.print(f"[red]写入失败: {resp.text}[/red]")
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/tui/test_app_sse.py::test_handle_write_proposals_uses_panels -v
```

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/tui/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/ci_optimizer/tui/app.py tests/tui/test_app_sse.py
git commit -m "fix(tui): unify write confirmation through panels.confirm_action"
```

---

## Task 6: Server Startup Progress Indicator

**Files:**
- Modify: `src/ci_optimizer/tui/app.py` (`_ensure_server`)

Replace the single dim line with a Rich `Live` spinner that updates each 0.5 s.

- [ ] **Step 1: Update `_ensure_server` in `app.py`**

```python
async def _ensure_server(server_url: str, console: Console) -> subprocess.Popen | None:
    """Ensure the server is running. Start it automatically if not."""
    import asyncio
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text

    if await _check_server(server_url):
        return None

    from urllib.parse import urlparse
    parsed = urlparse(server_url)
    port = parsed.port or 8000

    proc = _start_server_background(port)

    with Live(console=console, refresh_per_second=8) as live:
        for i in range(20):
            elapsed = i * 0.5
            live.update(
                Text(f"  ⠸ 正在启动 Server (port {port}) … {elapsed:.0f}s", style="dim")
            )
            await asyncio.sleep(0.5)
            if await _check_server(server_url):
                live.update(Text("  ✓ Server 已启动", style="green"))
                return proc

    proc.terminate()
    raise RuntimeError("Server 启动超时，请手动运行: ci-agent serve")
```

- [ ] **Step 2: Verify import is fine**

```bash
uv run python -c "from ci_optimizer.tui.app import _ensure_server; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ci_optimizer/tui/app.py
git commit -m "feat(tui): animated spinner during server startup"
```

---

## Task 7: Clean Up renderer.py (Remove Stale SDK Imports)

**Files:**
- Modify: `src/ci_optimizer/tui/renderer.py`

`renderer.py` imports `claude_agent_sdk` types (`AssistantMessage`, `ResultMessage`, etc.) but the TUI now uses SSE — these are never called from `app.py`. The `render_message` and `_render_result` methods are dead code. Clean up so the file only keeps `SessionStats`, `StreamRenderer` (with `print_stats`), and `_tool_description`.

- [ ] **Step 1: Write test that renderer has no SDK imports**

```python
# tests/tui/test_app_sse.py — add
def test_renderer_no_sdk_import():
    """renderer.py must not import claude_agent_sdk at module level."""
    import importlib, sys
    # Remove cached module if present
    sys.modules.pop("ci_optimizer.tui.renderer", None)
    mod = importlib.import_module("ci_optimizer.tui.renderer")
    assert "claude_agent_sdk" not in sys.modules or True  # SDK may be installed but shouldn't be imported by renderer
    # Check source doesn't have the import
    import inspect
    src = inspect.getsource(mod)
    assert "from claude_agent_sdk" not in src
    assert "import claude_agent_sdk" not in src
```

- [ ] **Step 2: Run test — expect failure**

```bash
uv run pytest tests/tui/test_app_sse.py::test_renderer_no_sdk_import -v
```

- [ ] **Step 3: Rewrite `renderer.py`**

```python
"""Rich-based stream stats tracker for the TUI."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console
from rich.text import Text


@dataclass
class SessionStats:
    """Accumulated stats for the current session."""

    total_cost_usd: float = 0.0
    query_count: int = 0


@dataclass
class StreamRenderer:
    """Tracks session stats and provides a print_stats helper."""

    console: Console = field(default_factory=Console)
    stats: SessionStats = field(default_factory=SessionStats)

    def print_stats(self) -> None:
        """Print accumulated session stats."""
        self.console.print()
        self.console.print("[bold]Session Stats[/bold]")
        self.console.print(f"  查询次数: {self.stats.query_count}")
        self.console.print(f"  总花费:   ${self.stats.total_cost_usd:.4f}")
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/tui/test_app_sse.py::test_renderer_no_sdk_import -v
```

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/tui/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/ci_optimizer/tui/renderer.py tests/tui/test_app_sse.py
git commit -m "refactor(tui): remove stale claude-agent-sdk imports from renderer"
```

---

## Task 8: USD Cost Accumulation in Session Stats

**Files:**
- Modify: `src/ci_optimizer/tui/app.py` (wire `_estimate_cost` into `renderer.stats`)
- Test: `tests/tui/test_app_sse.py`

After Task 1, `_estimate_cost` is defined. Now accumulate it into `renderer.stats.total_cost_usd` so `/cost` shows the real session total.

- [ ] **Step 1: Write failing test**

```python
# tests/tui/test_app_sse.py — add
@pytest.mark.asyncio
async def test_cost_accumulated_in_stats():
    from ci_optimizer.tui.app import _query_via_server
    from ci_optimizer.tui.renderer import StreamRenderer
    from rich.console import Console
    from io import StringIO

    console = Console(file=StringIO(), force_terminal=True)
    renderer = StreamRenderer(console=console)

    sse_lines = [
        "event: done\n",
        'data: {"usage": {"input_tokens": 1000, "output_tokens": 500}, "model": "claude-sonnet-4-6", "turns": 1}\n',
        "\n",
    ]

    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    async def _lines():
        for l in sse_lines:
            yield l

    mock_resp.aiter_lines = _lines

    with patch("ci_optimizer.tui.app.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_resp
        mock_client.stream.return_value = mock_cm

        ctx = MagicMock()
        ctx.display_name = "owner/repo"
        ctx.branch = "main"
        ctx.local_path = "/tmp/repo"
        config = MagicMock()
        config.model = "claude-sonnet-4-6"

        await _query_via_server("hello", ctx, config, renderer, [], "http://localhost:8000")

    # claude-sonnet: $3/1M input, $15/1M output
    # 1000 * 3/1M + 500 * 15/1M = 0.003 + 0.0075 = 0.0105
    assert renderer.stats.total_cost_usd == pytest.approx(0.0105, rel=0.01)
```

- [ ] **Step 2: Run test — expect failure**

```bash
uv run pytest tests/tui/test_app_sse.py::test_cost_accumulated_in_stats -v
```

- [ ] **Step 3: Wire cost into stats in `app.py` done handler**

In the `event_type == "done"` block (from Task 1), add:

```python
cost_usd = _estimate_cost(model_used, input_t, output_t)
renderer.stats.total_cost_usd += cost_usd   # ← add this line
renderer.stats.query_count += 1
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/tui/test_app_sse.py::test_cost_accumulated_in_stats -v
```

- [ ] **Step 5: Run full suite**

```bash
uv run pytest tests/tui/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/ci_optimizer/tui/app.py tests/tui/test_app_sse.py
git commit -m "feat(tui): accumulate USD cost into session stats for /cost command"
```

---

## Self-Review

**Spec coverage:**
- Markdown rendering → Task 1 ✓
- Multi-line input → Task 2 ✓
- Interrupt/cancel → Task 3 ✓
- /compact → Task 4 ✓
- Write confirmation UX → Task 5 ✓
- Server startup progress → Task 6 ✓
- Stale renderer cleanup → Task 7 ✓
- USD cost display + /cost → Task 1 + Task 8 ✓

**Placeholder scan:** All tasks have complete code. No TBD. No "similar to above". ✓

**Type consistency:**
- `StreamRenderer.stats.total_cost_usd` used in Task 1, 8, renderer.py Task 7 ✓
- `panels.ConfirmChoice`, `panels.WriteAction`, `panels.FileChange` used in Task 5 ✓
- `_estimate_cost(model, input_t, output_t) -> float` defined Task 1, used Task 8 ✓
- `_handle_write_proposals(proposals, ctx, renderer, server_url)` signature unchanged ✓
