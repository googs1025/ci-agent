"""Tests for GitHub webhook endpoint."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from ci_optimizer.api.app import app
from ci_optimizer.api.routes import get_db

WEBHOOK_URL = "/api/webhooks/github"

# Mock _run_analysis_task globally so background tasks don't hit the real DB
_mock_analysis = patch(
    "ci_optimizer.api.webhooks._run_analysis_task",
    new_callable=AsyncMock,
)


@pytest.fixture
async def test_app(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with _mock_analysis:
        yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(test_app):
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _sign(body: bytes, secret: str) -> str:
    """Compute X-Hub-Signature-256 header value."""
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _workflow_run_payload(
    repo_full_name: str = "octocat/hello-world",
    action: str = "completed",
    run_id: int = 12345,
    branch: str = "main",
) -> dict:
    return {
        "action": action,
        "workflow_run": {
            "id": run_id,
            "head_branch": branch,
            "status": "completed",
            "conclusion": "success",
        },
        "repository": {
            "full_name": repo_full_name,
            "html_url": f"https://github.com/{repo_full_name}",
        },
    }


class TestWebhookSignatureValidation:
    @pytest.mark.asyncio
    async def test_missing_signature_rejected_when_secret_set(self, client):
        payload = json.dumps({"repo": "octocat/hello"}).encode()
        with patch.dict("os.environ", {"WEBHOOK_SECRET": "mysecret"}):
            resp = await client.post(
                WEBHOOK_URL,
                content=payload,
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, client):
        payload = json.dumps({"repo": "octocat/hello"}).encode()
        with patch.dict("os.environ", {"WEBHOOK_SECRET": "mysecret"}):
            resp = await client.post(
                WEBHOOK_URL,
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=invalid",
                },
            )
        assert resp.status_code == 401
        assert "Invalid webhook signature" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self, client):
        secret = "test-secret-123"
        payload = json.dumps({"repo": "octocat/hello"}).encode()
        sig = _sign(payload, secret)
        with patch.dict("os.environ", {"WEBHOOK_SECRET": secret}):
            resp = await client.post(
                WEBHOOK_URL,
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": sig,
                },
            )
        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_no_secret_configured_skips_validation(self, client):
        """When WEBHOOK_SECRET is not set, any request is accepted."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove WEBHOOK_SECRET if present
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(
                WEBHOOK_URL,
                json={"repo": "octocat/hello"},
            )
        assert resp.status_code == 202


class TestWebhookWorkflowRunEvent:
    @pytest.mark.asyncio
    async def test_completed_workflow_triggers_analysis(self, client):
        payload = _workflow_run_payload()
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(
                WEBHOOK_URL,
                json=payload,
                headers={"X-GitHub-Event": "workflow_run"},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["repo"] == "octocat/hello-world"
        assert "report_id" in data

    @pytest.mark.asyncio
    async def test_non_completed_action_ignored(self, client):
        payload = _workflow_run_payload(action="requested")
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(
                WEBHOOK_URL,
                json=payload,
                headers={"X-GitHub-Event": "workflow_run"},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "ignored"

    @pytest.mark.asyncio
    async def test_missing_repo_full_name_rejected(self, client):
        payload = {
            "action": "completed",
            "workflow_run": {"id": 1},
            "repository": {},
        }
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(
                WEBHOOK_URL,
                json=payload,
                headers={"X-GitHub-Event": "workflow_run"},
            )
        assert resp.status_code == 400


class TestWebhookSimplePayload:
    @pytest.mark.asyncio
    async def test_simple_repo_trigger(self, client):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json={"repo": "org/myrepo"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["repo"] == "org/myrepo"

    @pytest.mark.asyncio
    async def test_invalid_repo_format_rejected(self, client):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json={"repo": "noslash"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_unsupported_payload_rejected(self, client):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json={"random": "data"})
        assert resp.status_code == 400
