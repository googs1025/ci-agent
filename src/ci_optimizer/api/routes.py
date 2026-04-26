"""FastAPI route handlers."""
# ── 架构角色 ──────────────────────────────────────────────────────────────────
# 本文件是 CI 分析功能的主路由层，统一挂载在 /api 前缀下并要求 API Key 鉴权。
# 核心职责：
#   - POST /analyze：接收仓库地址，异步在后台跑分析任务，立即返回 report_id
#   - GET /reports / /reports/{id}：查询分析报告和明细
#   - GET/PUT /config：读写运行时 Agent 配置（支持热更新）
#   - GET/POST/DELETE /skills：管理内置与用户自定义分析 skill
#   - GET /repositories / /dashboard / /dashboard/trends：统计与趋势视图
# 与 orchestrator（跑分析）、skill_registry（管理 skill）、db/crud（持久化）深度耦合。

import json
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ci_optimizer.agents.orchestrator import run_analysis
from ci_optimizer.api.auth import verify_api_key
from ci_optimizer.api.schemas import (  # noqa: E501 — many imports
    AgentConfigSchema,
    AnalyzeRequest,
    DashboardResponse,
    FindingSchema,
    ReportDetail,
    ReportListResponse,
    ReportSummary,
    RepositorySchema,
    SkillImportRequest,
    SkillImportResponse,
    SkillSchema,
    TrendsResponse,
)
from ci_optimizer.config import AgentConfig
from ci_optimizer.db.crud import (
    complete_report,
    compute_filters_hash,
    create_report,
    fail_report,
    find_cached_report,
    get_dashboard_stats,
    get_dashboard_trends,
    get_or_create_repo,
    get_report,
    list_reports,
    list_repositories,
)
from ci_optimizer.db.database import async_session
from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.prefetch import prepare_context
from ci_optimizer.report.formatter import format_json, format_summary_markdown
from ci_optimizer.resolver import resolve_input

router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])


async def get_db():
    """FastAPI 依赖注入：提供异步数据库 session，请求结束后自动关闭。"""
    async with async_session() as session:
        yield session


def _to_analysis_filters(schema) -> AnalysisFilters | None:
    """将 FilterSchema（API 请求体）转换为内部 AnalysisFilters，处理 since/until 对的组合逻辑。"""
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
        for field in ("provider", "model", "fallback_model", "anthropic_api_key", "openai_api_key", "github_token", "base_url", "language"):
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
    """后台分析任务：在独立协程中完整执行"预取→分析→格式化→入库"流水线。
    成功时将报告写入 DB，失败时记录错误状态。finally 块负责清理临时文件和克隆目录。
    """
    import logging
    import shutil

    logger = logging.getLogger("ci_optimizer.background")

    resolved = None
    ctx = None
    async with async_session() as session:
        try:
            logger.info(
                f"[report={report_id}] Starting analysis: repo={repo_input}, provider={config.provider if config else 'default'}, lang={config.language if config else 'default'}"
            )

            # Load skills to compute required data (uses singleton cache)
            from ci_optimizer.agents.skill_registry import get_registry

            registry = get_registry()
            skills = registry.get_active_skills(selected=selected_skills)
            required_data = registry.collect_required_data(skills)

            resolved = resolve_input(repo_input)
            ctx = await prepare_context(resolved, filters, required_data=required_data)
            logger.info(f"[report={report_id}] Prefetch done: {len(ctx.workflow_files)} workflows, required={required_data}")
            result = await run_analysis(ctx, config=config, selected_skills=selected_skills)
            logger.info(f"[report={report_id}] Analysis done: {len(result.findings)} findings, {len(result.raw_report)} chars raw")

            lang = config.language if config else "en"
            summary_md = format_summary_markdown(result, ctx, language=lang)
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
                for attr in ("runs_json_path", "jobs_json_path", "usage_stats_json_path", "logs_json_path", "workflows_json_path"):
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
    """触发一次新的 CI 流水线分析。
    先做缓存查找（同仓库+同过滤条件的近期报告），命中则直接返回；
    未命中则创建 running 状态的报告记录，将实际分析推入后台任务，立即返回 report_id。
    """
    # Extract owner/repo without cloning (clone deferred to background task)
    from ci_optimizer.resolver import GITHUB_SHORTHAND_PATTERN, is_github_shorthand, is_github_url, parse_github_url

    repo_input = request.repo
    if is_github_url(repo_input):
        owner, repo_name = parse_github_url(repo_input)
    elif is_github_shorthand(repo_input):
        match = GITHUB_SHORTHAND_PATTERN.match(repo_input)
        owner, repo_name = match.group(1), match.group(2)
    else:
        # Local path — validate exists and is safe
        # 本地路径：校验目录存在且含 .github/workflows/，防止路径遍历攻击
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
        db,
        owner,
        repo_name,
        url=repo_input if owner != "local" else None,
    )

    filters = _to_analysis_filters(request.filters)
    filters_json = json.dumps(filters.to_dict()) if filters else None
    config = _build_config_from_schema(request.agent_config)

    # Check cache: reuse recent completed report for same repo+filters
    fhash = compute_filters_hash(filters_json)
    ttl = int(os.getenv("CI_AGENT_CACHE_TTL_HOURS", "24"))
    if ttl > 0:
        cached = await find_cached_report(db, db_repo.id, fhash, ttl)
        if cached:
            return {"report_id": cached.id, "status": "completed", "cached": True}

    report = await create_report(db, db_repo.id, filters_json, filters_hash=fhash)
    await db.commit()

    background_tasks.add_task(_run_analysis_task, report.id, request.repo, filters, config, request.skills)

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
                skill_name=f.skill_name,
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


