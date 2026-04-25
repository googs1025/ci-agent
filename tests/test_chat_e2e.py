"""E2E tests for /api/chat SSE endpoint.

Tests the full HTTP flow: FastAPI → SSE streaming → agentic tool loop → events.
LLM is mocked at the SDK level; everything else (routing, auth, tools) is real.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from ci_optimizer.api.app import app


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse SSE text into a list of (event_type, data) tuples."""
    events = []
    event_type = None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: ") and event_type:
            events.append((event_type, json.loads(line[6:])))
            event_type = None
    return events


def _make_text_response(text: str, model: str = "test-model"):
    """Create a mock Anthropic response with a text block."""
    block = MagicMock()
    block.type = "text"
    block.text = text

    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    resp.model = model
    return resp


def _make_tool_response(tool_name: str, tool_input: dict, model: str = "test-model"):
    """Create a mock Anthropic response with a tool_use block."""
    block = MagicMock()
    block.type = "tool_use"
    block.id = f"call_{tool_name}"
    block.name = tool_name
    block.input = tool_input

    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    resp.model = model
    return resp


@pytest.fixture
def repo_with_workflow(tmp_path):
    """Create a minimal repo with a workflow file."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest")
    return tmp_path


class TestChatE2E:
    """End-to-end tests for /api/chat SSE endpoint."""

    @patch("ci_optimizer.api.chat._query_anthropic")
    async def test_simple_text_response(self, mock_query):
        """A simple text-only response returns text + done SSE events."""

        async def _fake_stream(*args, **kwargs):
            yield 'event: text\ndata: {"content": "Hello!"}\n\n'
            yield 'event: done\ndata: {"usage": {"input_tokens": 10, "output_tokens": 5}, "model": "test", "turns": 1}\n\n'

        mock_query.return_value = _fake_stream()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={
                    "messages": [{"role": "user", "content": "hi"}],
                    "repo": "test/repo",
                },
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        events = _parse_sse(resp.text)
        event_types = [e[0] for e in events]
        assert "text" in event_types
        assert "done" in event_types

    @patch("ci_optimizer.api.chat.AgentConfig")
    async def test_anthropic_tool_use_flow(self, mock_config_cls, repo_with_workflow):
        """Anthropic provider: tool calling works end-to-end via SSE."""
        config = MagicMock()
        config.provider = "anthropic"
        config.model = "test-model"
        config.anthropic_api_key = "test-key"
        config.anthropic_base_url = None
        config.max_turns = 10
        config.get_sdk_env.return_value = {}
        mock_config_cls.load.return_value = config

        first_resp = _make_tool_response("list_workflows", {})
        second_resp = _make_text_response("Found 1 workflow: ci.yml")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[first_resp, second_resp])

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={
                        "messages": [{"role": "user", "content": "list workflows"}],
                        "repo": "test/repo",
                        "repo_root": str(repo_with_workflow),
                    },
                )

        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        event_types = [e[0] for e in events]

        assert "tool_use" in event_types, f"Expected tool_use, got: {event_types}"
        assert "tool_result" in event_types, f"Expected tool_result, got: {event_types}"
        assert "done" in event_types

        # Verify tool_result contains workflow file info
        tool_results = [e[1] for e in events if e[0] == "tool_result"]
        assert any("ci.yml" in r.get("result_preview", "") for r in tool_results)

    @patch("ci_optimizer.api.chat.AgentConfig")
    async def test_openai_tool_use_flow(self, mock_config_cls, repo_with_workflow):
        """OpenAI provider: tool calling works end-to-end via SSE."""
        config = MagicMock()
        config.provider = "openai"
        config.model = "gpt-test"
        config.openai_api_key = "test-key"
        config.base_url = "http://fake"
        config.max_turns = 10
        mock_config_cls.load.return_value = config

        # First response: tool call
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "list_workflows"
        tool_call.function.arguments = "{}"

        first_msg = MagicMock()
        first_msg.content = None
        first_msg.tool_calls = [tool_call]
        first_msg.model_dump.return_value = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "list_workflows",
                        "arguments": "{}",
                    },
                }
            ],
        }

        first_choice = MagicMock()
        first_choice.message = first_msg
        first_choice.finish_reason = "tool_calls"

        first_resp = MagicMock()
        first_resp.choices = [first_choice]
        first_resp.usage = MagicMock(total_tokens=100)

        # Second response: text
        second_msg = MagicMock()
        second_msg.content = "Found 1 workflow."
        second_msg.tool_calls = None

        second_choice = MagicMock()
        second_choice.message = second_msg
        second_choice.finish_reason = "stop"

        second_resp = MagicMock()
        second_resp.choices = [second_choice]
        second_resp.usage = MagicMock(total_tokens=150)

        with patch("openai.AsyncOpenAI") as mock_openai_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=[first_resp, second_resp])
            mock_openai_cls.return_value = mock_client

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/chat",
                    json={
                        "messages": [{"role": "user", "content": "list workflows"}],
                        "repo": "test/repo",
                        "repo_root": str(repo_with_workflow),
                    },
                )

        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        event_types = [e[0] for e in events]

        assert "tool_use" in event_types, f"Expected tool_use, got: {event_types}"
        assert "tool_result" in event_types, f"Expected tool_result, got: {event_types}"
        assert "done" in event_types

    @patch("ci_optimizer.api.chat._query_anthropic")
    async def test_error_returns_error_event(self, mock_query):
        """When the LLM call fails, an error SSE event is returned."""

        async def _fail(*args, **kwargs):
            raise RuntimeError("LLM unavailable")
            yield  # noqa: unreachable — makes this an async generator

        mock_query.side_effect = _fail

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 200  # SSE always returns 200, errors in stream
        events = _parse_sse(resp.text)
        error_events = [e for e in events if e[0] == "error"]
        assert len(error_events) >= 1
        assert "LLM unavailable" in error_events[0][1].get("message", "")
