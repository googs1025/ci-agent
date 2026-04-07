"""Tests for prefetch module."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.prefetch import prepare_context, _write_temp_json, AnalysisContext
from ci_optimizer.resolver import ResolvedInput


class TestWriteTempJson:
    def test_writes_valid_json(self):
        data = {"key": "value", "count": 42}
        path = _write_temp_json(data, "test")
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data
        path.unlink()

    def test_handles_nested_data(self):
        data = {"runs": [{"id": 1, "name": "CI"}]}
        path = _write_temp_json(data, "test")
        loaded = json.loads(path.read_text())
        assert loaded["runs"][0]["id"] == 1
        path.unlink()


class TestPrepareContext:
    @pytest.mark.asyncio
    async def test_local_repo_collects_workflows(self, tmp_repo):
        resolved = ResolvedInput(local_path=tmp_repo)
        ctx = await prepare_context(resolved)

        assert len(ctx.workflow_files) == 2
        filenames = [f.name for f in ctx.workflow_files]
        assert "ci.yml" in filenames
        assert "deploy.yml" in filenames

    @pytest.mark.asyncio
    async def test_no_workflows_raises(self, tmp_repo_no_workflows):
        resolved = ResolvedInput(local_path=tmp_repo_no_workflows)
        with pytest.raises(FileNotFoundError, match="No GitHub Actions workflow files"):
            await prepare_context(resolved)

    @pytest.mark.asyncio
    async def test_local_repo_no_github_api(self, tmp_repo):
        """Local repo without owner/repo should not call GitHub API."""
        resolved = ResolvedInput(local_path=tmp_repo, owner=None, repo=None)
        ctx = await prepare_context(resolved)

        assert ctx.runs_json_path is None
        assert ctx.logs_json_path is None
        assert ctx.owner is None

    @pytest.mark.asyncio
    async def test_with_github_info_fetches_api(self, tmp_repo):
        """When owner/repo is set, GitHub API data is fetched."""
        resolved = ResolvedInput(
            local_path=tmp_repo, owner="octocat", repo="hello-world"
        )

        mock_client = AsyncMock()
        mock_client.list_workflow_runs.return_value = [
            {"id": 1, "conclusion": "success", "name": "CI"},
            {"id": 2, "conclusion": "failure", "name": "CI"},
        ]
        mock_client.get_run_jobs.return_value = [
            {"name": "test", "conclusion": "failure", "steps": []}
        ]
        mock_client.get_run_logs.return_value = "Error: test failed"
        mock_client.get_workflows.return_value = [
            {"id": 1, "name": "CI", "path": ".github/workflows/ci.yml"}
        ]
        mock_client.get_repo_info.return_value = {
            "full_name": "octocat/hello-world",
            "private": False,
        }

        with patch("ci_optimizer.prefetch.GitHubClient", return_value=mock_client):
            ctx = await prepare_context(resolved)

        assert ctx.runs_json_path is not None
        assert ctx.runs_json_path.exists()
        assert ctx.logs_json_path is not None
        assert ctx.logs_json_path.exists()
        assert ctx.workflows_json_path is not None
        assert ctx.repo_info is not None
        assert ctx.repo_info["full_name"] == "octocat/hello-world"

        # Verify run data was saved
        runs_data = json.loads(ctx.runs_json_path.read_text())
        assert len(runs_data) == 2

        # Verify logs data was saved (only failed runs)
        logs_data = json.loads(ctx.logs_json_path.read_text())
        assert "2" in logs_data  # run id 2 was failure

        # Cleanup temp files
        ctx.runs_json_path.unlink(missing_ok=True)
        ctx.logs_json_path.unlink(missing_ok=True)
        ctx.workflows_json_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_filters_passed_through(self, tmp_repo):
        """Filters should be stored in context."""
        resolved = ResolvedInput(local_path=tmp_repo)
        filters = AnalysisFilters(workflows=["ci.yml"], branches=["main"])
        ctx = await prepare_context(resolved, filters)

        assert ctx.filters is not None
        assert ctx.filters.workflows == ["ci.yml"]
        assert ctx.filters.branches == ["main"]
