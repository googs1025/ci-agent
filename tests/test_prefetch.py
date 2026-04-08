"""Tests for prefetch module."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.prefetch import (
    prepare_context,
    _write_temp_json,
    _compute_usage_stats,
    _duration_ms,
    _detect_runner_os,
    AnalysisContext,
)
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


class TestDurationMs:
    def test_valid_timestamps(self):
        assert _duration_ms("2024-01-01T00:00:00Z", "2024-01-01T00:05:00Z") == 300000

    def test_none_start(self):
        assert _duration_ms(None, "2024-01-01T00:05:00Z") is None

    def test_none_end(self):
        assert _duration_ms("2024-01-01T00:00:00Z", None) is None

    def test_both_none(self):
        assert _duration_ms(None, None) is None


class TestDetectRunnerOs:
    def test_ubuntu(self):
        assert _detect_runner_os(["ubuntu-latest"]) == "ubuntu"

    def test_macos(self):
        assert _detect_runner_os(["macos-latest"]) == "macos"

    def test_windows(self):
        assert _detect_runner_os(["windows-latest"]) == "windows"

    def test_self_hosted_linux(self):
        assert _detect_runner_os(["self-hosted", "linux"]) == "ubuntu"

    def test_unknown(self):
        assert _detect_runner_os(["self-hosted", "custom"]) == "unknown"

    def test_none(self):
        assert _detect_runner_os(None) == "unknown"

    def test_empty(self):
        assert _detect_runner_os([]) == "unknown"


class TestComputeUsageStats:
    def test_empty_data(self):
        stats = _compute_usage_stats([], {})
        assert stats["total_runs"] == 0
        assert stats["total_jobs"] == 0

    def test_basic_stats(self):
        runs = [
            {"id": 1, "name": "CI", "conclusion": "success", "run_started_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:10:00Z"},
            {"id": 2, "name": "CI", "conclusion": "failure", "run_started_at": "2024-01-01T01:00:00Z", "updated_at": "2024-01-01T01:05:00Z"},
        ]
        all_jobs = {
            "1": [
                {
                    "name": "test",
                    "conclusion": "success",
                    "labels": ["ubuntu-latest"],
                    "created_at": "2024-01-01T00:00:00Z",
                    "started_at": "2024-01-01T00:00:10Z",
                    "completed_at": "2024-01-01T00:05:00Z",
                    "steps": [
                        {"name": "Run tests", "conclusion": "success", "started_at": "2024-01-01T00:01:00Z", "completed_at": "2024-01-01T00:04:00Z"},
                    ],
                }
            ],
            "2": [
                {
                    "name": "test",
                    "conclusion": "failure",
                    "labels": ["ubuntu-latest"],
                    "created_at": "2024-01-01T01:00:00Z",
                    "started_at": "2024-01-01T01:00:05Z",
                    "completed_at": "2024-01-01T01:03:00Z",
                    "steps": [],
                }
            ],
        }

        stats = _compute_usage_stats(runs, all_jobs)

        assert stats["total_runs"] == 2
        assert stats["total_jobs"] == 2
        assert stats["conclusion_counts"]["success"] == 1
        assert stats["conclusion_counts"]["failure"] == 1
        assert stats["runner_distribution"]["ubuntu"] == 2

        # Per-workflow
        assert stats["per_workflow"]["CI"]["total_runs"] == 2
        assert stats["per_workflow"]["CI"]["success"] == 1
        assert stats["per_workflow"]["CI"]["success_rate"] == 50.0

        # Per-job
        assert stats["per_job"]["test"]["total_runs"] == 2
        assert stats["per_job"]["test"]["success"] == 1

        # Timing
        assert stats["timing"]["avg_job_duration_ms"] > 0
        assert stats["timing"]["avg_queue_wait_ms"] >= 0

        # Billing
        assert stats["billing_estimate"]["total_minutes"] > 0
        assert stats["billing_estimate"]["by_os"]["ubuntu"] > 0

    def test_runner_multipliers(self):
        runs = [{"id": 1, "name": "CI", "conclusion": "success"}]
        all_jobs = {
            "1": [
                {
                    "name": "build",
                    "conclusion": "success",
                    "labels": ["macos-latest"],
                    "created_at": "2024-01-01T00:00:00Z",
                    "started_at": "2024-01-01T00:00:00Z",
                    "completed_at": "2024-01-01T00:02:00Z",  # 2 minutes
                    "steps": [],
                }
            ],
        }

        stats = _compute_usage_stats(runs, all_jobs)
        # 2 minutes × 10 (macOS multiplier) = 20
        assert stats["billing_estimate"]["by_os"]["macos"] == 20

    def test_slowest_steps(self):
        runs = [{"id": 1, "name": "CI", "conclusion": "success"}]
        all_jobs = {
            "1": [
                {
                    "name": "build",
                    "conclusion": "success",
                    "labels": ["ubuntu-latest"],
                    "created_at": "2024-01-01T00:00:00Z",
                    "started_at": "2024-01-01T00:00:00Z",
                    "completed_at": "2024-01-01T00:10:00Z",
                    "steps": [
                        {"name": "Checkout", "conclusion": "success", "started_at": "2024-01-01T00:00:00Z", "completed_at": "2024-01-01T00:00:05Z"},
                        {"name": "Install deps", "conclusion": "success", "started_at": "2024-01-01T00:00:05Z", "completed_at": "2024-01-01T00:03:00Z"},
                        {"name": "Build", "conclusion": "success", "started_at": "2024-01-01T00:03:00Z", "completed_at": "2024-01-01T00:09:00Z"},
                    ],
                }
            ],
        }

        stats = _compute_usage_stats(runs, all_jobs)
        assert len(stats["slowest_steps"]) == 3
        assert stats["slowest_steps"][0]["step"] == "Build"  # slowest first


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
        assert ctx.jobs_json_path is None
        assert ctx.usage_stats_json_path is None
        assert ctx.logs_json_path is None
        assert ctx.owner is None

    @pytest.mark.asyncio
    async def test_with_github_info_fetches_all_jobs(self, tmp_repo):
        """When owner/repo is set, jobs are fetched for ALL runs."""
        resolved = ResolvedInput(
            local_path=tmp_repo, owner="octocat", repo="hello-world"
        )

        mock_client = AsyncMock()
        mock_client.list_workflow_runs.return_value = [
            {"id": 1, "conclusion": "success", "name": "CI", "run_started_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:05:00Z"},
            {"id": 2, "conclusion": "failure", "name": "CI", "run_started_at": "2024-01-01T01:00:00Z", "updated_at": "2024-01-01T01:03:00Z"},
        ]
        mock_client.get_run_jobs.return_value = [
            {
                "id": 100,
                "name": "test",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2024-01-01T00:00:00Z",
                "started_at": "2024-01-01T00:00:05Z",
                "completed_at": "2024-01-01T00:05:00Z",
                "runner_id": 1,
                "runner_name": "runner-1",
                "labels": ["ubuntu-latest"],
                "steps": [
                    {"name": "Run tests", "status": "completed", "conclusion": "success", "number": 1, "started_at": "2024-01-01T00:01:00Z", "completed_at": "2024-01-01T00:04:00Z"},
                ],
            }
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

        # get_run_jobs called for BOTH runs (not just failed)
        assert mock_client.get_run_jobs.call_count == 2

        # All new data files exist
        assert ctx.jobs_json_path is not None
        assert ctx.jobs_json_path.exists()
        assert ctx.usage_stats_json_path is not None
        assert ctx.usage_stats_json_path.exists()
        assert ctx.runs_json_path is not None
        assert ctx.logs_json_path is not None

        # Verify jobs data contains both runs
        jobs_data = json.loads(ctx.jobs_json_path.read_text())
        assert "1" in jobs_data
        assert "2" in jobs_data
        assert len(jobs_data["1"]) == 1
        assert jobs_data["1"][0]["labels"] == ["ubuntu-latest"]

        # Verify usage stats were computed
        usage_data = json.loads(ctx.usage_stats_json_path.read_text())
        assert usage_data["total_runs"] == 2
        assert usage_data["total_jobs"] == 2
        assert "ubuntu" in usage_data["runner_distribution"]
        assert usage_data["billing_estimate"]["total_minutes"] > 0

        # Cleanup
        for p in [ctx.runs_json_path, ctx.jobs_json_path, ctx.usage_stats_json_path,
                   ctx.logs_json_path, ctx.workflows_json_path]:
            if p:
                p.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_filters_passed_through(self, tmp_repo):
        """Filters should be stored in context."""
        resolved = ResolvedInput(local_path=tmp_repo)
        filters = AnalysisFilters(workflows=["ci.yml"], branches=["main"])
        ctx = await prepare_context(resolved, filters)

        assert ctx.filters is not None
        assert ctx.filters.workflows == ["ci.yml"]
        assert ctx.filters.branches == ["main"]
