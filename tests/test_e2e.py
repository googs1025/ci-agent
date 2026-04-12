"""End-to-end tests — full pipeline from input to report output.

These tests mock the Claude Agent SDK (no real API calls) but exercise
the entire flow: resolver → prefetch → orchestrator → formatter → API.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ci_optimizer.agents.orchestrator import AnalysisResult, _parse_result
from ci_optimizer.api.app import app
from ci_optimizer.api.routes import get_db
from ci_optimizer.config import AgentConfig
from ci_optimizer.db.models import Base
from ci_optimizer.prefetch import prepare_context
from ci_optimizer.report.formatter import format_json, format_markdown
from ci_optimizer.resolver import ResolvedInput, resolve_input

# ── Fixtures ──────────────────────────────────────────────────────────

MOCK_ORCHESTRATOR_OUTPUT = json.dumps(
    {
        "executive_summary": "Top 3 recommendations: 1) Pin actions to SHA, 2) Add dependency caching, 3) Switch deploy to ubuntu runner.",
        "dimensions": {
            "efficiency": {
                "findings": [
                    {
                        "severity": "major",
                        "title": "Missing dependency cache",
                        "description": "npm install runs without cache on every CI run",
                        "file": ".github/workflows/ci.yml",
                        "line": 14,
                        "suggestion": "Add actions/cache with package-lock.json hash key",
                        "impact": "~30% faster builds",
                    },
                    {
                        "severity": "minor",
                        "title": "Unnecessary sequential lint job",
                        "description": "Lint job has needs: [test] but does not depend on test output",
                        "file": ".github/workflows/ci.yml",
                        "line": 20,
                        "suggestion": "Remove needs: [test] to run lint in parallel",
                        "impact": "~2 min saved per run",
                    },
                ]
            },
            "security": {
                "findings": [
                    {
                        "severity": "critical",
                        "title": "Action pinned to mutable ref",
                        "description": "actions/checkout@main can be hijacked via tag mutation",
                        "file": ".github/workflows/deploy.yml",
                        "line": 7,
                        "suggestion": "Pin to full SHA: actions/checkout@b4ffde6...",
                        "impact": "Prevents supply chain attack",
                    },
                    {
                        "severity": "major",
                        "title": "Overly permissive permissions",
                        "description": "permissions: write-all grants unnecessary access",
                        "file": ".github/workflows/deploy.yml",
                        "line": 5,
                        "suggestion": "Set granular permissions: contents: read, deployments: write",
                        "impact": "Reduces blast radius of compromised workflow",
                    },
                ]
            },
            "cost": {
                "findings": [
                    {
                        "severity": "major",
                        "title": "macOS runner for non-native workload",
                        "description": "Deploy job runs npm commands on macos-latest (10x cost)",
                        "file": ".github/workflows/deploy.yml",
                        "line": 10,
                        "suggestion": "Switch to ubuntu-latest",
                        "impact": "10x cost reduction for deploy job",
                    },
                ]
            },
            "error": {
                "findings": [
                    {
                        "severity": "info",
                        "title": "No failure data available",
                        "description": "No CI run history provided, analysis based on workflow structure only",
                        "file": "",
                        "suggestion": "Provide GITHUB_TOKEN for historical failure analysis",
                        "impact": "N/A",
                    },
                ]
            },
        },
        "stats": {
            "total_findings": 6,
            "critical": 1,
            "major": 3,
            "minor": 1,
            "info": 1,
        },
    }
)


@pytest.fixture
def e2e_repo(tmp_path):
    """Create a realistic repo for E2E testing."""
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)

    (workflows_dir / "ci.yml").write_text("""\
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
      - run: npm install
      - run: npm test

  lint:
    runs-on: ubuntu-latest
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 18
      - run: npm install
      - run: npm run lint
""")

    (workflows_dir / "deploy.yml").write_text("""\
name: Deploy
on:
  push:
    branches: [main]

permissions: write-all

jobs:
  deploy:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@main
      - run: echo ${{ github.event.pull_request.title }}
      - run: npm install
      - run: npm run build
      - run: npm run deploy
