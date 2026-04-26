"""CRUD operations for CI Agent database.

架构角色：数据访问层（DAL），将所有 SQL 逻辑集中到一处，上层服务只调用函数而无需编写 ORM 查询。
核心职责：提供仓库、报告、发现项和失败诊断的增删改查接口，以及缓存命中判断和看板统计聚合。
与其他模块的关系：依赖 models.py 的 ORM 类；被 FastAPI 路由、AI 技能、Webhook 处理器调用；
database.py 提供 async_session 工厂注入此模块的每个函数。
"""

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ci_optimizer.db.models import AnalysisReport, FailureDiagnosis, Finding, Repository


def compute_filters_hash(filters_json: str | None) -> str:
    """Return a short deterministic hash for the given filters JSON string.

    生成过滤条件的 12 位 MD5 指纹，用作报告缓存的 key。
    None 和空字符串视为等价（"无过滤"），统一映射到相同 hash。
    """
    content = filters_json or ""
    return hashlib.md5(content.encode()).hexdigest()[:12]


async def find_cached_report(
    session: AsyncSession,
    repo_id: int,
    filters_hash: str,
    ttl_hours: int = 24,
) -> AnalysisReport | None:
    """Return the most recent completed report matching the cache key within TTL.

    避免对同一仓库+过滤条件在 TTL 窗口内重复触发耗时的 LLM 分析。
    仅返回 status="completed" 的报告，进行中或失败的记录不参与缓存命中。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    stmt = (
        select(AnalysisReport)
        .where(
            AnalysisReport.repo_id == repo_id,
            AnalysisReport.filters_hash == filters_hash,
            AnalysisReport.status == "completed",
            AnalysisReport.created_at >= cutoff,
        )
        .order_by(AnalysisReport.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_repo(session: AsyncSession, owner: str, repo: str, url: str | None = None) -> Repository:
    """查找或新建仓库记录，保证同一 owner/repo 只存在一行。

    使用 flush 而非 commit，让调用方统一控制事务边界。
    """
    stmt = select(Repository).where(Repository.owner == owner, Repository.repo == repo)
    result = await session.execute(stmt)
    db_repo = result.scalar_one_or_none()
    if db_repo is None:
        db_repo = Repository(owner=owner, repo=repo, url=url)
        session.add(db_repo)
        await session.flush()
    return db_repo


async def create_report(
    session: AsyncSession,
    repo_id: int,
    filters_json: str | None = None,
    filters_hash: str | None = None,
) -> AnalysisReport:
    """创建状态为 "running" 的报告占位行，分析完成后再由 complete_report 填充结果。

    先写占位行的好处：即使分析过程中断，数据库里也有失败记录可供追溯。
    """
    report = AnalysisReport(
        repo_id=repo_id,
        filters_json=filters_json,
        filters_hash=filters_hash,
        status="running",
    )
    session.add(report)
    await session.flush()
    return report


async def complete_report(
    session: AsyncSession,
    report_id: int,
    summary_md: str,
    full_report_json: str,
    findings_data: list[dict],
    duration_ms: int,
) -> AnalysisReport:
    """将分析结果写回报告行，同步批量插入 Finding 记录，并更新仓库的最后分析时间。"""
    stmt = select(AnalysisReport).where(AnalysisReport.id == report_id)
    result = await session.execute(stmt)
    report = result.scalar_one()

    report.status = "completed"
    report.summary_md = summary_md
    report.full_report_json = full_report_json
    report.duration_ms = duration_ms

    for f in findings_data:
        finding = Finding(
            report_id=report_id,
            dimension=f.get("dimension", "unknown"),
            skill_name=f.get("skill_name"),
            severity=f.get("severity", "info"),
            title=f.get("title", "Untitled finding"),
            description=f.get("description", ""),
            file_path=f.get("file"),
            line=f.get("line"),
            suggestion=f.get("suggestion"),
            impact=f.get("impact"),
            code_snippet=f.get("code_snippet"),
            suggested_code=f.get("suggested_code"),
        )
        session.add(finding)

    # Update repo's last_analyzed_at
    repo_stmt = select(Repository).where(Repository.id == report.repo_id)
    repo_result = await session.execute(repo_stmt)
    repo = repo_result.scalar_one()
    repo.last_analyzed_at = datetime.now(timezone.utc)

    await session.flush()
    return report


async def fail_report(session: AsyncSession, report_id: int, error_message: str) -> None:
    """将报告标记为 failed 并记录错误信息，供 UI 展示和后续重试判断。"""
    stmt = select(AnalysisReport).where(AnalysisReport.id == report_id)
    result = await session.execute(stmt)
    report = result.scalar_one()
    report.status = "failed"
    report.error_message = error_message
    await session.flush()


async def get_report(session: AsyncSession, report_id: int) -> AnalysisReport | None:
    """按 ID 查询单条报告，预加载 findings 和 repository，避免 N+1 懒加载问题。"""
    stmt = (
        select(AnalysisReport)
        .options(selectinload(AnalysisReport.findings), selectinload(AnalysisReport.repository))
        .where(AnalysisReport.id == report_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_reports(
    session: AsyncSession,
    repo_owner: str | None = None,
    repo_name: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[AnalysisReport], int]:
    """返回分页报告列表及总数，可选按 owner/repo 过滤。

    total 与列表在同一事务内查询，保证分页数据一致性。
    """
    stmt = (
        select(AnalysisReport)
        .options(selectinload(AnalysisReport.repository), selectinload(AnalysisReport.findings))
        .order_by(AnalysisReport.created_at.desc())
    )
    count_stmt = select(func.count(AnalysisReport.id))

    if repo_owner and repo_name:
        stmt = stmt.join(Repository).where(Repository.owner == repo_owner, Repository.repo == repo_name)
        count_stmt = count_stmt.join(Repository).where(Repository.owner == repo_owner, Repository.repo == repo_name)

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await session.execute(stmt)
    reports = list(result.scalars().all())

    return reports, total


async def list_repositories(session: AsyncSession) -> list[Repository]:
    """返回所有仓库，按最近分析时间倒序排列，未分析过的仓库排在末尾（nullslast）。"""
    stmt = select(Repository).order_by(Repository.last_analyzed_at.desc().nullslast())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_dashboard_stats(session: AsyncSession) -> dict:
    """聚合看板所需的概览统计：仓库数、报告数、按严重程度和维度的发现项分布，以及最近 5 条报告。"""
    repo_count = await session.execute(select(func.count(Repository.id)))
    report_count = await session.execute(select(func.count(AnalysisReport.id)))

    severity_stmt = select(Finding.severity, func.count(Finding.id)).group_by(Finding.severity)
    severity_result = await session.execute(severity_stmt)

    dimension_stmt = select(Finding.dimension, func.count(Finding.id)).group_by(Finding.dimension)
    dimension_result = await session.execute(dimension_stmt)

    recent_stmt = (
        select(AnalysisReport)
        .options(selectinload(AnalysisReport.repository))
        .where(AnalysisReport.status == "completed")
        .order_by(AnalysisReport.created_at.desc())
        .limit(5)
    )
    recent_result = await session.execute(recent_stmt)

    return {
        "repo_count": repo_count.scalar() or 0,
        "analysis_count": report_count.scalar() or 0,
        "severity_distribution": dict(severity_result.all()),
        "dimension_distribution": dict(dimension_result.all()),
        "recent_reports": list(recent_result.scalars().all()),
    }


async def get_dashboard_trends(
    session: AsyncSession,
    days: int = 30,
    repo: str | None = None,
) -> dict:
    """Return time-series trend data for dashboard charts.

    Returns:
        - daily_scores: per-day finding counts by severity
        - dimension_trends: per-day finding counts by dimension
        - repo_comparison: per-repo finding counts for latest analysis
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Base filter: completed reports within time range
    base_filter = [
        AnalysisReport.status == "completed",
        AnalysisReport.created_at >= cutoff,
    ]
    if repo:
        parts = repo.split("/", 1)
        if len(parts) == 2:
            base_filter.append(Repository.owner == parts[0])
            base_filter.append(Repository.repo == parts[1])

    # SQLite date() for grouping by day
    date_expr = func.date(AnalysisReport.created_at)

    # ── Daily severity counts ──
    daily_sev_stmt = (
        select(
            date_expr.label("date"),
            func.count(Finding.id).label("total"),
            func.sum(case((Finding.severity == "critical", 1), else_=0)).label("critical"),
            func.sum(case((Finding.severity == "major", 1), else_=0)).label("major"),
            func.sum(case((Finding.severity == "minor", 1), else_=0)).label("minor"),
            func.sum(case((Finding.severity == "info", 1), else_=0)).label("info"),
        )
        .select_from(AnalysisReport)
        .join(Repository, AnalysisReport.repo_id == Repository.id)
        .join(Finding, Finding.report_id == AnalysisReport.id)
        .where(*base_filter)
        .group_by(date_expr)
        .order_by(date_expr)
    )
    daily_sev_result = await session.execute(daily_sev_stmt)
    daily_scores = [
        {
            "date": str(row.date),
            "total": row.total,
            "critical": row.critical,
            "major": row.major,
            "minor": row.minor,
            "info": row.info,
        }
        for row in daily_sev_result.all()
    ]

    # ── Daily dimension counts ──
    daily_dim_stmt = (
        select(
            date_expr.label("date"),
            func.sum(case((Finding.dimension == "efficiency", 1), else_=0)).label("efficiency"),
            func.sum(case((Finding.dimension == "security", 1), else_=0)).label("security"),
            func.sum(case((Finding.dimension == "cost", 1), else_=0)).label("cost"),
            func.sum(case((Finding.dimension == "errors", 1), else_=0)).label("errors"),
        )
        .select_from(AnalysisReport)
        .join(Repository, AnalysisReport.repo_id == Repository.id)
        .join(Finding, Finding.report_id == AnalysisReport.id)
        .where(*base_filter)
        .group_by(date_expr)
        .order_by(date_expr)
    )
    daily_dim_result = await session.execute(daily_dim_stmt)
    dimension_trends = [
        {
            "date": str(row.date),
            "efficiency": row.efficiency,
            "security": row.security,
            "cost": row.cost,
            "errors": row.errors,
        }
        for row in daily_dim_result.all()
    ]

    # ── Repo comparison: total findings per repo (latest report each) ──
    # 子查询：每个仓库只取最新一条已完成报告，避免历史数据重复计入跨仓库对比
    latest_report_sub = (
        select(
            AnalysisReport.repo_id,
            func.max(AnalysisReport.id).label("latest_id"),
        )
        .where(AnalysisReport.status == "completed", AnalysisReport.created_at >= cutoff)
        .group_by(AnalysisReport.repo_id)
        .subquery()
    )

    repo_cmp_stmt = (
        select(
            (Repository.owner + cast("/", String) + Repository.repo).label("repo_name"),
            func.count(Finding.id).label("total"),
            func.sum(case((Finding.severity == "critical", 1), else_=0)).label("critical"),
            func.sum(case((Finding.severity == "major", 1), else_=0)).label("major"),
            func.sum(case((Finding.severity == "minor", 1), else_=0)).label("minor"),
            func.sum(case((Finding.severity == "info", 1), else_=0)).label("info"),
        )
        .select_from(latest_report_sub)
        .join(AnalysisReport, AnalysisReport.id == latest_report_sub.c.latest_id)
        .join(Repository, Repository.id == latest_report_sub.c.repo_id)
        .join(Finding, Finding.report_id == AnalysisReport.id)
        .group_by(Repository.owner, Repository.repo)
        .order_by(func.count(Finding.id).desc())
    )
    repo_cmp_result = await session.execute(repo_cmp_stmt)
    repo_comparison = [
        {
            "repo": row.repo_name,
            "total": row.total,
            "critical": row.critical,
            "major": row.major,
            "minor": row.minor,
            "info": row.info,
        }
        for row in repo_cmp_result.all()
    ]

    return {
        "daily_scores": daily_scores,
        "dimension_trends": dimension_trends,
        "repo_comparison": repo_comparison,
    }


