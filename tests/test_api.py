"""Tests for FastAPI API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from ci_optimizer.api.app import app
from ci_optimizer.api.routes import get_db
from ci_optimizer.db.crud import complete_report, create_report, get_or_create_repo


@pytest.fixture
async def test_app(db_session):
    """Override the database dependency with test session."""

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


class TestDashboardEndpoint:
    @pytest.mark.asyncio
    async def test_empty_dashboard(self, client):
        resp = await client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_count"] == 0
        assert data["analysis_count"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_with_data(self, client, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello")
        report = await create_report(db_session, repo.id)
        await complete_report(
            db_session,
            report.id,
            summary_md="test",
            full_report_json="{}",
            findings_data=[
                {"dimension": "efficiency", "severity": "major", "title": "T", "description": "d"},
            ],
            duration_ms=100,
        )
        await db_session.commit()

        resp = await client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repo_count"] == 1
        assert data["analysis_count"] == 1


class TestReportsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_reports(self, client):
        resp = await client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_reports(self, client, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello")
        await create_report(db_session, repo.id)
        await create_report(db_session, repo.id)
        await db_session.commit()

        resp = await client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["reports"]) == 2

    @pytest.mark.asyncio
    async def test_list_reports_pagination(self, client, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello")
        for _ in range(5):
            await create_report(db_session, repo.id)
        await db_session.commit()

        resp = await client.get("/api/reports?page=1&limit=2")
        data = resp.json()
        assert len(data["reports"]) == 2
        assert data["total"] == 5

    @pytest.mark.asyncio
    async def test_list_reports_filter_by_repo(self, client, db_session):
        repo1 = await get_or_create_repo(db_session, "owner1", "repo1")
        repo2 = await get_or_create_repo(db_session, "owner2", "repo2")
        await create_report(db_session, repo1.id)
        await create_report(db_session, repo2.id)
        await db_session.commit()

        resp = await client.get("/api/reports?repo=owner1/repo1")
        data = resp.json()
        assert data["total"] == 1


class TestReportDetailEndpoint:
    @pytest.mark.asyncio
    async def test_not_found(self, client):
        resp = await client.get("/api/reports/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_report(self, client, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello")
        report = await create_report(db_session, repo.id)
        await complete_report(
            db_session,
            report.id,
            summary_md="# Summary",
            full_report_json='{"test": true}',
            findings_data=[
                {"dimension": "security", "severity": "critical", "title": "Issue", "description": "Bad"},
            ],
            duration_ms=2000,
        )
        await db_session.commit()

        resp = await client.get(f"/api/reports/{report.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["summary_md"] == "# Summary"
        assert data["duration_ms"] == 2000
        assert len(data["findings"]) == 1
        assert data["findings"][0]["severity"] == "critical"


class TestDashboardTrendsEndpoint:
    @pytest.mark.asyncio
    async def test_empty_trends(self, client):
        resp = await client.get("/api/dashboard/trends?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_scores"] == []
        assert data["dimension_trends"] == []
        assert data["repo_comparison"] == []

    @pytest.mark.asyncio
    async def test_trends_with_data(self, client, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello")
        report = await create_report(db_session, repo.id)
        await complete_report(
            db_session,
            report.id,
            summary_md="test",
            full_report_json="{}",
            findings_data=[
                {"dimension": "efficiency", "severity": "major", "title": "Slow", "description": "d"},
                {"dimension": "security", "severity": "critical", "title": "Vuln", "description": "d"},
                {"dimension": "security", "severity": "minor", "title": "Warn", "description": "d"},
            ],
            duration_ms=500,
        )
        await db_session.commit()

        resp = await client.get("/api/dashboard/trends?days=30")
        assert resp.status_code == 200
        data = resp.json()

        # Should have one day of data
        assert len(data["daily_scores"]) == 1
        day = data["daily_scores"][0]
        assert day["total"] == 3
        assert day["critical"] == 1
        assert day["major"] == 1
        assert day["minor"] == 1
        assert day["info"] == 0

        # Dimension trends
        assert len(data["dimension_trends"]) == 1
        dim = data["dimension_trends"][0]
        assert dim["efficiency"] == 1
        assert dim["security"] == 2

        # Repo comparison
        assert len(data["repo_comparison"]) == 1
        assert data["repo_comparison"][0]["repo"] == "octocat/hello"
        assert data["repo_comparison"][0]["total"] == 3

    @pytest.mark.asyncio
    async def test_trends_invalid_days_defaults_to_30(self, client):
        resp = await client.get("/api/dashboard/trends?days=15")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trends_valid_days(self, client):
        for d in [7, 30, 90]:
            resp = await client.get(f"/api/dashboard/trends?days={d}")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trends_repo_filter(self, client, db_session):
        repo1 = await get_or_create_repo(db_session, "owner1", "repo1")
        repo2 = await get_or_create_repo(db_session, "owner2", "repo2")

        r1 = await create_report(db_session, repo1.id)
        await complete_report(
            db_session, r1.id, "s", "{}",
            [{"dimension": "cost", "severity": "info", "title": "T", "description": "d"}],
            100,
        )
        r2 = await create_report(db_session, repo2.id)
        await complete_report(
            db_session, r2.id, "s", "{}",
            [{"dimension": "errors", "severity": "major", "title": "T", "description": "d"}],
            100,
        )
        await db_session.commit()

        # Filter to repo1 only
        resp = await client.get("/api/dashboard/trends?days=30&repo=owner1/repo1")
        data = resp.json()
        assert len(data["daily_scores"]) == 1
        assert data["daily_scores"][0]["total"] == 1
        # Repo comparison shows all repos (not filtered by subquery), but daily data is filtered
        # Dimension should only show cost
        assert data["dimension_trends"][0]["cost"] == 1
        assert data["dimension_trends"][0]["errors"] == 0

    @pytest.mark.asyncio
    async def test_trends_multiple_repos_comparison(self, client, db_session):
        repo1 = await get_or_create_repo(db_session, "org", "alpha")
        repo2 = await get_or_create_repo(db_session, "org", "beta")

        r1 = await create_report(db_session, repo1.id)
        await complete_report(
            db_session, r1.id, "s", "{}",
            [
                {"dimension": "security", "severity": "critical", "title": "T", "description": "d"},
                {"dimension": "security", "severity": "major", "title": "T", "description": "d"},
            ],
            100,
        )
        r2 = await create_report(db_session, repo2.id)
        await complete_report(
            db_session, r2.id, "s", "{}",
            [{"dimension": "cost", "severity": "info", "title": "T", "description": "d"}],
            100,
        )
        await db_session.commit()

        resp = await client.get("/api/dashboard/trends?days=30")
        data = resp.json()
        # repo_comparison sorted by total desc
        assert len(data["repo_comparison"]) == 2
        assert data["repo_comparison"][0]["repo"] == "org/alpha"
        assert data["repo_comparison"][0]["total"] == 2
        assert data["repo_comparison"][1]["repo"] == "org/beta"
        assert data["repo_comparison"][1]["total"] == 1


class TestRepositoriesEndpoint:
    @pytest.mark.asyncio
    async def test_empty(self, client):
        resp = await client.get("/api/repositories")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_repos(self, client, db_session):
        await get_or_create_repo(db_session, "owner1", "repo1")
        await get_or_create_repo(db_session, "owner2", "repo2")
        await db_session.commit()

        resp = await client.get("/api/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