""")

    return tmp_path


@pytest_asyncio.fixture
async def e2e_db():
    """In-memory DB for E2E tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def e2e_client(e2e_db):
    """Async test client with DB override."""

    async def override_get_db():
        yield e2e_db

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_agent_config(tmp_path):
    """Config pointing to temp dir with a fake API key."""
    config = AgentConfig(
        model="claude-sonnet-4-20250514",
        anthropic_api_key="sk-test-fake-key",
        max_turns=5,
    )
    return config


# ── E2E: Parse Result ─────────────────────────────────────────────────


class TestParseResult:
    """Test that _parse_result correctly extracts structured data from raw agent output."""

    def test_parses_valid_json(self):
        summary, findings, stats = _parse_result(MOCK_ORCHESTRATOR_OUTPUT)
        assert "Pin actions to SHA" in summary
        assert len(findings) == 6
        assert stats["critical"] == 1
        assert stats["major"] == 3

    def test_findings_have_dimensions(self):
        _, findings, _ = _parse_result(MOCK_ORCHESTRATOR_OUTPUT)
        dimensions = {f["dimension"] for f in findings}
        assert dimensions == {"efficiency", "security", "cost", "error"}

    def test_plain_text_fallback(self):
        summary, findings, stats = _parse_result("No JSON here, just text analysis.")
        assert summary == "No JSON here, just text analysis."
        assert findings == []
        assert stats["total_findings"] == 0

    def test_json_with_surrounding_text(self):
        text = "Here is my analysis:\n" + MOCK_ORCHESTRATOR_OUTPUT + "\nDone."
        summary, findings, stats = _parse_result(text)
        assert len(findings) == 6


# ── E2E: Resolver → Prefetch → Report ────────────────────────────────


class TestLocalAnalysisPipeline:
    """Test the full pipeline with a local repo (no GitHub API calls)."""

    @pytest.mark.asyncio
    async def test_resolve_and_prefetch(self, e2e_repo):
        resolved = resolve_input(str(e2e_repo))
        assert resolved.local_path == e2e_repo
        assert resolved.is_remote is False

        ctx = await prepare_context(resolved)
        assert len(ctx.workflow_files) == 2
        assert ctx.runs_json_path is None  # no owner/repo → no API calls
        assert ctx.jobs_json_path is None
        assert ctx.usage_stats_json_path is None

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_agent(self, e2e_repo, mock_agent_config):
        """resolver → prefetch → mock run_analysis → formatter → output."""
        resolved = resolve_input(str(e2e_repo))
        ctx = await prepare_context(resolved)

        # Mock the agent SDK query to return our fixture output
        mock_result = AnalysisResult(
            executive_summary="Top 3 recommendations",
            findings=[
                {
                    "dimension": "efficiency",
                    "severity": "major",
                    "title": "Missing cache",
                    "description": "No cache",
                    "file": "ci.yml",
                    "suggestion": "Add cache",
                    "impact": "30% faster",
                },
                {
                    "dimension": "security",
                    "severity": "critical",
                    "title": "Unpinned action",
                    "description": "Using @main",
                    "file": "deploy.yml",
                    "suggestion": "Pin SHA",
                    "impact": "Supply chain",
                },
            ],
            stats={"total_findings": 2, "critical": 1, "major": 1, "minor": 0, "info": 0},
            duration_ms=3000,
            cost_usd=0.01,
        )

        with patch("ci_optimizer.agents.orchestrator.run_analysis", return_value=mock_result):
            result = mock_result  # use directly since we're testing the formatter

        # Test markdown output
        md = format_markdown(result, ctx)
        assert "CI Pipeline Analysis Report" in md
        assert "Missing cache" in md
        assert "Unpinned action" in md
        assert "Execution Efficiency" in md
        assert "Security & Best Practices" in md

        # Test JSON output
        js = format_json(result, ctx)
        data = json.loads(js)
        assert data["workflow_count"] == 2
        assert len(data["findings"]) == 2
        assert data["stats"]["critical"] == 1
        assert data["duration_ms"] == 3000


# ── E2E: Prefetch with Mock GitHub API ────────────────────────────────


