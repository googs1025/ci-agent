"""Tests for configuration module."""

import json
import os
from unittest.mock import patch

import pytest

from ci_optimizer.config import DEFAULT_MODEL, AgentConfig


class TestAgentConfig:
    def test_defaults(self):
        config = AgentConfig()
        assert config.model == DEFAULT_MODEL
        assert config.fallback_model is None
        assert config.anthropic_api_key is None
        assert config.github_token is None
        assert config.max_turns == 20

    def test_save_and_load(self, tmp_path):
        config_file = tmp_path / "config.json"
        with (
            patch("ci_optimizer.config.CONFIG_FILE", config_file),
            patch("ci_optimizer.config.CONFIG_DIR", tmp_path),
            patch.dict(os.environ, {}, clear=True),
        ):
            config = AgentConfig(
                model="claude-opus-4-20250514",
                anthropic_api_key="sk-test-key",
                github_token="ghp-test-token",
                max_turns=30,
            )
            config.save()

            assert config_file.exists()
            saved = json.loads(config_file.read_text())
            assert saved["model"] == "claude-opus-4-20250514"
            assert saved["anthropic_api_key"] == "sk-test-key"

            loaded = AgentConfig.load()
            assert loaded.model == "claude-opus-4-20250514"
            assert loaded.anthropic_api_key == "sk-test-key"
            assert loaded.github_token == "ghp-test-token"
            assert loaded.max_turns == 30

    def test_env_overrides_file(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps(
                {
                    "model": "from-file",
                    "anthropic_api_key": "from-file-key",
                }
            )
        )

        with (
            patch("ci_optimizer.config.CONFIG_FILE", config_file),
            patch("ci_optimizer.config.CONFIG_DIR", tmp_path),
            patch.dict(
                os.environ,
                {
                    "ANTHROPIC_API_KEY": "from-env-key",
                    "CI_AGENT_MODEL": "from-env-model",
                },
            ),
        ):
            config = AgentConfig.load()
            assert config.anthropic_api_key == "from-env-key"  # env wins
            assert config.model == "from-env-model"  # env wins

    def test_load_no_config_file(self, tmp_path):
        config_file = tmp_path / "nonexistent.json"
        with (
            patch("ci_optimizer.config.CONFIG_FILE", config_file),
            patch("ci_optimizer.config.CONFIG_DIR", tmp_path),
            patch.dict(os.environ, {}, clear=True),
        ):
            config = AgentConfig.load()
            assert config.model == DEFAULT_MODEL

    def test_get_sdk_env(self):
        config = AgentConfig(anthropic_api_key="sk-test")
        env = config.get_sdk_env()
        assert env == {"ANTHROPIC_API_KEY": "sk-test"}

    def test_get_sdk_env_empty(self):
        config = AgentConfig()
        env = config.get_sdk_env()
        assert env == {}

    def test_to_display_dict_masks_keys(self):
        config = AgentConfig(
            anthropic_api_key="sk-ant-api03-very-long-key-here",
            github_token="ghp_very-long-token-here",
        )
        display = config.to_display_dict()
        assert "sk-ant-a" in display["anthropic_api_key"]
        assert "here" in display["anthropic_api_key"]
        assert "..." in display["anthropic_api_key"]
        # Full key should NOT be in display
        assert display["anthropic_api_key"] != "sk-ant-api03-very-long-key-here"

    def test_to_display_dict_short_key(self):
        config = AgentConfig(anthropic_api_key="short")
        display = config.to_display_dict()
        assert display["anthropic_api_key"] == "***"

    def test_save_omits_none(self, tmp_path):
        config_file = tmp_path / "config.json"
        with patch("ci_optimizer.config.CONFIG_FILE", config_file), patch("ci_optimizer.config.CONFIG_DIR", tmp_path):
            config = AgentConfig(model="test-model")
            config.save()

            saved = json.loads(config_file.read_text())
            assert "fallback_model" not in saved
            assert "anthropic_api_key" not in saved


class TestAgentConfigApi:
    @pytest.mark.asyncio
    async def test_get_config(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "model" in data

    @pytest.mark.asyncio
    async def test_update_config(self, client, tmp_path):
        with patch("ci_optimizer.config.CONFIG_FILE", tmp_path / "config.json"), patch("ci_optimizer.config.CONFIG_DIR", tmp_path):
            resp = await client.put(
                "/api/config",
                json={
                    "model": "claude-opus-4-20250514",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["model"] == "claude-opus-4-20250514"


# Fixtures for API tests
@pytest.fixture
async def client(db_session):
    from httpx import ASGITransport, AsyncClient

    from ci_optimizer.api.app import app
    from ci_optimizer.api.routes import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
