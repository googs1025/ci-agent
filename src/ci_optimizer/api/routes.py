"""FastAPI route handlers."""

import asyncio
import json
import traceback

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ci_optimizer.agents.orchestrator import run_analysis
from ci_optimizer.api.schemas import (
    AnalyzeRequest,
    DashboardResponse,
    ReportDetail,
    ReportListResponse,
    ReportSummary,
    RepositorySchema,
    FindingSchema,
)
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
from ci_optimizer.db.database import async_session
from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.prefetch import prepare_context
from ci_optimizer.report.formatter import format_json, format_markdown
from ci_optimizer.resolver import resolve_input

router = APIRouter(prefix="/api")


async def get_db():
    async with async_session() as session:
        yield session


def _to_analysis_filters(schema) -> AnalysisFilters | None:
    if schema is None:
        return None
    time_range = None
    if schema.since and schema.until:
        time_range = (schema.since, schema.until)
    return AnalysisFilters(
        time_range=time_range,
        workflows=schema.workflows,
        status=schema.status,
        branches=schema.branches,
    )


async def _run_analysis_task(report_id: int, repo_input: str, filters: AnalysisFilters | None):
    """Background task to run the analysis."""
    async with async_session() as session:
        try:
            resolved = resolve_input(repo_input)
            ctx = await prepare_context(resolved, filters)
            result = await run_analysis(ctx)

            summary_md = format_markdown(result, ctx)
            full_json = format_json(result, ctx)

            await complete_report(
                session=session,
                report_id=report_id,
                summary_md=summary_md,
                full_report_json=full_json,
                findings_data=result.findings,
                duration_ms=result.duration_ms,
            )
            await session.commit()
        except Exception as e:
            await fail_report(session, report_id, str(e))
            await session.commit()


@router.post("/analyze")
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a new CI pipeline analysis."""
    # Resolve repo info for DB record
    try:
        resolved = resolve_input(request.repo)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    owner = resolved.owner or "local"
    repo_name = resolved.repo or str(resolved.local_path.name)

    db_repo = await get_or_create_repo(
        db, owner, repo_name,
        url=request.repo if resolved.is_remote else None,
    )

    filters = _to_analysis_filters(request.filters)
    filters_json = json.dumps(filters.to_dict()) if filters else None

    report = await create_report(db, db_repo.id, filters_json)
    await db.commit()

    background_tasks.add_task(
        _run_analysis_task, report.id, request.repo, filters
    )

    return {"report_id": report.id, "status": "running"}


@router.get("/reports", response_model=ReportListResponse)
async def get_reports(
    repo: str | None = None,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List analysis reports with pagination."""
    repo_owner, repo_name = None, None
    if repo and "/" in repo:
        repo_owner, repo_name = repo.split("/", 1)

    reports, total = await list_reports(db, repo_owner, repo_name, page, limit)

    return ReportListResponse(
        reports=[
            ReportSummary(
                id=r.id,
                repo_owner=r.repository.owner if r.repository else None,
                repo_name=r.repository.repo if r.repository else None,
                created_at=r.created_at,
                status=r.status,
                finding_count=len(r.findings),
                duration_ms=r.duration_ms,
            )
            for r in reports
        ],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/reports/{report_id}", response_model=ReportDetail)
async def get_report_detail(
    report_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single report with findings."""
    report = await get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return ReportDetail(
        id=report.id,
        repo_owner=report.repository.owner if report.repository else None,
        repo_name=report.repository.repo if report.repository else None,
        created_at=report.created_at,
        status=report.status,
        summary_md=report.summary_md,
        full_report_json=report.full_report_json,
        duration_ms=report.duration_ms,
        error_message=report.error_message,
        findings=[
            FindingSchema(
                id=f.id,
                dimension=f.dimension,
                severity=f.severity,
                title=f.title,
                description=f.description,
                file_path=f.file_path,
                line=f.line,
                suggestion=f.suggestion,
                impact=f.impact,
            )
            for f in report.findings
        ],
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(db: AsyncSession = Depends(get_db)):
    """Get dashboard aggregated data."""
    stats = await get_dashboard_stats(db)

    return DashboardResponse(
        repo_count=stats["repo_count"],
        analysis_count=stats["analysis_count"],
        severity_distribution=stats["severity_distribution"],
        dimension_distribution=stats["dimension_distribution"],
        recent_reports=[
            ReportSummary(
                id=r.id,
                repo_owner=r.repository.owner if r.repository else None,
                repo_name=r.repository.repo if r.repository else None,
                created_at=r.created_at,
                status=r.status,
                duration_ms=r.duration_ms,
            )
            for r in stats["recent_reports"]
        ],
    )


@router.get("/repositories", response_model=list[RepositorySchema])
async def get_repositories(db: AsyncSession = Depends(get_db)):
    """List all analyzed repositories."""
    repos = await list_repositories(db)
    return [
        RepositorySchema(
            id=r.id,
            owner=r.owner,
            repo=r.repo,
            url=r.url,
            last_analyzed_at=r.last_analyzed_at,
        )
        for r in repos
    ]