@router.get("/dashboard/trends", response_model=TrendsResponse)
async def dashboard_trends(
    days: int = 30,
    repo: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get time-series trend data for dashboard charts."""
    if days not in (7, 30, 90):
        days = 30
    data = await get_dashboard_trends(db, days=days, repo=repo)
    return TrendsResponse(**data)


@router.get("/config")
async def get_config():
    """Get current agent configuration (sensitive values masked)."""
    config = AgentConfig.load()
    return config.to_display_dict()


# Mapping: config field → env var name (so PUT /api/config can override env vars in-process)
_FIELD_TO_ENV = {
    "provider": "CI_AGENT_PROVIDER",
    "model": "CI_AGENT_MODEL",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "github_token": "GITHUB_TOKEN",
    "base_url": "CI_AGENT_BASE_URL",
    "language": "CI_AGENT_LANGUAGE",
}


@router.put("/config")
async def update_config(updates: AgentConfigSchema):
    """更新 Agent 配置：同时写入 config.json 并更新进程内环境变量，使变更立即生效，
    避免下次 AgentConfig.load() 从 env 读取到旧值而覆盖刚写入的配置。
    """
    config = AgentConfig.load()
    for field in ("provider", "model", "fallback_model", "anthropic_api_key", "openai_api_key", "github_token", "base_url", "language"):
        val = getattr(updates, field, None)
        if val is not None:
            setattr(config, field, val)
            # Also set env var so load() won't revert the change
            if env_key := _FIELD_TO_ENV.get(field):
                os.environ[env_key] = val
    if updates.max_turns is not None:
        config.max_turns = updates.max_turns
    config.save()
    return config.to_display_dict()


@router.get("/skills", response_model=list[SkillSchema])
async def get_skills():
    """List all available analysis skills (builtin + user)."""
    from ci_optimizer.agents.skill_registry import get_registry

    registry = get_registry()
    # Include all skills (enabled + disabled) so users can see what's available
    all_skills = list(registry._skills.values())
    # Sort by priority desc, then name
    all_skills.sort(key=lambda s: (-s.priority, s.name))
    return [
        SkillSchema(
            name=s.name,
            description=s.description,
            dimension=s.dimension,
            source=s.source,
            enabled=s.enabled,
            priority=s.priority,
            tools=s.tools,
            requires_data=s.requires_data,
            prompt=s.prompt,
        )
        for s in all_skills
    ]


@router.post("/skills/reload")
async def reload_skills():
    """Rescan builtin + user skill directories and refresh the registry cache."""
    from ci_optimizer.agents.skill_registry import get_registry

    registry = get_registry()
    registry.reload()
    skills = registry.get_active_skills()
    return {
        "reloaded": True,
        "active_count": len(skills),
        "skills": [{"name": s.name, "dimension": s.dimension, "source": s.source} for s in skills],
    }


@router.post("/skills/import", response_model=SkillImportResponse)
async def import_skill(req: SkillImportRequest):
    """从多种来源导入自定义 skill（Claude Code / OpenCode / 本地路径 / GitHub 仓库）。
    导入成功后立即重载内存中的 skill 注册表单例，让新 skill 对后续分析请求即时可用。
    """
    from pathlib import Path as _P

    from ci_optimizer.agents.skill_importer import (
        SkillImportError,
        import_from_claude_code,
        import_from_opencode,
        import_from_path,
        install_from_github,
    )
    from ci_optimizer.agents.skill_registry import get_registry

    try:
        if req.source_type == "claude-code":
            result = import_from_claude_code(req.source, dimension=req.dimension, requires_data=req.requires_data)
        elif req.source_type == "opencode":
            result = import_from_opencode(req.source, dimension=req.dimension, requires_data=req.requires_data)
        elif req.source_type == "path":
            result = import_from_path(
                _P(req.source),
                dimension=req.dimension,
                requires_data=req.requires_data,
                name_override=req.name_override,
                source_kind="path",
            )
        elif req.source_type == "github":
            result = install_from_github(req.source, dimension=req.dimension, requires_data=req.requires_data)
        else:  # pragma: no cover — pydantic validates the literal
            raise HTTPException(400, f"Unknown source_type: {req.source_type}")
    except SkillImportError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Refresh the singleton so the new skill is immediately usable
    get_registry().reload()

    return SkillImportResponse(
        name=result.name,
        dimension=result.dimension,
        target_path=str(result.target_path),
        source_kind=result.source_kind,
        warnings=result.warnings,
    )


@router.delete("/skills/{name}")
async def delete_skill(name: str):
    """Uninstall a user-installed skill by directory name."""
    from ci_optimizer.agents.skill_importer import SkillImportError, uninstall_skill
    from ci_optimizer.agents.skill_registry import get_registry

    try:
        path = uninstall_skill(name)
    except SkillImportError as e:
        raise HTTPException(status_code=404, detail=str(e))

    get_registry().reload()
    return {"removed": str(path)}


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
