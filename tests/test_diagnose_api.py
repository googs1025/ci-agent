"""Tests for the /api/ci-runs/diagnose and /api/diagnoses/by-signature endpoints (v1).

Mocks both GitHubClient network calls and the underlying LLM invocation
so the tests run fully offline against an in-memory SQLite DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from ci_optimizer.api import diagnose as diagnose_module
from ci_optimizer.api.app import app
from ci_optimizer.api.routes import get_db
from ci_optimizer.db.crud import save_diagnosis
from ci_optimizer.db.models import Repository

DIAGNOSE_URL = "/api/ci-runs/diagnose"


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


def _mock_jobs_response(has_failure: bool = True) -> list[dict]:
    return [
        {
            "id": 999,
            "name": "test-job",
            "conclusion": "failure" if has_failure else "success",
            "workflow_name": "ci",
            "steps": [
                {"name": "checkout", "conclusion": "success"},
                {"name": "pytest unit", "conclusion": "failure" if has_failure else "success"},
            ],
        }
    ]


_FAKE_LOG = "\n".join(
    [
        "INFO: starting pytest unit",
        "tests/test_api.py::test_webhook FAILED",
        "AssertionError: expected 200, got 502",
        "Bad Gateway: upstream returned 502",
    ]
)

_FAKE_LLM_DIAG = {
    "category": "flaky_test",
    "confidence": "high",
    "root_cause": "Test sensitive to upstream 502 responses; no retry configured",
    "quick_fix": "Add @pytest.mark.flaky(reruns=2, reruns_delay=1) to test_webhook",
    "failing_step": "pytest unit",
    "model": "claude-haiku-4-5-20251001",
    "cost_usd": 0.0012,
}


def _patch_github_and_llm(llm_diag: dict | None = None):
    """Return a context manager that patches both GitHubClient + LLM."""
    from contextlib import ExitStack

    diag = llm_diag or _FAKE_LLM_DIAG

    class _PatchBundle:
        def __enter__(self):
            self.stack = ExitStack()
            self.stack.enter_context(
                patch.object(
                    diagnose_module.GitHubClient,
                    "get_run_jobs",
                    new=AsyncMock(return_value=_mock_jobs_response()),
                )
            )
            self.stack.enter_context(
                patch.object(
                    diagnose_module.GitHubClient,
                    "get_run_logs",
                    new=AsyncMock(return_value=_FAKE_LOG),
                )
            )
            self.stack.enter_context(
                patch.object(
                    diagnose_module.GitHubClient,
                    "close",
                    new=AsyncMock(return_value=None),
                )
            )
            self.llm_mock = AsyncMock(return_value=diag)
            self.stack.enter_context(patch.object(diagnose_module, "diagnose", new=self.llm_mock))
            return self

        def __exit__(self, *a):
            self.stack.close()

    return _PatchBundle()


class TestDiagnoseEndpoint:
    async def test_happy_path_returns_diagnosis(self, client):
        with _patch_github_and_llm():
            resp = await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == "flaky_test"
        assert body["confidence"] == "high"
        assert body["failing_step"] == "pytest unit"
        assert body["workflow"] == "ci"
        assert body["quick_fix"].startswith("Add @pytest.mark.flaky")
        assert body["cached"] is False
        assert body["source"] == "manual"
        assert "AssertionError" in body["error_excerpt"]
        assert len(body["error_signature"]) == 12

    async def test_exact_cache_hit_on_second_call(self, client):
        with _patch_github_and_llm() as bundle:
            await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})
            resp = await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        # LLM called exactly once (2nd request hit exact cache)
        assert bundle.llm_mock.call_count == 1

    async def test_different_run_attempt_is_fresh_diagnosis(self, client):
        with _patch_github_and_llm() as bundle:
            await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 12345, "run_attempt": 1},
            )
            # Same run, attempt 2 — should go to signature cache (same error),
            # but still persist a new DB row keyed on attempt=2.
            resp = await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 12345, "run_attempt": 2},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True  # signature cache reused the previous diagnosis
        assert body["cost_usd"] == 0.0  # no new LLM call
        assert bundle.llm_mock.call_count == 1  # LLM called only for attempt 1

    async def test_signature_cache_reused_across_repos(self, client):
        """Same error signature in a different repo should reuse the diagnosis."""
        with _patch_github_and_llm() as bundle:
            await client.post(DIAGNOSE_URL, json={"repo": "alice/app", "run_id": 100})
            resp = await client.post(DIAGNOSE_URL, json={"repo": "bob/app", "run_id": 200})

        assert resp.status_code == 200
        assert resp.json()["cached"] is True
        assert resp.json()["cost_usd"] == 0.0
        assert bundle.llm_mock.call_count == 1

    async def test_invalid_repo_format_returns_400(self, client):
        resp = await client.post(DIAGNOSE_URL, json={"repo": "no-slash-here", "run_id": 1})
        assert resp.status_code == 400
        assert "owner/name" in resp.json()["detail"]

    async def test_run_with_no_failed_jobs_returns_400(self, client):
        with (
            patch.object(
                diagnose_module.GitHubClient,
                "get_run_jobs",
                new=AsyncMock(return_value=_mock_jobs_response(has_failure=False)),
            ),
            patch.object(
                diagnose_module.GitHubClient,
                "close",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})

        assert resp.status_code == 400
        assert "no failed jobs" in resp.json()["detail"]

    async def test_run_not_found_returns_404(self, client):
        with (
            patch.object(
                diagnose_module.GitHubClient,
                "get_run_jobs",
                new=AsyncMock(side_effect=RuntimeError("Not Found")),
            ),
            patch.object(
                diagnose_module.GitHubClient,
                "close",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 99999})

        assert resp.status_code == 404

    async def test_empty_logs_returns_502(self, client):
        with (
            patch.object(
                diagnose_module.GitHubClient,
                "get_run_jobs",
                new=AsyncMock(return_value=_mock_jobs_response()),
            ),
            patch.object(
                diagnose_module.GitHubClient,
                "get_run_logs",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                diagnose_module.GitHubClient,
                "close",
                new=AsyncMock(return_value=None),
            ),
        ):
            resp = await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})

        assert resp.status_code == 502

    async def test_deep_tier_uses_sonnet_model(self, client):
        captured_model: dict[str, str] = {}

        async def _fake_diagnose(*, excerpt, failing_step, workflow, model, config):
            captured_model["model"] = model
            return {**_FAKE_LLM_DIAG, "model": model}

        with (
            patch.object(
                diagnose_module.GitHubClient,
                "get_run_jobs",
                new=AsyncMock(return_value=_mock_jobs_response()),
            ),
            patch.object(
                diagnose_module.GitHubClient,
                "get_run_logs",
                new=AsyncMock(return_value=_FAKE_LOG),
            ),
            patch.object(
                diagnose_module.GitHubClient,
                "close",
                new=AsyncMock(return_value=None),
            ),
            patch.object(diagnose_module, "diagnose", new=_fake_diagnose),
        ):
            resp = await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 12345, "tier": "deep"},
            )

        assert resp.status_code == 200
        assert "sonnet" in captured_model["model"]


class TestSignatureCluster:
    async def test_by_signature_returns_matching_runs(self, client, db_session):
        # Seed 2 diagnoses with the same signature
        repo = Repository(owner="acme", repo="svc")
        db_session.add(repo)
        await db_session.flush()

        for run_id in (100, 200):
            await save_diagnosis(
                db_session,
                repo_id=repo.id,
                run_id=run_id,
                run_attempt=1,
                tier="default",
                category="timeout",
                confidence="high",
                root_cause="Exceeded 60m",
                quick_fix="timeout-minutes: 90",
                failing_step="e2e",
                workflow="ci",
                error_excerpt="##[error]The operation was canceled.",
                error_signature="abc123def456",
                model="claude-haiku-4-5-20251001",
                cost_usd=0.001,
            )
        await db_session.commit()

        resp = await client.get("/api/diagnoses/by-signature/abc123def456?days=30")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert body["category"] == "timeout"
        assert len(body["runs"]) == 2
        assert {r["run_id"] for r in body["runs"]} == {100, 200}
        for r in body["runs"]:
            assert r["repo"] == "acme/svc"

    async def test_invalid_signature_returns_400(self, client):
        # Not 12 chars
        resp = await client.get("/api/diagnoses/by-signature/toolong12345678")
        assert resp.status_code == 400
        # Non-hex
        resp = await client.get("/api/diagnoses/by-signature/NOTHEXCHARS!")
        assert resp.status_code == 400

    async def test_no_matches_returns_empty_list(self, client):
        resp = await client.get("/api/diagnoses/by-signature/000000000000")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["runs"] == []
        assert body["category"] is None


class TestParseDiagnosis:
    """Unit tests for the JSON parser robustness (agent module)."""

    def test_parse_strict_json(self):
        from ci_optimizer.agents.failure_triage import _parse_diagnosis

        raw = '{"category":"timeout","confidence":"high","root_cause":"job exceeded 60m","quick_fix":"add timeout-minutes: 90","failing_step":"e2e"}'
        result = _parse_diagnosis(raw, failing_step="e2e")
        assert result["category"] == "timeout"
        assert result["confidence"] == "high"
        assert result["failing_step"] == "e2e"

    def test_parse_json_wrapped_in_prose(self):
        from ci_optimizer.agents.failure_triage import _parse_diagnosis

        raw = 'Here is my analysis:\n{"category":"network","confidence":"medium","root_cause":"DNS timeout","quick_fix":null,"failing_step":null}\nHope that helps!'
        result = _parse_diagnosis(raw, failing_step=None)
        assert result["category"] == "network"
        assert result["quick_fix"] is None

    def test_parse_invalid_category_falls_back(self):
        from ci_optimizer.agents.failure_triage import _parse_diagnosis

        raw = '{"category":"alien_invasion","confidence":"high","root_cause":"X"}'
        result = _parse_diagnosis(raw, failing_step=None)
        assert result["category"] == "unknown"

    def test_parse_invalid_json_returns_unknown(self):
        from ci_optimizer.agents.failure_triage import _parse_diagnosis

        raw = "not json at all just prose"
        result = _parse_diagnosis(raw, failing_step="test")
        assert result["category"] == "unknown"
        assert result["confidence"] == "low"
        assert result["failing_step"] == "test"

    def test_parse_malformed_json_returns_unknown(self):
        from ci_optimizer.agents.failure_triage import _parse_diagnosis

        raw = '{"category":"timeout" "confidence":"high"}'  # missing comma
        result = _parse_diagnosis(raw, failing_step=None)
        assert result["category"] == "unknown"
