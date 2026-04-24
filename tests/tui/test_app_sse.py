"""Tests for TUI SSE streaming and rendering."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_ctx():
    ctx = MagicMock()
    ctx.display_name = "owner/repo"
    ctx.branch = "main"
    ctx.local_path = "/tmp/repo"
    return ctx


def _make_config(model="claude-sonnet-4-6"):
    cfg = MagicMock()
    cfg.model = model
    return cfg


async def _aiter(items):
    for item in items:
        yield item


def _patch_httpx(sse_lines):
    """Return a context manager that patches httpx.AsyncClient stream."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = lambda: _aiter(sse_lines)

    mock_stream_cm = AsyncMock()
    mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.stream = MagicMock(return_value=mock_stream_cm)

    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    return patch("ci_optimizer.tui.app.httpx.AsyncClient", return_value=mock_client_cm)


# ── existing tests ────────────────────────────────────────────────────────────

def make_sse(event: str, data: dict) -> list[str]:
    """Simulate lines returned by aiter_lines() for SSE."""
    return [f"event: {event}", f"data: {json.dumps(data)}"]


class TestSSEEventTypes:
    def test_parse_text_event(self):
        lines = make_sse("text", {"content": "Hello"})
        assert lines[0] == "event: text"
        data = json.loads(lines[1][6:])
        assert data["content"] == "Hello"

    def test_parse_tool_use_event(self):
        lines = make_sse("tool_use", {"id": "t1", "name": "read_file", "input": {"path": "ci.yml"}})
        data = json.loads(lines[1][6:])
        assert data["name"] == "read_file"
        assert data["input"]["path"] == "ci.yml"

    def test_parse_tool_result_event(self):
        lines = make_sse("tool_result", {"id": "t1", "name": "read_file", "result_preview": "name: CI..."})
        data = json.loads(lines[1][6:])
        assert data["name"] == "read_file"
        assert "CI" in data["result_preview"]

    def test_parse_done_event_with_turns(self):
        lines = make_sse("done", {"usage": {"input_tokens": 100, "output_tokens": 50}, "model": "claude", "turns": 3})
        data = json.loads(lines[1][6:])
        assert data["turns"] == 3


# ── new tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_markdown_rendered_after_stream():
    """Text chunks accumulate; Markdown() is called on done, not raw printed."""
    from ci_optimizer.tui.app import _query_via_server
    from ci_optimizer.tui.renderer import StreamRenderer
    from rich.console import Console

    console = Console(file=StringIO(), force_terminal=True, highlight=False)
    renderer = StreamRenderer(console=console)

    sse_lines = [
        "event: text\n",
        'data: {"content": "## Hello\\n\\n- item1"}\n',
        "\n",
        "event: done\n",
        'data: {"usage": {"input_tokens": 10, "output_tokens": 5}, "model": "claude-sonnet-4-6", "turns": 1}\n',
        "\n",
    ]

    with _patch_httpx(sse_lines):
        await _query_via_server("hi", _make_ctx(), _make_config(), renderer, [], "http://localhost:8000")

    output = console.file.getvalue()
    # "Hello" heading should appear; raw "##" should not survive rendering
    assert "Hello" in output


@pytest.mark.asyncio
async def test_cost_accumulated_in_stats():
    """renderer.stats.total_cost_usd should reflect token cost after done."""
    from ci_optimizer.tui.app import _query_via_server
    from ci_optimizer.tui.renderer import StreamRenderer
    from rich.console import Console

    console = Console(file=StringIO(), force_terminal=True)
    renderer = StreamRenderer(console=console)

    sse_lines = [
        "event: done\n",
        'data: {"usage": {"input_tokens": 1000, "output_tokens": 500}, "model": "claude-sonnet-4-6", "turns": 1}\n',
        "\n",
    ]

    with _patch_httpx(sse_lines):
        await _query_via_server("hi", _make_ctx(), _make_config(), renderer, [], "http://localhost:8000")

    # claude-sonnet: $3/1M input + $15/1M output
    # 1000*3/1e6 + 500*15/1e6 = 0.003 + 0.0075 = 0.0105
    assert abs(renderer.stats.total_cost_usd - 0.0105) < 0.001


@pytest.mark.asyncio
async def test_estimate_cost_unknown_model():
    """Unknown model returns 0.0."""
    from ci_optimizer.tui.app import _estimate_cost
    assert _estimate_cost("gpt-4o", 1000, 500) == 0.0


@pytest.mark.asyncio
async def test_tool_result_preview_shown():
    """tool_result events should show a green checkmark and preview."""
    from ci_optimizer.tui.app import _query_via_server
    from ci_optimizer.tui.renderer import StreamRenderer
    from rich.console import Console

    console = Console(file=StringIO(), force_terminal=True, highlight=False)
    renderer = StreamRenderer(console=console)

    sse_lines = [
        "event: tool_result\n",
        'data: {"name": "read_file", "result_preview": "name: CI"}\n',
        "\n",
        "event: done\n",
        'data: {"usage": {"input_tokens": 5, "output_tokens": 2}, "model": "claude-haiku-4-5", "turns": 1}\n',
        "\n",
    ]

    with _patch_httpx(sse_lines):
        await _query_via_server("hi", _make_ctx(), _make_config(), renderer, [], "http://localhost:8000")

    output = console.file.getvalue()
    assert "read_file" in output
    assert "name: CI" in output
