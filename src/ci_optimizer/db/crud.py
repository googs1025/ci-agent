"""CRUD operations for CI Agent database."""

import json
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ci_optimizer.db.models import AnalysisReport, Finding, Repository


async def get_or_create_repo(
    session: AsyncSession, owner: str, repo: str, url: str | None = None
) -> Repository:
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
) -> AnalysisReport:
    report = AnalysisReport(
        repo_id=repo_id,
        filters_json=filters_json,
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


async def fail_report(
    session: AsyncSession, report_id: int, error_message: str
) -> None:
    stmt = select(AnalysisReport).where(AnalysisReport.id == report_id)
    result = await session.execute(stmt)
    report = result.scalar_one()
    report.status = "failed"
    report.error_message = error_message
    await session.flush()


async def get_report(session: AsyncSession, report_id: int) -> AnalysisReport | None:
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
    stmt = (
        select(AnalysisReport)
        .options(selectinload(AnalysisReport.repository), selectinload(AnalysisReport.findings))
        .order_by(AnalysisReport.created_at.desc())
    )
    count_stmt = select(func.count(AnalysisReport.id))

    if repo_owner and repo_name:
        stmt = stmt.join(Repository).where(
            Repository.owner == repo_owner, Repository.repo == repo_name
        )
        count_stmt = count_stmt.join(Repository).where(
            Repository.owner == repo_owner, Repository.repo == repo_name
        )

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.offset((page - 1) * limit).limit(limit)
    result = await session.execute(stmt)
    reports = list(result.scalars().all())

    return reports, total


async def list_repositories(session: AsyncSession) -> list[Repository]:
    stmt = select(Repository).order_by(Repository.last_analyzed_at.desc().nullslast())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_dashboard_stats(session: AsyncSession) -> dict:
    repo_count = await session.execute(select(func.count(Repository.id)))
    report_count = await session.execute(select(func.count(AnalysisReport.id)))

    severity_stmt = (
        select(Finding.severity, func.count(Finding.id))
        .group_by(Finding.severity)
    )
    severity_result = await session.execute(severity_stmt)

    dimension_stmt = (
        select(Finding.dimension, func.count(Finding.id))
        .group_by(Finding.dimension)
    )
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
