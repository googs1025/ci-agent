"""Tests for API key authentication."""

import pytest
from httpx import ASGITransport, AsyncClient

from ci_optimizer.api.app import app
from ci_optimizer.api.routes import get_db


@pytest.fixture
async def test_app(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAuthNoKeyConfigured:
    """When CI_AGENT_API_KEY is not set, all requests pass through."""

    @pytest.mark.asyncio
    async def test_api_endpoint_accessible(self, client, monkeypatch):
        monkeypatch.delenv("CI_AGENT_API_KEY", raising=False)
        resp = await client.get("/api/dashboard")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_accessible(self, client, monkeypatch):
        monkeypatch.delenv("CI_AGENT_API_KEY", raising=False)
        resp = await client.get("/health")
        assert resp.status_code == 200


class TestAuthWithKeyConfigured:
    """When CI_AGENT_API_KEY is set, /api/* endpoints require a valid Bearer token."""

    API_KEY = "test-secret-key-12345"

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("CI_AGENT_API_KEY", self.API_KEY)
        resp = await client.get("/api/dashboard")
        assert resp.status_code == 401
        assert "Invalid or missing API key" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("CI_AGENT_API_KEY", self.API_KEY)
        resp = await client.get(
            "/api/dashboard",
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_token_passes(self, client, monkeypatch):
        monkeypatch.setenv("CI_AGENT_API_KEY", self.API_KEY)
        resp = await client.get(
            "/api/dashboard",
            headers={"Authorization": f"Bearer {self.API_KEY}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_always_exempt(self, client, monkeypatch):
        monkeypatch.setenv("CI_AGENT_API_KEY", self.API_KEY)
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
