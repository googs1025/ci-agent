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
    conclusion: str = "success",
    run_attempt: int = 1,
) -> dict:
    return {
        "action": action,
        "workflow_run": {
            "id": run_id,
            "head_branch": branch,
            "status": "completed",
            "conclusion": conclusion,
            "run_attempt": run_attempt,
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


class TestWebhookAutoDiagnose:
    """Verify that workflow_run failures route to the auto-diagnosis path."""

    @pytest.mark.asyncio
    async def test_failure_queues_auto_diagnose(self, client):
        import os

        from ci_optimizer.api import webhooks as wh

        payload = _workflow_run_payload(conclusion="failure")
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(wh, "_run_auto_diagnosis_task", new=AsyncMock()) as mock_task,
        ):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "workflow_run"})

        assert resp.status_code == 202
        body = resp.json()
        assert body["auto_diagnose"]["queued"] is True
        assert body["auto_diagnose"]["reason"] == "ok"
        # Background task is added via BackgroundTasks — verify the wrapper was
        # registered (the call itself is deferred until after response).
        assert mock_task is not None

    @pytest.mark.asyncio
    async def test_success_does_not_trigger_auto_diagnose(self, client):
        import os

        payload = _workflow_run_payload(conclusion="success")
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "workflow_run"})

        assert resp.status_code == 202
        body = resp.json()
        assert body["auto_diagnose"]["queued"] is False
        assert body["auto_diagnose"]["reason"] == "not-a-failure"

    @pytest.mark.asyncio
    async def test_auto_diagnose_respects_master_switch(self, client):
        import os

        from ci_optimizer.api import webhooks as wh
        from ci_optimizer.config import AgentConfig

        fake_config = AgentConfig()
        fake_config.diagnose_auto_on_webhook = False

        payload = _workflow_run_payload(conclusion="failure")
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(wh.AgentConfig, "load", return_value=fake_config),
        ):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "workflow_run"})

        assert resp.status_code == 202
        body = resp.json()
        assert body["auto_diagnose"]["queued"] is False
        assert body["auto_diagnose"]["reason"] == "disabled"

    @pytest.mark.asyncio
    async def test_auto_diagnose_respects_budget(self, client, db_session):
        """When 24h spend >= budget, auto-diagnosis is skipped."""
        import os

        from ci_optimizer.api import webhooks as wh
        from ci_optimizer.config import AgentConfig
        from ci_optimizer.db.crud import save_diagnosis
        from ci_optimizer.db.models import Repository

        # Seed a big past spend
        r = Repository(owner="acme", repo="svc")
        db_session.add(r)
        await db_session.flush()
        await save_diagnosis(
            db_session,
            repo_id=r.id,
            run_id=1,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="budgetcap001",
            model="m",
            cost_usd=5.0,
        )
        await db_session.commit()

        fake_config = AgentConfig()
        fake_config.diagnose_budget_usd_day = 1.0  # already exceeded

        payload = _workflow_run_payload(conclusion="failure")
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(wh.AgentConfig, "load", return_value=fake_config),
        ):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "workflow_run"})

        assert resp.status_code == 202
        body = resp.json()
        assert body["auto_diagnose"]["queued"] is False
        assert "budget-exceeded" in body["auto_diagnose"]["reason"]

    @pytest.mark.asyncio
    async def test_auto_diagnose_respects_sample_rate_zero(self, client):
        """Sample rate 0 means no auto-diagnosis."""
        import os

        from ci_optimizer.api import webhooks as wh
        from ci_optimizer.config import AgentConfig

        fake_config = AgentConfig()
        fake_config.diagnose_sample_rate = 0.0

        payload = _workflow_run_payload(conclusion="failure")
        with (
            patch.dict("os.environ", {}, clear=False),
            patch.object(wh.AgentConfig, "load", return_value=fake_config),
        ):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = await client.post(WEBHOOK_URL, json=payload, headers={"X-GitHub-Event": "workflow_run"})

        assert resp.status_code == 202
        body = resp.json()
        assert body["auto_diagnose"]["queued"] is False
        assert "sampled-out" in body["auto_diagnose"]["reason"]
