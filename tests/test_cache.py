"""Tests for analysis result caching."""

from datetime import datetime, timedelta, timezone

import pytest

from ci_optimizer.db.crud import (
    complete_report,
    compute_filters_hash,
    create_report,
    find_cached_report,
    get_or_create_repo,
)


class TestComputeFiltersHash:
    def test_consistent_output(self):
        h1 = compute_filters_hash('{"branches": ["main"]}')
        h2 = compute_filters_hash('{"branches": ["main"]}')
        assert h1 == h2

    def test_different_for_different_filters(self):
        h1 = compute_filters_hash('{"branches": ["main"]}')
        h2 = compute_filters_hash('{"branches": ["dev"]}')
        assert h1 != h2

    def test_none_treated_as_empty(self):
        h1 = compute_filters_hash(None)
        h2 = compute_filters_hash("")
        assert h1 == h2

    def test_returns_short_hex(self):
        h = compute_filters_hash("anything")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)


class TestFindCachedReport:
    @pytest.mark.asyncio
    async def test_returns_cached_completed_report(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        fhash = compute_filters_hash(None)

        report = await create_report(db_session, repo.id, filters_hash=fhash)
        await complete_report(
            db_session,
            report.id,
            summary_md="cached",
            full_report_json="{}",
            findings_data=[],
            duration_ms=100,
        )

        cached = await find_cached_report(db_session, repo.id, fhash, ttl_hours=24)
        assert cached is not None
        assert cached.id == report.id

    @pytest.mark.asyncio
    async def test_returns_none_for_expired(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        fhash = compute_filters_hash(None)

        report = await create_report(db_session, repo.id, filters_hash=fhash)
        await complete_report(
            db_session,
            report.id,
            summary_md="old",
            full_report_json="{}",
            findings_data=[],
            duration_ms=100,
        )

        # Manually backdate created_at beyond the TTL
        report.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        cached = await find_cached_report(db_session, repo.id, fhash, ttl_hours=24)
        assert cached is None

    @pytest.mark.asyncio
    async def test_returns_none_for_running_report(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        fhash = compute_filters_hash(None)

        # Report exists but is still running (not completed)
        await create_report(db_session, repo.id, filters_hash=fhash)

        cached = await find_cached_report(db_session, repo.id, fhash, ttl_hours=24)
        assert cached is None

    @pytest.mark.asyncio
    async def test_returns_none_for_different_hash(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        fhash = compute_filters_hash('{"branches": ["main"]}')

        report = await create_report(db_session, repo.id, filters_hash=fhash)
        await complete_report(
            db_session,
            report.id,
            summary_md="done",
            full_report_json="{}",
            findings_data=[],
            duration_ms=100,
        )

        other_hash = compute_filters_hash('{"branches": ["dev"]}')
        cached = await find_cached_report(db_session, repo.id, other_hash, ttl_hours=24)
        assert cached is None

    @pytest.mark.asyncio
    async def test_returns_most_recent(self, db_session):
        repo = await get_or_create_repo(db_session, "octocat", "hello-world")
        fhash = compute_filters_hash(None)

        # Create two completed reports with same hash
        r1 = await create_report(db_session, repo.id, filters_hash=fhash)
        await complete_report(db_session, r1.id, "old", "{}", [], 100)

        r2 = await create_report(db_session, repo.id, filters_hash=fhash)
        await complete_report(db_session, r2.id, "new", "{}", [], 200)

        cached = await find_cached_report(db_session, repo.id, fhash, ttl_hours=24)
        assert cached is not None
        assert cached.id == r2.id