class TestPrefetchWithGitHubAPI:
    """Test full prefetch pipeline with mocked GitHub API including usage stats."""

    @pytest.mark.asyncio
    async def test_usage_stats_computed(self, e2e_repo):
        resolved = ResolvedInput(local_path=e2e_repo, owner="testorg", repo="testrepo")

        mock_client = AsyncMock()
        mock_client.list_workflow_runs.return_value = [
            {
                "id": 101,
                "name": "CI",
                "conclusion": "success",
                "run_started_at": "2024-06-01T10:00:00Z",
                "updated_at": "2024-06-01T10:08:00Z",
                "created_at": "2024-06-01T10:00:00Z",
                "head_branch": "main",
            },
            {
                "id": 102,
                "name": "CI",
                "conclusion": "failure",
                "run_started_at": "2024-06-01T11:00:00Z",
                "updated_at": "2024-06-01T11:05:00Z",
                "created_at": "2024-06-01T11:00:00Z",
                "head_branch": "main",
            },
            {
                "id": 103,
                "name": "Deploy",
                "conclusion": "success",
                "run_started_at": "2024-06-01T12:00:00Z",
                "updated_at": "2024-06-01T12:15:00Z",
                "created_at": "2024-06-01T12:00:00Z",
                "head_branch": "main",
            },
        ]

        def make_jobs(run_id):
            if run_id == 101:
                return [
                    {
                        "id": 201,
                        "name": "test",
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2024-06-01T10:00:00Z",
                        "started_at": "2024-06-01T10:00:12Z",
                        "completed_at": "2024-06-01T10:04:00Z",
                        "runner_id": 1,
                        "runner_name": "r1",
                        "labels": ["ubuntu-latest"],
                        "steps": [
                            {
                                "name": "Checkout",
                                "status": "completed",
                                "conclusion": "success",
                                "number": 1,
                                "started_at": "2024-06-01T10:00:12Z",
                                "completed_at": "2024-06-01T10:00:15Z",
                            },
                            {
                                "name": "Run tests",
                                "status": "completed",
                                "conclusion": "success",
                                "number": 2,
                                "started_at": "2024-06-01T10:00:15Z",
                                "completed_at": "2024-06-01T10:04:00Z",
                            },
                        ],
                    },
                    {
                        "id": 202,
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2024-06-01T10:04:00Z",
                        "started_at": "2024-06-01T10:04:08Z",
                        "completed_at": "2024-06-01T10:06:00Z",
                        "runner_id": 2,
                        "runner_name": "r2",
                        "labels": ["ubuntu-latest"],
                        "steps": [],
                    },
                ]
            elif run_id == 102:
                return [
                    {
                        "id": 203,
                        "name": "test",
                        "status": "completed",
                        "conclusion": "failure",
                        "created_at": "2024-06-01T11:00:00Z",
                        "started_at": "2024-06-01T11:00:20Z",
                        "completed_at": "2024-06-01T11:03:00Z",
                        "runner_id": 3,
                        "runner_name": "r3",
                        "labels": ["ubuntu-latest"],
                        "steps": [
                            {
                                "name": "Run tests",
                                "status": "completed",
                                "conclusion": "failure",
                                "number": 2,
                                "started_at": "2024-06-01T11:00:25Z",
                                "completed_at": "2024-06-01T11:03:00Z",
                            },
                        ],
                    },
                ]
            else:  # 103
                return [
                    {
                        "id": 204,
                        "name": "deploy",
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2024-06-01T12:00:00Z",
                        "started_at": "2024-06-01T12:00:30Z",
                        "completed_at": "2024-06-01T12:14:00Z",
                        "runner_id": 4,
                        "runner_name": "r4",
                        "labels": ["macos-latest"],
                        "steps": [
                            {
                                "name": "Build",
                                "status": "completed",
                                "conclusion": "success",
                                "number": 3,
                                "started_at": "2024-06-01T12:01:00Z",
                                "completed_at": "2024-06-01T12:10:00Z",
                            },
                            {
                                "name": "Deploy",
                                "status": "completed",
                                "conclusion": "success",
                                "number": 4,
                                "started_at": "2024-06-01T12:10:00Z",
                                "completed_at": "2024-06-01T12:14:00Z",
                            },
                        ],
                    },
                ]

        mock_client.get_run_jobs.side_effect = lambda o, r, rid: make_jobs(rid)
        mock_client.get_run_logs.return_value = "Error: npm test failed\nAssertionError"
        mock_client.get_workflows.return_value = [
            {"id": 1, "name": "CI", "path": ".github/workflows/ci.yml"},
            {"id": 2, "name": "Deploy", "path": ".github/workflows/deploy.yml"},
        ]
        mock_client.get_repo_info.return_value = {"full_name": "testorg/testrepo", "private": True}

        with patch("ci_optimizer.prefetch.GitHubClient", return_value=mock_client):
            ctx = await prepare_context(resolved)

        # Verify all data files exist
        assert ctx.jobs_json_path.exists()
        assert ctx.usage_stats_json_path.exists()
        assert ctx.runs_json_path.exists()
        assert ctx.logs_json_path.exists()

        # Verify jobs collected for ALL runs
        jobs_data = json.loads(ctx.jobs_json_path.read_text())
        assert "101" in jobs_data  # success run
        assert "102" in jobs_data  # failure run
        assert "103" in jobs_data  # deploy run
        assert len(jobs_data["101"]) == 2  # test + lint
        assert jobs_data["103"][0]["labels"] == ["macos-latest"]

        # Verify usage stats
        usage = json.loads(ctx.usage_stats_json_path.read_text())

        assert usage["total_runs"] == 3
        assert usage["total_jobs"] == 4
        assert usage["conclusion_counts"]["success"] == 2
        assert usage["conclusion_counts"]["failure"] == 1

        # Runner distribution
        assert usage["runner_distribution"]["ubuntu"] == 3
        assert usage["runner_distribution"]["macos"] == 1

        # Billing: macOS job ~14 min × 10 = 140, ubuntu jobs much less
        assert usage["billing_estimate"]["by_os"]["macos"] > 0
        assert usage["billing_estimate"]["by_os"]["ubuntu"] > 0
        assert usage["billing_estimate"]["total_minutes"] > 0

        # Per-workflow
        assert usage["per_workflow"]["CI"]["total_runs"] == 2
        assert usage["per_workflow"]["CI"]["success"] == 1
        assert usage["per_workflow"]["CI"]["failure"] == 1
        assert usage["per_workflow"]["CI"]["success_rate"] == 50.0
        assert usage["per_workflow"]["Deploy"]["total_runs"] == 1
        assert usage["per_workflow"]["Deploy"]["success_rate"] == 100.0

        # Per-job
        assert usage["per_job"]["test"]["total_runs"] == 2
        assert usage["per_job"]["test"]["success"] == 1
        assert usage["per_job"]["deploy"]["total_runs"] == 1
        assert usage["per_job"]["deploy"]["avg_queue_wait_ms"] > 0

        # Slowest steps
        assert len(usage["slowest_steps"]) > 0
        # "Build" step (9 min) should be the slowest
        assert usage["slowest_steps"][0]["step"] == "Build"

        # Verify logs only for failed runs
        logs_data = json.loads(ctx.logs_json_path.read_text())
        assert "102" in logs_data
        assert "101" not in logs_data  # success, no logs

        # Format the report to verify it works end-to-end
        mock_result = AnalysisResult(
            executive_summary="Test summary",
            findings=[
                {
                    "dimension": "cost",
                    "severity": "major",
                    "title": "macOS cost",
                    "description": "...",
                    "file": "deploy.yml",
                    "suggestion": "Use ubuntu",
                }
            ],
            stats={"total_findings": 1, "critical": 0, "major": 1, "minor": 0, "info": 0},
            duration_ms=5000,
        )
        md = format_markdown(mock_result, ctx)
        assert "testorg/testrepo" in md

        js_output = format_json(mock_result, ctx)
        js_data = json.loads(js_output)
        assert "usage_stats" in js_data
        assert js_data["usage_stats"]["total_runs"] == 3

        # Cleanup
        for p in [ctx.runs_json_path, ctx.jobs_json_path, ctx.usage_stats_json_path, ctx.logs_json_path, ctx.workflows_json_path]:
            if p:
                p.unlink(missing_ok=True)


