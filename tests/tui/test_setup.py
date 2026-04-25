"""Tests for TUI setup wizard logic."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_optimizer.tui.setup import mask_key, needs_setup


def test_needs_setup_no_config_file(tmp_path):
    with patch("ci_optimizer.tui.setup.CONFIG_FILE", tmp_path / "config.json"):
        assert needs_setup() is True


def test_needs_setup_config_exists(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"provider": "anthropic"}))
    with patch("ci_optimizer.tui.setup.CONFIG_FILE", config_file):
        assert needs_setup() is False


def test_mask_key_long():
    assert mask_key("sk-ant-api03-abcdefghij1234") == "sk-ant-a...1234"


def test_mask_key_short():
    assert mask_key("short") == "***"


def test_mask_key_none():
    assert mask_key(None) == "(未设置)"


def test_mask_key_empty():
    assert mask_key("") == "(未设置)"


import httpx
from unittest.mock import AsyncMock, MagicMock

from ci_optimizer.tui.setup import verify_api


@pytest.mark.asyncio
async def test_verify_api_anthropic_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "type": "message",
        "content": [{"type": "text", "text": "Hi"}],
        "model": "claude-sonnet-4-20250514",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = mock_response

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="anthropic",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
        )
    assert ok is True
    assert "claude-sonnet" in msg


@pytest.mark.asyncio
async def test_verify_api_anthropic_auth_error():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock(status_code=401, text="invalid api key")
    )

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="anthropic",
            api_key="bad-key",
            model="claude-sonnet-4-20250514",
        )
    assert ok is False
    assert "401" in msg or "认证" in msg


@pytest.mark.asyncio
async def test_verify_api_openai_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hi"}}],
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = mock_response

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="openai",
            api_key="sk-test",
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )
    assert ok is True
    assert "gpt-4o" in msg


@pytest.mark.asyncio
async def test_verify_api_network_error():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="anthropic",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
        )
    assert ok is False
    assert "网络" in msg or "connect" in msg.lower()
