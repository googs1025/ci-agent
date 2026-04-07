"""Tests for GitHub client with mocked HTTP responses."""

import json

import httpx
import pytest

from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.github_client import GitHubClient


@pytest.fixture
def mock_transport():
    """Create a mock httpx transport that returns predefined responses."""

    class MockTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.responses = {}

        def add_response(self, path: str, data: dict | list, status_code: int = 200):
            self.responses[path] = (status_code, data)

        async def handle_async_request(self, request: httpx.Request):
            path = request.url.path
            if path in self.responses:
                status_code, data = self.responses[path]
                return httpx.Response(
                    status_code=status_code,
                    json=data,
                    request=request,
                )
            return httpx.Response(404, json={"message": "Not Found"}, request=request)

    return MockTransport()


@pytest.fixture
def client_with_transport(mock_transport):
    """Create a GitHubClient with a mock transport."""
    client = GitHubClient(token="test-token")
    client._client = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=mock_transport,
    )
    return client, mock_transport


@pytest.mark.asyncio
async def test_list_workflow_runs(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo/actions/runs",
        {
            "total_count": 2,
            "workflow_runs": [
                {
                    "id": 1,
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": "main",
                    "path": ".github/workflows/ci.yml",
                },
                {
                    "id": 2,
                    "name": "CI",
                    "status": "completed",
                    "conclusion": "failure",
                    "head_branch": "feature",
                    "path": ".github/workflows/ci.yml",
                },
            ],
        },
    )

    runs = await client.list_workflow_runs("owner", "repo")
    assert len(runs) == 2
    assert runs[0]["id"] == 1
    assert runs[1]["conclusion"] == "failure"

    await client.close()


@pytest.mark.asyncio
async def test_list_workflow_runs_with_branch_filter(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo/actions/runs",
        {
            "total_count": 2,
            "workflow_runs": [
                {"id": 1, "head_branch": "main", "name": "CI", "path": ".github/workflows/ci.yml", "conclusion": "success", "status": "completed"},
                {"id": 2, "head_branch": "feature", "name": "CI", "path": ".github/workflows/ci.yml", "conclusion": "success", "status": "completed"},
            ],
        },
    )

    filters = AnalysisFilters(branches=["main", "develop"])
    runs = await client.list_workflow_runs("owner", "repo", filters)
    # Client-side filter: only "main" matches
    assert len(runs) == 1
    assert runs[0]["head_branch"] == "main"

    await client.close()


@pytest.mark.asyncio
async def test_list_workflow_runs_with_workflow_filter(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo/actions/runs",
        {
            "total_count": 2,
            "workflow_runs": [
                {"id": 1, "name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main", "conclusion": "success", "status": "completed"},
                {"id": 2, "name": "Deploy", "path": ".github/workflows/deploy.yml", "head_branch": "main", "conclusion": "success", "status": "completed"},
            ],
        },
    )

    filters = AnalysisFilters(workflows=["ci.yml"])
    runs = await client.list_workflow_runs("owner", "repo", filters)
    assert len(runs) == 1
    assert runs[0]["name"] == "CI"

    await client.close()


@pytest.mark.asyncio
async def test_list_workflow_runs_with_status_filter(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo/actions/runs",
        {
            "total_count": 3,
            "workflow_runs": [
                {"id": 1, "conclusion": "success", "status": "completed", "name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main"},
                {"id": 2, "conclusion": "failure", "status": "completed", "name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main"},
                {"id": 3, "conclusion": "cancelled", "status": "completed", "name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main"},
            ],
        },
    )

    filters = AnalysisFilters(status=["failure", "cancelled"])
    runs = await client.list_workflow_runs("owner", "repo", filters)
    assert len(runs) == 2
    conclusions = {r["conclusion"] for r in runs}
    assert conclusions == {"failure", "cancelled"}

    await client.close()


@pytest.mark.asyncio
async def test_get_run_jobs(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo/actions/runs/123/jobs",
        {
            "total_count": 1,
            "jobs": [
                {
                    "id": 456,
                    "name": "test",
                    "status": "completed",
                    "conclusion": "failure",
                    "started_at": "2024-01-01T00:00:00Z",
                    "completed_at": "2024-01-01T00:05:00Z",
                    "steps": [
                        {"name": "Run tests", "conclusion": "failure", "number": 3},
                    ],
                }
            ],
        },
    )

    jobs = await client.get_run_jobs("owner", "repo", 123)
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test"
    assert jobs[0]["conclusion"] == "failure"

    await client.close()


@pytest.mark.asyncio
async def test_get_workflows(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo/actions/workflows",
        {
            "total_count": 2,
            "workflows": [
                {"id": 1, "name": "CI", "path": ".github/workflows/ci.yml", "state": "active"},
                {"id": 2, "name": "Deploy", "path": ".github/workflows/deploy.yml", "state": "active"},
            ],
        },
    )

    workflows = await client.get_workflows("owner", "repo")
    assert len(workflows) == 2
    assert workflows[0]["name"] == "CI"

    await client.close()


@pytest.mark.asyncio
async def test_get_repo_info(client_with_transport):
    client, transport = client_with_transport
    transport.add_response(
        "/repos/owner/repo",
        {
            "full_name": "owner/repo",
            "private": False,
            "default_branch": "main",
        },
    )

    info = await client.get_repo_info("owner", "repo")
    assert info["full_name"] == "owner/repo"
    assert info["private"] is False

    await client.close()


@pytest.mark.asyncio
async def test_get_workflow_timing_not_found(client_with_transport):
    """Timing endpoint returns None on error."""
    client, transport = client_with_transport
    # No response registered for this path -> 404
    result = await client.get_workflow_timing("owner", "repo", 999)
    assert result is None

    await client.close()
