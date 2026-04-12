"""Integration tests — real GitHub API calls, mock Agent SDK.

These tests make REAL requests to the GitHub API to verify data collection
works against a live repository. Agent SDK is still mocked (no Anthropic costs).

Requirements:
  - GITHUB_TOKEN env var set (or skip)
  - Network access to api.github.com

Target repo: https://github.com/kubernetes-sigs/descheduler
"""

import json
import os

import pytest

from ci_optimizer.agents.orchestrator import AnalysisResult
from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.github_client import GitHubClient
from ci_optimizer.prefetch import prepare_context
from ci_optimizer.report.formatter import format_json, format_markdown
from ci_optimizer.resolver import resolve_input

OWNER = "kubernetes-sigs"
REPO = "descheduler"
REPO_URL = f"https://github.com/{OWNER}/{REPO}"

skip_no_token = pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN"),
    reason="GITHUB_TOKEN not set — skipping real GitHub API tests",
)


@skip_no_token
class TestGitHubClientReal:
    """Test GitHubClient against the real GitHub API."""

    @pytest.mark.asyncio
    async def test_list_workflow_runs(self):
        client = GitHubClient()
        try:
            runs = await client.list_workflow_runs(OWNER, REPO, per_page=5)
            assert isinstance(runs, list)
            assert len(runs) > 0

            run = runs[0]
            assert "id" in run
            assert "name" in run
            assert "status" in run
            assert "conclusion" in run or run["status"] == "in_progress"
            assert "created_at" in run
            assert "head_branch" in run
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_list_workflow_runs_with_filter(self):
        client = GitHubClient()
        try:
            filters = AnalysisFilters(branches=["master"])
            runs = await client.list_workflow_runs(OWNER, REPO, filters, per_page=5)
            assert isinstance(runs, list)
            for run in runs:
                assert run["head_branch"] == "master"
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_run_jobs(self):
        client = GitHubClient()
        try:
            runs = await client.list_workflow_runs(OWNER, REPO, per_page=3)
            assert len(runs) > 0

            # Get jobs for the first completed run
            completed = [r for r in runs if r.get("status") == "completed"]
            if not completed:
                pytest.skip("No completed runs found")

            run_id = completed[0]["id"]
            jobs = await client.get_run_jobs(OWNER, REPO, run_id)
            assert isinstance(jobs, list)
            assert len(jobs) > 0

            job = jobs[0]
            assert "id" in job
            assert "name" in job
            assert "started_at" in job
            assert "completed_at" in job
            assert "labels" in job
            assert isinstance(job["labels"], list)
            assert "steps" in job
            assert isinstance(job["steps"], list)

            if job["steps"]:
                step = job["steps"][0]
                assert "name" in step
                assert "started_at" in step
                assert "completed_at" in step
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_workflows(self):
        client = GitHubClient()
        try:
            workflows = await client.get_workflows(OWNER, REPO)
            assert isinstance(workflows, list)
            assert len(workflows) > 0

            wf = workflows[0]
            assert "id" in wf
            assert "name" in wf
            assert "path" in wf
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_get_repo_info(self):
        client = GitHubClient()
        try:
            info = await client.get_repo_info(OWNER, REPO)
            assert info["full_name"] == f"{OWNER}/{REPO}"
            assert "default_branch" in info
        finally:
            await client.close()


