"""Unit tests for diagnosis CRUD (issue #35, v1)."""

from datetime import datetime, timedelta, timezone

from ci_optimizer.db.crud import (
    find_cached_diagnosis,
    find_diagnosis_by_signature,
    get_daily_diagnose_spend,
    list_diagnoses_by_signature,
    save_diagnosis,
)
from ci_optimizer.db.models import Repository


async def _mk_repo(db_session, owner="acme", repo="svc"):
    r = Repository(owner=owner, repo=repo)
    db_session.add(r)
    await db_session.flush()
    return r


class TestSaveDiagnosis:
    async def test_insert_new_diagnosis(self, db_session):
        repo = await _mk_repo(db_session)
        diag = await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=100,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="over 60m",
            quick_fix="timeout-minutes: 90",
            failing_step="e2e",
            workflow="ci",
            error_excerpt="...",
            error_signature="aaa000111222",
            model="claude-haiku-4-5-20251001",
            cost_usd=0.001,
        )
        assert diag.id is not None
        assert diag.source == "manual"

    async def test_upsert_updates_existing(self, db_session):
        repo = await _mk_repo(db_session)
        base = dict(
            repo_id=repo.id,
            run_id=100,
            run_attempt=1,
            tier="default",
            confidence="high",
            root_cause="first",
            quick_fix=None,
            failing_step="e2e",
            workflow="ci",
            error_excerpt="v1",
            error_signature="aaa000111222",
            model="claude-haiku-4-5-20251001",
            cost_usd=0.001,
        )
        d1 = await save_diagnosis(db_session, category="timeout", **base)
        d2 = await save_diagnosis(
            db_session,
            category="flaky_test",
            **{**base, "root_cause": "updated"},
        )
        assert d1.id == d2.id
        assert d2.category == "flaky_test"
        assert d2.root_cause == "updated"


class TestFindCachedDiagnosis:
    async def test_miss_returns_none(self, db_session):
        result = await find_cached_diagnosis(db_session, 1, 999, 1, "default")
        assert result is None

    async def test_matches_exact_key(self, db_session):
        repo = await _mk_repo(db_session)
        await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=42,
            run_attempt=2,
            tier="deep",
            category="network",
            confidence="medium",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="sig000000001",
            model="m",
            cost_usd=None,
        )
        hit = await find_cached_diagnosis(db_session, repo.id, 42, 2, "deep")
        assert hit is not None
        assert hit.category == "network"
        # Different tier → miss
        miss = await find_cached_diagnosis(db_session, repo.id, 42, 2, "default")
        assert miss is None
        # Different attempt → miss
        miss = await find_cached_diagnosis(db_session, repo.id, 42, 1, "deep")
        assert miss is None


class TestFindBySignature:
    async def test_signature_ttl_expires(self, db_session):
        repo = await _mk_repo(db_session)
        diag = await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=1,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="expiredsig01",
            model="m",
            cost_usd=0.001,
        )
        # Force the created_at into the past
        diag.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
        await db_session.flush()

        hit = await find_diagnosis_by_signature(db_session, "expiredsig01", ttl_hours=24)
        assert hit is None

        # Larger window matches
        hit = await find_diagnosis_by_signature(db_session, "expiredsig01", ttl_hours=72)
        assert hit is not None

    async def test_returns_most_recent(self, db_session):
        repo = await _mk_repo(db_session)
        older = await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=1,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="older",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="sharedsig123",
            model="m",
            cost_usd=0.001,
        )
        older.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await db_session.flush()

        await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=2,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="newer",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="sharedsig123",
            model="m",
            cost_usd=0.001,
        )
        hit = await find_diagnosis_by_signature(db_session, "sharedsig123")
        assert hit.root_cause == "newer"


class TestListBySignature:
    async def test_filters_by_days(self, db_session):
        repo = await _mk_repo(db_session)
        old = await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=1,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="listsigABCDE",
            model="m",
            cost_usd=0.001,
        )
        old.created_at = datetime.now(timezone.utc) - timedelta(days=45)
        await db_session.flush()

        await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=2,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="listsigABCDE",
            model="m",
            cost_usd=0.001,
        )

        # 30-day window: only the new one
        rows = await list_diagnoses_by_signature(db_session, "listsigABCDE", days=30)
        assert len(rows) == 1
        # 60-day window: both
        rows = await list_diagnoses_by_signature(db_session, "listsigABCDE", days=60)
        assert len(rows) == 2


class TestDailySpend:
    async def test_empty_returns_zero(self, db_session):
        assert await get_daily_diagnose_spend(db_session) == 0.0

    async def test_sums_recent_cost(self, db_session):
        repo = await _mk_repo(db_session)
        for i, cost in enumerate([0.01, 0.02, 0.03]):
            await save_diagnosis(
                db_session,
                repo_id=repo.id,
                run_id=100 + i,
                run_attempt=1,
                tier="default",
                category="timeout",
                confidence="high",
                root_cause="x",
                quick_fix=None,
                failing_step=None,
                workflow="ci",
                error_excerpt="x",
                error_signature=f"sig{i:010d}"[:12],
                model="m",
                cost_usd=cost,
            )
        spend = await get_daily_diagnose_spend(db_session)
        assert abs(spend - 0.06) < 1e-9

    async def test_excludes_old_records(self, db_session):
        repo = await _mk_repo(db_session)
        old = await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=1,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="oldsig000000",
            model="m",
            cost_usd=0.5,
        )
        old.created_at = datetime.now(timezone.utc) - timedelta(hours=30)
        await db_session.flush()
        assert await get_daily_diagnose_spend(db_session) == 0.0

    async def test_null_cost_treated_as_zero(self, db_session):
        repo = await _mk_repo(db_session)
        await save_diagnosis(
            db_session,
            repo_id=repo.id,
            run_id=1,
            run_attempt=1,
            tier="default",
            category="timeout",
            confidence="high",
            root_cause="x",
            quick_fix=None,
            failing_step=None,
            workflow="ci",
            error_excerpt="x",
            error_signature="nullcost0000",
            model="m",
            cost_usd=None,
        )
        spend = await get_daily_diagnose_spend(db_session)
        assert spend == 0.0
