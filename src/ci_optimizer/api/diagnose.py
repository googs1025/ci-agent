"""Per-run CI failure diagnosis endpoint (issue #35, v1).

v1 replaces v0's in-memory cache with DB persistence:
- Exact cache lookup keyed on (repo_id, run_id, run_attempt, tier)
- Signature-based dedup: same normalized error within 24h reuses an existing diagnosis
- Daily budget tracker for webhook auto-diagnosis (manual calls always proceed)

v0 in-memory cache is removed. Frontend integration lands in v2 (#32).
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ci_optimizer.agents.failure_triage import FailureTriageError, diagnose
from ci_optimizer.api.routes import get_db
from ci_optimizer.api.schemas import (
    DiagnoseRequest,
    DiagnoseResponse,
    DiagnoseSiblingRun,
    FailedRunSummary,
    SignatureClusterResponse,
)
from ci_optimizer.config import AgentConfig
from ci_optimizer.db.crud import (
    find_cached_diagnosis,
    find_diagnosis_by_signature,
    get_or_create_repo,
    list_diagnoses_by_signature,
    save_diagnosis,
)
from ci_optimizer.db.models import FailureDiagnosis, Repository
from ci_optimizer.github_client import GitHubClient
from ci_optimizer.log_extractor import compute_signature, extract_error_excerpt

logger = logging.getLogger("ci_optimizer.diagnose")

diagnose_router = APIRouter(prefix="/api", tags=["diagnose"])

# Validates "owner/repo" format (shared with webhooks)
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _pick_failed_job(jobs: list[dict]) -> dict | None:
    """Return the first failed job from a list. v0/v1 handles one job per run."""
    for job in jobs:
        if job.get("conclusion") == "failure":
            return job
    return None


def _find_failing_step(job: dict) -> str | None:
    """Extract the name of the first failing step."""
    for step in job.get("steps", []) or []:
        if step.get("conclusion") == "failure":
            return step.get("name")
    return None


def _tier_to_model(tier: Literal["default", "deep"], config: AgentConfig) -> str:
    return config.diagnose_deep_model if tier == "deep" else config.diagnose_default_model


def _diag_to_response(
    diag: FailureDiagnosis,
    *,
    cached: bool,
) -> DiagnoseResponse:
    return DiagnoseResponse(
        category=diag.category,  # type: ignore[arg-type]
        confidence=diag.confidence,  # type: ignore[arg-type]
        root_cause=diag.root_cause,
        quick_fix=diag.quick_fix,
        failing_step=diag.failing_step,
        error_excerpt=diag.error_excerpt,
        error_signature=diag.error_signature,
        workflow=diag.workflow,
        model=diag.model,
        cost_usd=diag.cost_usd,
        cached=cached,
        source=diag.source,  # type: ignore[arg-type]
    )


async def run_diagnosis(
    db: AsyncSession,
    *,
    owner: str,
    repo_name: str,
    run_id: int,
    run_attempt: int,
    tier: Literal["default", "deep"],
    source: Literal["manual", "webhook_auto"],
    config: AgentConfig | None = None,
) -> DiagnoseResponse:
    """Core diagnosis flow — shared by manual API + webhook auto path.

    Cache order:
        1. Exact cache: same (repo, run, attempt, tier)
        2. Signature cache: same normalized error within TTL window
        3. Fresh diagnosis via LLM
    """
    config = config or AgentConfig.load()
    db_repo = await get_or_create_repo(db, owner, repo_name)
    await db.flush()

    # 1. Exact cache
    if existing := await find_cached_diagnosis(db, db_repo.id, run_id, run_attempt, tier):
        logger.info("diagnose: exact cache hit run=%d tier=%s", run_id, tier)
        return _diag_to_response(existing, cached=True)

    # 2. Fetch from GitHub
    gh = GitHubClient(config=config)
    try:
        try:
            jobs = await gh.get_run_jobs(owner, repo_name, run_id, filter="latest")
        except Exception as e:
            logger.warning("diagnose: failed to fetch jobs: %s", e)
            raise HTTPException(status_code=404, detail=f"Run not found or inaccessible: {e}") from e

        failing_job = _pick_failed_job(jobs)
        if failing_job is None:
            raise HTTPException(status_code=400, detail="Run has no failed jobs — nothing to diagnose")

        # Fetch the log of the specific failing job, not the whole-run ZIP,
        # so we don't mix output from unrelated passing jobs.
        log_text = await gh.get_job_log(owner, repo_name, failing_job["id"], max_lines=2000)
        if not log_text:
            # Fall back to whole-run log if per-job fetch fails (e.g., log expired)
            log_text = await gh.get_run_logs(owner, repo_name, run_id, max_lines=2000)
    finally:
        await gh.close()

    if not log_text:
        raise HTTPException(status_code=502, detail="Could not retrieve run logs from GitHub")

    failing_step = _find_failing_step(failing_job)
    excerpt, first_error_line = extract_error_excerpt(log_text, max_lines=200)
    signature = compute_signature(failing_step, first_error_line)
    workflow_name = failing_job.get("workflow_name") or "unknown"

    # 3. Signature cache — reuse diagnosis from an identical recent failure
    if sig_hit := await find_diagnosis_by_signature(db, signature, ttl_hours=config.diagnose_signature_ttl_hours):
        logger.info(
            "diagnose: signature cache hit sig=%s reusing diag=%d",
            signature,
            sig_hit.id,
        )
        # Persist a new record for this run pointing to the reused content
        # (so the exact-cache path hits next time).
        saved = await save_diagnosis(
            db,
            repo_id=db_repo.id,
            run_id=run_id,
            run_attempt=run_attempt,
            tier=tier,
            category=sig_hit.category,
            confidence=sig_hit.confidence,
            root_cause=sig_hit.root_cause,
            quick_fix=sig_hit.quick_fix,
            failing_step=failing_step,
            workflow=workflow_name,
            error_excerpt=excerpt,
            error_signature=signature,
            model=sig_hit.model,
            cost_usd=0.0,  # no new LLM call
            source=source,
        )
        await db.commit()
        return _diag_to_response(saved, cached=True)

    # 4. Fresh LLM call
    model = _tier_to_model(tier, config)
    try:
        diag = await diagnose(
            excerpt=excerpt,
            failing_step=failing_step,
            workflow=workflow_name,
            model=model,
            config=config,
        )
    except FailureTriageError as e:
        logger.error("diagnose: triage failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Diagnosis failed: {e}") from e
    except Exception as e:
        logger.exception("diagnose: unexpected error")
        raise HTTPException(status_code=502, detail=f"Diagnosis error: {e}") from e

    saved = await save_diagnosis(
        db,
        repo_id=db_repo.id,
        run_id=run_id,
        run_attempt=run_attempt,
        tier=tier,
        category=diag["category"],
        confidence=diag["confidence"],
        root_cause=diag["root_cause"],
        quick_fix=diag.get("quick_fix"),
        failing_step=failing_step,
        workflow=workflow_name,
        error_excerpt=excerpt,
        error_signature=signature,
        model=diag["model"],
        cost_usd=diag.get("cost_usd"),
        source=source,
    )
    await db.commit()
    return _diag_to_response(saved, cached=False)


@diagnose_router.post("/ci-runs/diagnose", response_model=DiagnoseResponse)
async def diagnose_run(
    req: DiagnoseRequest,
    db: AsyncSession = Depends(get_db),
) -> DiagnoseResponse:
    """Diagnose a single failed CI run.

    Returns 400 for malformed repo or run without failed jobs,
    404 if the run is inaccessible, 502 if the LLM or GitHub call fails.
    """
    if not _REPO_RE.match(req.repo):
        raise HTTPException(status_code=400, detail="repo must match 'owner/name'")

    owner, repo_name = req.repo.split("/", 1)
    return await run_diagnosis(
        db,
        owner=owner,
        repo_name=repo_name,
        run_id=req.run_id,
        run_attempt=req.run_attempt,
        tier=req.tier,
        source="manual",
    )


@diagnose_router.get(
    "/diagnoses/by-signature/{signature}",
    response_model=SignatureClusterResponse,
)
async def diagnoses_by_signature(
    signature: str,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> SignatureClusterResponse:
    """List all recent failures sharing the same error signature.

    Used to answer "how often has this exact failure happened lately?"
    """
    if len(signature) != 12 or any(c not in "0123456789abcdef" for c in signature):
        raise HTTPException(status_code=400, detail="signature must be 12 hex chars")

    diagnoses = await list_diagnoses_by_signature(db, signature, days=days)

    # Join repo info for display (small N so a lookup dict is fine)
    repo_ids = {d.repo_id for d in diagnoses}
    repos: dict[int, str] = {}
    if repo_ids:
        from sqlalchemy import select

        stmt = select(Repository).where(Repository.id.in_(repo_ids))
        result = await db.execute(stmt)
        for r in result.scalars().all():
            repos[r.id] = f"{r.owner}/{r.repo}"

    runs = [
        DiagnoseSiblingRun(
            repo=repos.get(d.repo_id, "unknown/unknown"),
            run_id=d.run_id,
            run_attempt=d.run_attempt,
            workflow=d.workflow,
            failing_step=d.failing_step,
            created_at=d.created_at,
        )
        for d in diagnoses
    ]

    # Category is whatever the most recent diagnosis says (they should all agree).
    category = diagnoses[0].category if diagnoses else None

    return SignatureClusterResponse(
        signature=signature,
        count=len(diagnoses),
        days=days,
        category=category,  # type: ignore[arg-type]
        runs=runs,
    )


def _parse_github_datetime(iso: str | None) -> object:
    """GitHub returns ISO-8601 strings with 'Z'; FastAPI will serialize datetimes."""
    if not iso:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


@diagnose_router.get(
    "/repos/{owner}/{repo_name}/failed-runs",
    response_model=list[FailedRunSummary],
)
async def list_failed_runs(
    owner: str,
    repo_name: str,
    limit: int = Query(default=20, ge=1, le=50),
) -> list[FailedRunSummary]:
    """List recent failed workflow runs for a repository.

    Queries GitHub directly (no DB persistence) so the picker works even
    on repos that have never been analyzed. Returns most recent first.
    """
    if not _REPO_RE.match(f"{owner}/{repo_name}"):
        raise HTTPException(status_code=400, detail="invalid owner/repo")

    config = AgentConfig.load()
    gh = GitHubClient(config=config)
    try:
        # GitHub's "status" filter doesn't support "failure" — we filter by
        # conclusion client-side after fetching recent completed runs.
        data = await gh._request(
            "GET",
            f"/repos/{owner}/{repo_name}/actions/runs",
            params={"status": "completed", "per_page": min(limit * 3, 100)},
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Repository not accessible: {e}") from e
    finally:
        await gh.close()

    all_runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    failed = [r for r in all_runs if r.get("conclusion") in ("failure", "timed_out", "startup_failure")][:limit]

    return [
        FailedRunSummary(
            run_id=r["id"],
            run_attempt=r.get("run_attempt", 1),
            workflow=r.get("name", "unknown"),
            branch=r.get("head_branch"),
            event=r.get("event"),
            created_at=_parse_github_datetime(r.get("created_at")),  # type: ignore[arg-type]
            html_url=r.get("html_url"),
            actor=(r.get("actor") or {}).get("login"),
        )
        for r in failed
    ]