@skip_no_token
class TestPrefetchReal:
    """Test full prefetch pipeline with real GitHub API data."""

    @pytest.mark.asyncio
    async def test_prefetch_clones_and_collects(self):
        """Clone descheduler, fetch real API data, compute usage stats."""
        resolved = resolve_input(REPO_URL)

        try:
            assert resolved.owner == OWNER
            assert resolved.repo == REPO
            assert resolved.is_remote is True
            assert resolved.local_path.exists()

            # Check workflow files were found in the clone
            wf_dir = resolved.local_path / ".github" / "workflows"
            assert wf_dir.exists()
            wf_files = list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))
            assert len(wf_files) > 0
            print(f"\nWorkflow files found: {[f.name for f in wf_files]}")

            # Run prefetch with real API
            ctx = await prepare_context(resolved)

            # Verify workflow files collected
            assert len(ctx.workflow_files) > 0
            print(f"Workflow files in context: {len(ctx.workflow_files)}")

            # Verify runs data
            assert ctx.runs_json_path is not None
            assert ctx.runs_json_path.exists()
            runs = json.loads(ctx.runs_json_path.read_text())
            print(f"Runs fetched: {len(runs)}")
            assert isinstance(runs, list)

            # Verify jobs data (ALL runs, not just failed)
            assert ctx.jobs_json_path is not None
            assert ctx.jobs_json_path.exists()
            jobs_data = json.loads(ctx.jobs_json_path.read_text())
            total_jobs = sum(len(jobs) for jobs in jobs_data.values())
            print(f"Jobs fetched: {total_jobs} across {len(jobs_data)} runs")
            assert total_jobs > 0

            # Verify at least one job has expected fields
            some_jobs = next(iter(jobs_data.values()))
            job = some_jobs[0]
            assert "name" in job
            assert "labels" in job
            assert "started_at" in job
            assert "steps" in job

            # Verify usage stats computed
            assert ctx.usage_stats_json_path is not None
            assert ctx.usage_stats_json_path.exists()
            usage = json.loads(ctx.usage_stats_json_path.read_text())

            print("\n--- Usage Stats ---")
            print(f"Total runs: {usage['total_runs']}")
            print(f"Total jobs: {usage['total_jobs']}")
            print(f"Conclusions: {usage['conclusion_counts']}")
            print(f"Runner distribution: {usage['runner_distribution']}")
            print(f"Billing estimate: {usage['billing_estimate']['total_minutes']} minutes")
            print(f"Avg job duration: {usage['timing']['avg_job_duration_ms']}ms")
            print(f"Avg queue wait: {usage['timing']['avg_queue_wait_ms']}ms")
            print(f"Max queue wait: {usage['timing']['max_queue_wait_ms']}ms")

            assert usage["total_runs"] > 0
            assert usage["total_jobs"] > 0
            assert usage["timing"]["avg_job_duration_ms"] > 0

            # Per-workflow stats
            print("\nPer-workflow stats:")
            for wf_name, ws in usage["per_workflow"].items():
                print(f"  {wf_name}: {ws['total_runs']} runs, {ws['success_rate']}% success, avg {ws['avg_duration_ms']}ms")
            assert len(usage["per_workflow"]) > 0

            # Per-job stats
            print("\nPer-job stats (top 5):")
            for i, (jn, js) in enumerate(usage["per_job"].items()):
                if i >= 5:
                    break
                print(
                    f"  {jn}: {js['total_runs']} runs, {js['success_rate']}% success, avg {js['avg_duration_ms']}ms, queue {js['avg_queue_wait_ms']}ms"
                )

            # Slowest steps
            if usage["slowest_steps"]:
                print("\nSlowest steps (top 5):")
                for s in usage["slowest_steps"][:5]:
                    print(f"  {s['step']} ({s['job']}): {s['duration_ms']}ms")

            # Runner distribution should exist
            assert len(usage["runner_distribution"]) > 0

            # Verify logs (may or may not have failed runs)
            assert ctx.logs_json_path is not None

            # Verify we can generate a report from this data
            mock_result = AnalysisResult(
                executive_summary="Integration test summary",
                findings=[
                    {
                        "dimension": "efficiency",
                        "severity": "info",
                        "title": "Test",
                        "description": "Integration test",
                        "file": "ci.yml",
                        "suggestion": "N/A",
                    }
                ],
                stats={"total_findings": 1, "critical": 0, "major": 0, "minor": 0, "info": 1},
                duration_ms=1000,
            )
            md = format_markdown(mock_result, ctx)
            assert f"{OWNER}/{REPO}" in md

            js_output = format_json(mock_result, ctx)
            js_data = json.loads(js_output)
            assert js_data["repository"] == f"{OWNER}/{REPO}"
            assert "usage_stats" in js_data
            assert js_data["usage_stats"]["total_runs"] > 0

        finally:
            # Cleanup cloned repo
            if resolved.temp_dir:
                import shutil

                shutil.rmtree(resolved.temp_dir, ignore_errors=True)
            # Cleanup temp files
            for attr in ["runs_json_path", "jobs_json_path", "usage_stats_json_path", "logs_json_path", "workflows_json_path"]:
                p = getattr(ctx, attr, None) if "ctx" in dir() else None
                if p and p.exists():
                    p.unlink(missing_ok=True)
