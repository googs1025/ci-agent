"""GitHub webhook handler for automated CI analysis."""

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ci_optimizer.api.routes import _run_analysis_task, get_db
from ci_optimizer.config import AgentConfig
from ci_optimizer.db.crud import create_report, get_or_create_repo

logger = logging.getLogger("ci_optimizer.webhook")

webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@webhook_router.get("/status")
async def webhook_status():
    """Return webhook configuration status and usage instructions."""
    secret = os.getenv("WEBHOOK_SECRET", "")
    base_url = os.getenv("CI_AGENT_BASE_URL", "http://localhost:8000")
    webhook_url = f"{base_url}/api/webhooks/github"

    return {
        "enabled": True,
        "secret_configured": bool(secret),
        "webhook_url": webhook_url,
        "supported_events": ["workflow_run"],
    }


def _verify_signature(payload: bytes, signature_header: str | None, secret: str) -> None:
    """Validate X-Hub-Signature-256 HMAC.

    Raises HTTPException 401 if the signature is missing or invalid.
    """
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Invalid signature format")

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")

    if not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@webhook_router.post("/github", status_code=202)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Handle GitHub webhook events.

    Supports:
    - ``workflow_run`` events (completed) → trigger analysis
    - Simple JSON payload with ``repo`` field (manual curl trigger)

    Validates HMAC signature when ``WEBHOOK_SECRET`` is set.
    Returns 202 Accepted immediately; analysis runs in background.
    """
    secret = os.getenv("WEBHOOK_SECRET", "")
    body = await request.body()

    # Validate HMAC if secret is configured
    if secret:
        sig = request.headers.get("X-Hub-Signature-256")
        _verify_signature(body, sig, secret)

    # Parse JSON payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = request.headers.get("X-GitHub-Event", "")

    # ── GitHub workflow_run event ──
    if event_type == "workflow_run":
        action = payload.get("action", "")
        if action != "completed":
            # Only analyze completed runs
            return {"status": "ignored", "reason": f"action={action}"}

        wf_run = payload.get("workflow_run", {})
        repo_data = payload.get("repository", {})
        full_name = repo_data.get("full_name", "")

        if not full_name:
            raise HTTPException(status_code=400, detail="Missing repository.full_name in payload")

        owner, repo_name = full_name.split("/", 1)
        repo_url = repo_data.get("html_url", f"https://github.com/{full_name}")

        logger.info(
            "Webhook received: workflow_run completed for %s (run_id=%s, branch=%s)",
            full_name,
            wf_run.get("id"),
            wf_run.get("head_branch"),
        )

    # ── Simple payload: {"repo": "owner/name"} (manual trigger) ──
    elif "repo" in payload:
        repo_input = payload["repo"]
        if "/" not in repo_input:
            raise HTTPException(status_code=400, detail="repo must be in 'owner/name' format")

        owner, repo_name = repo_input.split("/", 1)
        full_name = repo_input
        repo_url = f"https://github.com/{full_name}"

        logger.info("Webhook received: manual trigger for %s", full_name)

    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported payload: expected workflow_run event or {repo: 'owner/name'}",
        )

    # Create DB records and trigger background analysis
    db_repo = await get_or_create_repo(db, owner, repo_name, url=repo_url)
    report = await create_report(db, db_repo.id)
    await db.commit()

    config = AgentConfig.load()
    background_tasks.add_task(
        _run_analysis_task,
        report.id,
        full_name,
        None,  # no filters for webhook-triggered analysis
        config,
    )

    logger.info("Analysis queued: report_id=%d for %s", report.id, full_name)

    return {
        "status": "accepted",
        "report_id": report.id,
        "repo": full_name,
    }
