"""SQLAlchemy ORM models for CI Agent.

架构角色：数据层的基础，定义所有持久化实体的结构。
核心职责：声明 ORM 表结构（Repository、AnalysisReport、Finding、FailureDiagnosis），
并通过 relationship() 描述表间关联。
与其他模块的关系：被 database.py 用于建表，被 crud.py 用于查询/写入，
上层 API 路由和 AI 技能均通过 crud 间接依赖本模块。
"""

from datetime import datetime, timezone

import sqlalchemy
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Repository(Base):
    """代表一个被追踪的 GitHub 仓库，是所有报告和诊断的根节点。"""

    __tablename__ = "repositories"
    __table_args__ = (sqlalchemy.UniqueConstraint("owner", "repo", name="uq_owner_repo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str]
    repo: Mapped[str]
    url: Mapped[str | None]
    last_analyzed_at: Mapped[datetime | None]

    reports: Mapped[list["AnalysisReport"]] = relationship(back_populates="repository")


class AnalysisReport(Base):
    """一次 CI 分析任务的执行记录，包含输入过滤条件、执行状态和输出结果。

    filters_hash 用于缓存命中判断：相同过滤条件的近期报告可直接复用，避免重复调用 LLM。
    """

    __tablename__ = "analysis_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    filters_json: Mapped[str | None] = mapped_column(Text)
    filters_hash: Mapped[str | None] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default="pending")  # pending/running/completed/failed
    summary_md: Mapped[str | None] = mapped_column(Text)
    full_report_json: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None]
    error_message: Mapped[str | None] = mapped_column(Text)

    repository: Mapped["Repository"] = relationship(back_populates="reports")
    findings: Mapped[list["Finding"]] = relationship(back_populates="report")


class Finding(Base):
    """分析报告中的单条问题发现，细化到具体维度（效率/安全/成本/错误）和严重程度。"""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("analysis_reports.id"))
    dimension: Mapped[str]  # efficiency/security/cost/error
    skill_name: Mapped[str | None]  # e.g. "security-analyst" — which skill produced this finding
    severity: Mapped[str]  # critical/major/minor/info
    title: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None]
    line: Mapped[int | None]
    suggestion: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None]
    code_snippet: Mapped[str | None] = mapped_column(Text)
    suggested_code: Mapped[str | None] = mapped_column(Text)

    report: Mapped["AnalysisReport"] = relationship(back_populates="findings")


class FailureDiagnosis(Base):
    """AI-generated diagnosis for a single failed CI run (issue #35).

    Natural key: (repo_id, run_id, run_attempt, tier). Uses repo_id FK but
    intentionally does NOT reference ci_runs yet — that table lands with
    issue #36 and this model must work standalone in v1.

    针对单次失败 CI Run 的 AI 诊断结果。
    tier 区分诊断深度（"default" 快速 / "deep" 深度），同一 run 在不同 tier 下可各存一条。
    error_signature 是去噪后的错误哈希，用于跨 run 聚类相同根因，避免重复调用 LLM。
    故意不外键关联 ci_runs 表（该表尚未落地），保证本模型可独立运行。
    """

    __tablename__ = "failure_diagnoses"
    __table_args__ = (
        sqlalchemy.UniqueConstraint("repo_id", "run_id", "run_attempt", "tier", name="uq_diag_run_tier"),
        sqlalchemy.Index("ix_diag_signature_created", "error_signature", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    run_id: Mapped[int] = mapped_column(index=True)  # GitHub workflow_run.id
    run_attempt: Mapped[int] = mapped_column(default=1)
    tier: Mapped[str]  # "default" | "deep"

    category: Mapped[str]  # 9-value enum (see schemas.DiagnoseCategory)
    confidence: Mapped[str]  # high | medium | low
    root_cause: Mapped[str] = mapped_column(Text)
    quick_fix: Mapped[str | None] = mapped_column(Text)
    failing_step: Mapped[str | None]
    workflow: Mapped[str]
    error_excerpt: Mapped[str] = mapped_column(Text)
    error_signature: Mapped[str]  # 12-char hash for clustering

    model: Mapped[str]
    cost_usd: Mapped[float | None]
    source: Mapped[str] = mapped_column(default="manual")  # manual | webhook_auto
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), index=True)
