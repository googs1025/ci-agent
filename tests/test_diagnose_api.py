"""Tests for the /api/ci-runs/diagnose endpoint.

Mocks both GitHubClient network calls and the underlying LLM invocation
so the tests run fully offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from ci_optimizer.api import diagnose as diagnose_module
from ci_optimizer.api.app import app

DIAGNOSE_URL = "/api/ci-runs/diagnose"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure the v0 in-memory cache is clean for each test."""
    diagnose_module._CACHE.clear()
    yield
    diagnose_module._CACHE.clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
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


class TestDiagnoseEndpoint:
    async def test_happy_path_returns_diagnosis(self, client):
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
            patch.object(
                diagnose_module,
                "diagnose",
                new=AsyncMock(return_value=_FAKE_LLM_DIAG),
            ),
        ):
            resp = await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 12345},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == "flaky_test"
        assert body["confidence"] == "high"
        assert body["failing_step"] == "pytest unit"
        assert body["workflow"] == "ci"
        assert body["quick_fix"].startswith("Add @pytest.mark.flaky")
        assert body["cached"] is False
        # excerpt should contain the error line
        assert "AssertionError" in body["error_excerpt"]
        # signature should be 12-char hex
        assert len(body["error_signature"]) == 12

    async def test_second_call_returns_cached(self, client):
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
            patch.object(
                diagnose_module,
                "diagnose",
                new=AsyncMock(return_value=_FAKE_LLM_DIAG),
            ) as llm_mock,
        ):
            await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})
            resp = await client.post(DIAGNOSE_URL, json={"repo": "owner/name", "run_id": 12345})

        assert resp.status_code == 200
        body = resp.json()
        assert body["cached"] is True
        # LLM called only once (cache hit on the 2nd request)
        assert llm_mock.call_count == 1

    async def test_invalid_repo_format_returns_400(self, client):
        resp = await client.post(
            DIAGNOSE_URL,
            json={"repo": "no-slash-here", "run_id": 1},
        )
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
            resp = await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 12345},
            )

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
            resp = await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 99999},
            )

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
            resp = await client.post(
                DIAGNOSE_URL,
                json={"repo": "owner/name", "run_id": 12345},
            )

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


class TestParseDiagnosis:
    """Unit tests for the JSON parser robustness (via the agent module)."""

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
