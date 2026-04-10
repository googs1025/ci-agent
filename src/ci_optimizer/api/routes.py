"""FastAPI route handlers."""

import asyncio
import json
import traceback

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ci_optimizer.agents.orchestrator import run_analysis
from ci_optimizer.api.schemas import (
    AgentConfigSchema,
    AnalyzeRequest,
    DashboardResponse,
    ReportDetail,
    ReportListResponse,
    ReportSummary,
    RepositorySchema,
    FindingSchema,
)
from ci_optimizer.config import AgentConfig
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


def _build_config_from_schema(schema: AgentConfigSchema | None) -> AgentConfig:
    """Build AgentConfig from base config + per-request overrides."""
    config = AgentConfig.load()
    if schema:
        for field in ("provider", "model", "fallback_model", "anthropic_api_key",
                       "openai_api_key", "github_token", "base_url", "language"):
            val = getattr(schema, field, None)
            if val is not None:
                setattr(config, field, val)
        if schema.max_turns is not None:
            config.max_turns = schema.max_turns
    return config


async def _run_analysis_task(
    report_id: int,
    repo_input: str,
    filters: AnalysisFilters | None,
    config: AgentConfig | None = None,
    selected_skills: list[str] | None = None,
):
    """Background task to run the analysis."""
    import logging
    import shutil
    logger = logging.getLogger("ci_optimizer.background")

    resolved = None
    ctx = None
    async with async_session() as session:
        try:
            logger.info(f"[report={report_id}] Starting analysis: repo={repo_input}, provider={config.provider if config else 'default'}, lang={config.language if config else 'default'}")

            # Load skills to compute required data
            from ci_optimizer.agents.skill_registry import SkillRegistry
            registry = SkillRegistry().load()
            skills = registry.get_active_skills(selected=selected_skills)
            required_data = registry.collect_required_data(skills)

            resolved = resolve_input(repo_input)
            ctx = await prepare_context(resolved, filters, required_data=required_data)
            logger.info(f"[report={report_id}] Prefetch done: {len(ctx.workflow_files)} workflows, required={required_data}")
            result = await run_analysis(ctx, config=config, selected_skills=selected_skills)
            logger.info(f"[report={report_id}] Analysis done: {len(result.findings)} findings, {len(result.raw_report)} chars raw")

            lang = config.language if config else "en"
            summary_md = format_markdown(result, ctx, language=lang)
            full_json = format_json(result, ctx, language=lang)

            await complete_report(
                session=session,
                report_id=report_id,
                summary_md=summary_md,
                full_report_json=full_json,
                findings_data=result.findings,
                duration_ms=result.duration_ms,
            )
            await session.commit()
            logger.info(f"[report={report_id}] Saved to DB: {len(result.findings)} findings")
        except Exception as e:
            logger.error(f"[report={report_id}] Failed: {e}", exc_info=True)
            await fail_report(session, report_id, str(e))
            await session.commit()
        finally:
            # Cleanup temp files and cloned repos
            if ctx:
                for attr in ("runs_json_path", "jobs_json_path", "usage_stats_json_path",
                              "logs_json_path", "workflows_json_path"):
                    p = getattr(ctx, attr, None)
                    if p and p.exists():
                        try:
                            p.unlink()
                        except OSError:
                            pass
            if resolved and resolved.temp_dir:
                shutil.rmtree(resolved.temp_dir, ignore_errors=True)


@router.post("/analyze")
async def analyze(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a new CI pipeline analysis."""
    # Extract owner/repo without cloning (clone deferred to background task)
    from ci_optimizer.resolver import is_github_url, is_github_shorthand, parse_github_url, GITHUB_SHORTHAND_PATTERN

    repo_input = request.repo
    if is_github_url(repo_input):
        owner, repo_name = parse_github_url(repo_input)
    elif is_github_shorthand(repo_input):
        match = GITHUB_SHORTHAND_PATTERN.match(repo_input)
        owner, repo_name = match.group(1), match.group(2)
    else:
        # Local path — validate exists and is safe
        from pathlib import Path
        p = Path(repo_input).resolve()
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"Path does not exist: {repo_input}")
        # Block path traversal: must contain .github/workflows
        wf_dir = p / ".github" / "workflows"
        if not wf_dir.exists():
            raise HTTPException(status_code=400, detail=f"Not a valid repo: no .github/workflows/ found in {repo_input}")
        owner = "local"
        repo_name = p.name

    db_repo = await get_or_create_repo(
        db, owner, repo_name,
        url=repo_input if owner != "local" else None,
    )

    filters = _to_analysis_filters(request.filters)
    filters_json = json.dumps(filters.to_dict()) if filters else None
    config = _build_config_from_schema(request.agent_config)

    report = await create_report(db, db_repo.id, filters_json)
    await db.commit()

    background_tasks.add_task(
        _run_analysis_task, report.id, request.repo, filters, config, request.skills
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
                code_snippet=f.code_snippet,
                suggested_code=f.suggested_code,
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


@router.get("/config")
async def get_config():
    """Get current agent configuration (sensitive values masked)."""
    config = AgentConfig.load()
    return config.to_display_dict()


@router.put("/config")
async def update_config(updates: AgentConfigSchema):
    """Update agent configuration."""
    config = AgentConfig.load()
    for field in ("provider", "model", "fallback_model", "anthropic_api_key",
                   "openai_api_key", "github_token", "base_url", "language"):
        val = getattr(updates, field, None)
        if val is not None:
            setattr(config, field, val)
    if updates.max_turns is not None:
        config.max_turns = updates.max_turns
    config.save()
    return config.to_display_dict()


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
