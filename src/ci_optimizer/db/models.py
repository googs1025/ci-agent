"""SQLAlchemy ORM models for CI Agent."""

import json
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str]
    repo: Mapped[str]
    url: Mapped[str | None]
    last_analyzed_at: Mapped[datetime | None]

    reports: Mapped[list["AnalysisReport"]] = relationship(back_populates="repository")


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    filters_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="pending")  # pending/running/completed/failed
    summary_md: Mapped[str | None] = mapped_column(Text)
    full_report_json: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None]
    error_message: Mapped[str | None] = mapped_column(Text)

    repository: Mapped["Repository"] = relationship(back_populates="reports")
    findings: Mapped[list["Finding"]] = relationship(back_populates="report")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("analysis_reports.id"))
    dimension: Mapped[str]  # efficiency/security/cost/error
    severity: Mapped[str]  # critical/major/minor/info
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None]
    line: Mapped[int | None]
    suggestion: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None]

    report: Mapped["AnalysisReport"] = relationship(back_populates="findings")
