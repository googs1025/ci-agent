"""Per-run CI failure diagnosis endpoint (issue #35, v0).

POST /api/ci-runs/diagnose
    Fetch a single failed run from GitHub, extract the error excerpt,
    invoke the failure-triage skill, and return a structured diagnosis.

v0 uses an in-memory cache keyed on (repo, run_id, tier). v1 replaces this
with DB-backed persistence once the `failure_diagnoses` table lands (#36).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Literal

from fastapi import APIRouter, HTTPException

from ci_optimizer.agents.failure_triage import FailureTriageError, diagnose
from ci_optimizer.api.schemas import DiagnoseRequest, DiagnoseResponse
from ci_optimizer.config import AgentConfig
from ci_optimizer.github_client import GitHubClient
from ci_optimizer.log_extractor import compute_signature, extract_error_excerpt

logger = logging.getLogger("ci_optimizer.diagnose")

diagnose_router = APIRouter(prefix="/api/ci-runs", tags=["diagnose"])

# ── in-memory cache (v0) ─────────────────────────────────────────────────────
# Replaced by DB-backed cache in v1. Keyed by (repo, run_id, tier).
_CACHE: dict[tuple[str, int, str], tuple[DiagnoseResponse, float]] = {}
_CACHE_TTL_SEC = 300  # 5 min

# Validates "owner/repo" format
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def _cache_get(key: tuple[str, int, str]) -> DiagnoseResponse | None:
    entry = _CACHE.get(key)
    if entry is None:
        return None
    response, expires_at = entry
    if time.time() > expires_at:
        _CACHE.pop(key, None)
        return None
    return response


def _cache_set(key: tuple[str, int, str], value: DiagnoseResponse) -> None:
    _CACHE[key] = (value, time.time() + _CACHE_TTL_SEC)


def _pick_failed_job(jobs: list[dict]) -> dict | None:
    """Return the first failed job from a list. v0 handles one job per run."""
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
    if tier == "deep":
        return config.diagnose_deep_model
    return config.diagnose_default_model


@diagnose_router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose_run(req: DiagnoseRequest) -> DiagnoseResponse:
    """Diagnose a single failed CI run.

    Returns 400 if the run has no failed jobs, 404 if the run doesn't exist,
    502 if the LLM call fails.
    """
    if not _REPO_RE.match(req.repo):
        raise HTTPException(status_code=400, detail="repo must match 'owner/name'")

    tier: Literal["default", "deep"] = req.tier
    cache_key = (req.repo, req.run_id, tier)

    if cached := _cache_get(cache_key):
        logger.info("diagnose: cache hit for %s run=%d tier=%s", req.repo, req.run_id, tier)
        return cached.model_copy(update={"cached": True})

    config = AgentConfig.load()
    owner, name = req.repo.split("/", 1)
    gh = GitHubClient(config=config)

    try:
        jobs = await gh.get_run_jobs(owner, name, req.run_id, filter="latest")
    except Exception as e:
        logger.warning("diagnose: failed to fetch jobs: %s", e)
        await gh.close()
        raise HTTPException(status_code=404, detail=f"Run not found or inaccessible: {e}") from e

    failing_job = _pick_failed_job(jobs)
    if failing_job is None:
        await gh.close()
        raise HTTPException(
            status_code=400,
            detail="Run has no failed jobs — nothing to diagnose",
        )

    # Fetch the full-run log zip (GitHub doesn't offer per-job logs via REST).
    log_text = await gh.get_run_logs(owner, name, req.run_id, max_lines=2000)
    await gh.close()

    if not log_text:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve run logs from GitHub",
        )

    failing_step = _find_failing_step(failing_job)
    excerpt, first_error_line = extract_error_excerpt(log_text, max_lines=200)
    signature = compute_signature(failing_step, first_error_line)

    workflow_name = failing_job.get("workflow_name") or "unknown"
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

    response = DiagnoseResponse(
        category=diag["category"],
        confidence=diag["confidence"],
        root_cause=diag["root_cause"],
        quick_fix=diag.get("quick_fix"),
        failing_step=failing_step,
        error_excerpt=excerpt,
        error_signature=signature,
        workflow=workflow_name,
        model=diag["model"],
        cost_usd=diag.get("cost_usd"),
        cached=False,
    )
    _cache_set(cache_key, response)
    return response
