"""Tests for database CRUD operations."""

import pytest

from ci_optimizer.db.crud import (
    complete_report,
    create_report,
    fail_report,
    get_dashboard_stats,
    get_or_create_repo,
    get_report,
    list_reports,
    list_repositories,
)


class TestGetOrCreateRepo:
    @pytest.mark.asyncio
    async def test_creates_new_repo(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        assert repo.id is not None
        assert repo.owner == "octocat"
        assert repo.repo == "hello-world"

    @pytest.mark.asyncio
    async def test_returns_existing_repo(self, db_session):
        repo1 = await get_or_create_repo(db_session, "octocat", "hello-world")
        repo2 = await get_or_create_repo(db_session, "octocat", "hello-world")
        assert repo1.id == repo2.id

    @pytest.mark.asyncio
    async def test_different_repos_different_ids(self, db_session):
        repo1 = await get_or_create_repo(db_session, "owner1", "repo1")
        repo2 = await get_or_create_repo(db_session, "owner2", "repo2")
        assert repo1.id != repo2.id


class TestCreateReport:
    @pytest.mark.asyncio
    async def test_creates_report(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        report = await create_report(db_session, repo.id)
        assert report.id is not None
        assert report.status == "running"
        assert report.repo_id == repo.id

    @pytest.mark.asyncio
    async def test_creates_report_with_filters(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        report = await create_report(db_session, repo.id, filters_json='{"branches": ["main"]}')
        assert report.filters_json == '{"branches": ["main"]}'


class TestCompleteReport:
    @pytest.mark.asyncio
    async def test_completes_report_with_findings(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        report = await create_report(db_session, repo.id)

        findings = [
            {
                "dimension": "efficiency",
                "severity": "major",
                "title": "Missing cache",
                "description": "No dependency caching configured",
                "file": ".github/workflows/ci.yml",
                "suggestion": "Add actions/cache step",
                "impact": "30% faster builds",
            },
            {
                "dimension": "security",
                "severity": "critical",
                "title": "Unpinned action",
                "description": "Using @main instead of SHA",
                "file": ".github/workflows/deploy.yml",
                "suggestion": "Pin to SHA",
            },
        ]

        completed = await complete_report(
            db_session,
            report.id,
            summary_md="# Summary\nTwo findings",
            full_report_json='{"findings": []}',
            findings_data=findings,
            duration_ms=5000,
        )

        assert completed.status == "completed"
        assert completed.duration_ms == 5000
        assert completed.summary_md == "# Summary\nTwo findings"

    @pytest.mark.asyncio
    async def test_updates_repo_last_analyzed(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        assert repo.last_analyzed_at is None

        report = await create_report(db_session, repo.id)
        await complete_report(
            db_session,
            report.id,
            summary_md="done",
            full_report_json="{}",
            findings_data=[],
            duration_ms=1000,
        )

        # Refresh repo
        from sqlalchemy import select

        from ci_optimizer.db.models import Repository

        result = await db_session.execute(select(Repository).where(Repository.id == repo.id))
        updated_repo = result.scalar_one()
        assert updated_repo.last_analyzed_at is not None


class TestFailReport:
    @pytest.mark.asyncio
    async def test_fails_report(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        report = await create_report(db_session, repo.id)

        await fail_report(db_session, report.id, "Something went wrong")

        fetched = await get_report(db_session, report.id)
        assert fetched.status == "failed"
        assert fetched.error_message == "Something went wrong"


class TestGetReport:
    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self, db_session):
        result = await get_report(db_session, 9999)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_report_with_findings(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        report = await create_report(db_session, repo.id)
        await complete_report(
            db_session,
            report.id,
            summary_md="test",
            full_report_json="{}",
            findings_data=[
                {"dimension": "efficiency", "severity": "minor", "title": "Test", "description": "desc"},
            ],
            duration_ms=100,
        )

        fetched = await get_report(db_session, report.id)
        assert fetched is not None
        assert len(fetched.findings) == 1
        assert fetched.findings[0].dimension == "efficiency"
        assert fetched.repository.owner == "octocat"


class TestListReports:
    @pytest.mark.asyncio
    async def test_empty_list(self, db_session):
        reports, total = await list_reports(db_session)
        assert reports == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_pagination(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        for _ in range(5):
            await create_report(db_session, repo.id)

        reports, total = await list_reports(db_session, page=1, limit=2)
        assert len(reports) == 2
        assert total == 5

        reports2, _ = await list_reports(db_session, page=2, limit=2)
        assert len(reports2) == 2

    @pytest.mark.asyncio
    async def test_filter_by_repo(self, db_session):
        repo1 = await get_or_create_repo(db_session, "owner1", "repo1")
        repo2 = await get_or_create_repo(db_session, "owner2", "repo2")
        await create_report(db_session, repo1.id)
        await create_report(db_session, repo1.id)
        await create_report(db_session, repo2.id)

        reports, total = await list_reports(db_session, "owner1", "repo1")
        assert total == 2


class TestListRepositories:
    @pytest.mark.asyncio
    async def test_empty(self, db_session):
        repos = await list_repositories(db_session)
        assert repos == []

    @pytest.mark.asyncio
    async def test_returns_repos(self, db_session):
        await get_or_create_repo(db_session, "owner1", "repo1")
        await get_or_create_repo(db_session, "owner2", "repo2")

        repos = await list_repositories(db_session)
        assert len(repos) == 2


class TestGetDashboardStats:
    @pytest.mark.asyncio
    async def test_empty_stats(self, db_session):
        stats = await get_dashboard_stats(db_session)
        assert stats["repo_count"] == 0
        assert stats["analysis_count"] == 0
        assert stats["recent_reports"] == []

    @pytest.mark.asyncio
    async def test_with_data(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        report = await create_report(db_session, repo.id)
        await complete_report(
            db_session,
            report.id,
            summary_md="test",
            full_report_json="{}",
            findings_data=[
                {"dimension": "efficiency", "severity": "major", "title": "A", "description": "a"},
                {"dimension": "security", "severity": "critical", "title": "B", "description": "b"},
            ],
            duration_ms=100,
        )

        stats = await get_dashboard_stats(db_session)
        assert stats["repo_count"] == 1
        assert stats["analysis_count"] == 1
        assert stats["severity_distribution"]["major"] == 1
        assert stats["severity_distribution"]["critical"] == 1
        assert stats["dimension_distribution"]["efficiency"] == 1
        assert stats["dimension_distribution"]["security"] == 1
        assert len(stats["recent_reports"]) == 1