# ── Failure diagnoses (issue #35, v1) ───────────────────────────────────────


async def find_cached_diagnosis(
    session: AsyncSession,
    repo_id: int,
    run_id: int,
    run_attempt: int,
    tier: str,
) -> FailureDiagnosis | None:
    """Return the diagnosis for this exact (run, tier) if it exists.

    Unlike report caching, diagnoses have no TTL — a run is immutable, so
    the diagnosis for it should never need re-computation at the same tier.
    """
    stmt = select(FailureDiagnosis).where(
        FailureDiagnosis.repo_id == repo_id,
        FailureDiagnosis.run_id == run_id,
        FailureDiagnosis.run_attempt == run_attempt,
        FailureDiagnosis.tier == tier,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def find_diagnosis_by_signature(
    session: AsyncSession,
    signature: str,
    ttl_hours: int = 24,
) -> FailureDiagnosis | None:
    """Return the most recent diagnosis matching this signature within TTL.

    Used for signature-based dedup: if the exact same error (same step,
    same normalized error line) was diagnosed within the TTL window, reuse
    that diagnosis instead of calling the LLM again.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    stmt = (
        select(FailureDiagnosis)
        .where(
            FailureDiagnosis.error_signature == signature,
            FailureDiagnosis.created_at >= cutoff,
        )
        .order_by(FailureDiagnosis.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def save_diagnosis(
    session: AsyncSession,
    *,
    repo_id: int,
    run_id: int,
    run_attempt: int,
    tier: str,
    category: str,
    confidence: str,
    root_cause: str,
    quick_fix: str | None,
    failing_step: str | None,
    workflow: str,
    error_excerpt: str,
    error_signature: str,
    model: str,
    cost_usd: float | None,
    source: str = "manual",
) -> FailureDiagnosis:
    """Upsert a diagnosis keyed on (repo_id, run_id, run_attempt, tier).

    用 upsert 语义而非 insert-or-ignore：若已存在则用最新结果覆盖（支持 deep 升级 default）。
    所有参数均为 keyword-only，防止调用方因参数顺序错误写入错误字段。
    """
    existing = await find_cached_diagnosis(session, repo_id, run_id, run_attempt, tier)
    if existing is not None:
        existing.category = category
        existing.confidence = confidence
        existing.root_cause = root_cause
        existing.quick_fix = quick_fix
        existing.failing_step = failing_step
        existing.workflow = workflow
        existing.error_excerpt = error_excerpt
        existing.error_signature = error_signature
        existing.model = model
        existing.cost_usd = cost_usd
        existing.source = source
        await session.flush()
        return existing

    diag = FailureDiagnosis(
        repo_id=repo_id,
        run_id=run_id,
        run_attempt=run_attempt,
        tier=tier,
        category=category,
        confidence=confidence,
        root_cause=root_cause,
        quick_fix=quick_fix,
        failing_step=failing_step,
        workflow=workflow,
        error_excerpt=error_excerpt,
        error_signature=error_signature,
        model=model,
        cost_usd=cost_usd,
        source=source,
    )
    session.add(diag)
    await session.flush()
    return diag


async def list_diagnoses_by_signature(
    session: AsyncSession,
    signature: str,
    days: int = 30,
) -> list[FailureDiagnosis]:
    """Return all diagnoses sharing a signature within the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(FailureDiagnosis)
        .where(
            FailureDiagnosis.error_signature == signature,
            FailureDiagnosis.created_at >= cutoff,
        )
        .order_by(FailureDiagnosis.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_daily_diagnose_spend(session: AsyncSession) -> float:
    """Sum cost_usd of all diagnoses created in the last 24 hours.

    Used by the webhook auto-diagnosis path to enforce a daily budget
    ceiling. Returns 0.0 if no diagnoses recorded or cost_usd is NULL.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = select(func.coalesce(func.sum(FailureDiagnosis.cost_usd), 0.0)).where(
        FailureDiagnosis.created_at >= cutoff,
    )
    result = await session.execute(stmt)
    return float(result.scalar_one() or 0.0)