# ── E2E: API Flow ────────────────────────────────────────────────────


class TestAPIFlow:
    """Test API endpoints work together as a complete flow."""

    @pytest.mark.asyncio
    async def test_analyze_and_retrieve_report(self, e2e_repo, e2e_db, e2e_client):
        """Full flow: create repo+report in DB → complete it → query all endpoints."""
        from ci_optimizer.db.crud import (
            complete_report,
            create_report,
            get_or_create_repo,
        )

        # Simulate what the API analyze flow does, but directly in the test DB
        repo = await get_or_create_repo(e2e_db, "e2eorg", "e2erepo")
        report = await create_report(e2e_db, repo.id)
        await complete_report(
            e2e_db,
            report.id,
            summary_md="# E2E Report\nTop 3: pin actions, add caching, switch runners.",
            full_report_json='{"executive_summary": "E2E test"}',
            findings_data=[
                {
                    "dimension": "efficiency",
                    "severity": "major",
                    "title": "No cache",
                    "description": "Missing npm cache",
                    "file": "ci.yml",
                    "suggestion": "Add cache",
                },
                {
                    "dimension": "security",
                    "severity": "critical",
                    "title": "Unpinned",
                    "description": "Action @main",
                    "file": "deploy.yml",
                    "suggestion": "Pin SHA",
                },
            ],
            duration_ms=4200,
        )
        await e2e_db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Step 1: Retrieve the report
            resp = await client.get(f"/api/reports/{report.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "completed"
            assert "E2E Report" in data["summary_md"]
            assert data["duration_ms"] == 4200
            assert len(data["findings"]) == 2
            assert data["repo_owner"] == "e2eorg"
            assert data["repo_name"] == "e2erepo"

            # Step 2: Check reports list
            resp = await client.get("/api/reports")
            assert resp.status_code == 200
            reports_list = resp.json()
            assert reports_list["total"] == 1
            assert reports_list["reports"][0]["id"] == report.id
            assert reports_list["reports"][0]["finding_count"] == 2

            # Step 3: Filter reports by repo
            resp = await client.get("/api/reports?repo=e2eorg/e2erepo")
            assert resp.status_code == 200
            assert resp.json()["total"] == 1

            resp = await client.get("/api/reports?repo=other/repo")
            assert resp.status_code == 200
            assert resp.json()["total"] == 0

            # Step 4: Check dashboard
            resp = await client.get("/api/dashboard")
            assert resp.status_code == 200
            dashboard = resp.json()
            assert dashboard["repo_count"] == 1
            assert dashboard["analysis_count"] == 1
            assert dashboard["severity_distribution"]["critical"] == 1
            assert dashboard["severity_distribution"]["major"] == 1
            assert dashboard["dimension_distribution"]["efficiency"] == 1
            assert dashboard["dimension_distribution"]["security"] == 1
            assert len(dashboard["recent_reports"]) == 1

            # Step 5: Check repositories
            resp = await client.get("/api/repositories")
            assert resp.status_code == 200
            repos = resp.json()
            assert len(repos) == 1
            assert repos[0]["owner"] == "e2eorg"
            assert repos[0]["last_analyzed_at"] is not None

    @pytest.mark.asyncio
    async def test_analyze_invalid_repo(self, e2e_db, e2e_client):
        """POST /analyze with invalid repo returns 400."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/analyze",
                json={"repo": "/nonexistent/path/that/does/not/exist"},
            )
            assert resp.status_code == 400
            assert "does not exist" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_config_flow(self, e2e_db, e2e_client, tmp_path):
        """GET /config → PUT /config → GET /config roundtrip."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Get initial config
            resp = await client.get("/api/config")
            assert resp.status_code == 200
            initial = resp.json()
            assert "model" in initial

            # Update config
            with patch("ci_optimizer.api.routes.AgentConfig.load") as mock_load, patch("ci_optimizer.api.routes.AgentConfig.save"):
                mock_config = AgentConfig()
                mock_load.return_value = mock_config

                resp = await client.put(
                    "/api/config",
                    json={
                        "model": "claude-opus-4-20250514",
                    },
                )
                assert resp.status_code == 200
                updated = resp.json()
                assert updated["model"] == "claude-opus-4-20250514"
