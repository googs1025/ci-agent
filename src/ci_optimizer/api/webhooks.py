"""GitHub webhook handler for automated CI analysis."""
# ── 架构角色 ──────────────────────────────────────────────────────────────────
# 本文件处理来自 GitHub 的 webhook 事件，是 CI Agent 的被动触发入口。
# 主要职责：
#   - 验证 X-Hub-Signature-256 HMAC 签名（WEBHOOK_SECRET 配置后强制校验）
#   - 处理 workflow_run completed 事件：创建 DB 记录并在后台启动全量分析
#   - 对失败的 workflow_run，按"开关 + 采样率 + 每日预算"三道门控决定是否触发自动诊断
#   - 支持简单 {"repo": "owner/name"} 格式的手动 curl 触发
# 所有耗时操作（分析、诊断）均推入 BackgroundTasks，接口本身立即返回 202。

import hashlib
import hmac
import logging
import os
import random

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ci_optimizer.api.routes import _run_analysis_task, get_db
from ci_optimizer.config import AgentConfig
from ci_optimizer.db.crud import (
    create_report,
    get_daily_diagnose_spend,
    get_or_create_repo,
)
from ci_optimizer.db.database import async_session

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


async def _run_auto_diagnosis_task(
    owner: str,
    repo_name: str,
    run_id: int,
    run_attempt: int,
    config: AgentConfig,
) -> None:
    """Background task: diagnose a failed webhook run.

    Runs in its own session so we don't tie up the webhook request's session
    past the 202 response. Swallows errors so a failing diagnosis never
    poisons the surrounding analysis pipeline.
    使用独立的 async_session，防止 webhook 请求 session 在 202 返回后被复用；
    吞掉所有异常（仅 warning 日志），确保自动诊断失败不影响主分析流水线。
    """
    # Late import to break a circular dependency with diagnose.py.
    from ci_optimizer.api.diagnose import run_diagnosis

    try:
        async with async_session() as db:
            result = await run_diagnosis(
                db,
                owner=owner,
                repo_name=repo_name,
                run_id=run_id,
                run_attempt=run_attempt,
                tier="default",
                source="webhook_auto",
                config=config,
            )
            logger.info(
                "auto-diagnose: %s/%s run=%d category=%s cost=%s",
                owner,
                repo_name,
                run_id,
                result.category,
                result.cost_usd,
            )
    except Exception as e:
        logger.warning("auto-diagnose failed for %s/%s run=%d: %s", owner, repo_name, run_id, e)


async def _should_auto_diagnose(db: AsyncSession, config: AgentConfig) -> tuple[bool, str]:
    """Decide whether to enqueue an auto-diagnosis for a failed webhook run.

    Returns (should_run, reason). Reason is useful for logging/debugging.
    三道门控（按顺序）：全局开关 → 随机采样率 → 今日累计费用预算。
    reason 字符串用于响应体和日志，方便调试配置是否生效。
    """
    if not config.diagnose_auto_on_webhook:
        return False, "disabled"
    if random.random() > config.diagnose_sample_rate:
        return False, f"sampled-out (rate={config.diagnose_sample_rate})"
    spend = await get_daily_diagnose_spend(db)
    if spend >= config.diagnose_budget_usd_day:
        return False, f"budget-exceeded (spend=${spend:.4f} >= ${config.diagnose_budget_usd_day})"
    return True, "ok"


def _verify_signature(payload: bytes, signature_header: str | None, secret: str) -> None:
    """Validate X-Hub-Signature-256 HMAC.

    Raises HTTPException 401 if the signature is missing or invalid.
    使用 hmac.compare_digest 进行常数时间比较，防止时序攻击。
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

    # Track per-event auto-diagnosis intent so we can attach the task AFTER
    # the db.commit() below (BackgroundTasks only run after response send).
    # 先收集自动诊断的目标信息，等 db.commit() 完成后再添加 background task，
    # 保证 session 已关闭、DB 数据已持久化时后台任务才开始执行。
    auto_diag_target: dict | None = None

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
        run_id_val = wf_run.get("id")
        run_attempt_val = wf_run.get("run_attempt", 1)
        run_conclusion = wf_run.get("conclusion", "")

        logger.info(
            "Webhook received: workflow_run completed for %s (run_id=%s, branch=%s, conclusion=%s)",
            full_name,
            run_id_val,
            wf_run.get("head_branch"),
            run_conclusion,
        )

        # Remember details for auto-diagnosis dispatch later
        if run_conclusion == "failure" and isinstance(run_id_val, int):
            auto_diag_target = {
                "owner": owner,
                "repo_name": repo_name,
                "run_id": run_id_val,
                "run_attempt": int(run_attempt_val or 1),
            }

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

    # Auto-diagnosis dispatch (v1): only for workflow_run failures, gated on
    # the master switch + sample rate + daily budget.
    auto_diag_queued = False
    auto_diag_reason = "not-a-failure"
    if auto_diag_target is not None:
        should_run, reason = await _should_auto_diagnose(db, config)
        auto_diag_reason = reason
        if should_run:
            background_tasks.add_task(
                _run_auto_diagnosis_task,
                auto_diag_target["owner"],
                auto_diag_target["repo_name"],
                auto_diag_target["run_id"],
                auto_diag_target["run_attempt"],
                config,
            )
            auto_diag_queued = True
            logger.info(
                "Auto-diagnose queued: %s run_id=%d",
                full_name,
                auto_diag_target["run_id"],
            )
        else:
            logger.info("Auto-diagnose skipped (%s): %s", auto_diag_reason, full_name)

    return {
        "status": "accepted",
        "report_id": report.id,
        "repo": full_name,
        "auto_diagnose": {
            "queued": auto_diag_queued,
            "reason": auto_diag_reason,
        },
    }
