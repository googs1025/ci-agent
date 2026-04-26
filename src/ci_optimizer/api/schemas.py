"""Pydantic request/response schemas for the API."""
# ── 架构角色 ──────────────────────────────────────────────────────────────────
# 本文件是 API 层的数据合约，所有请求体和响应体的 Pydantic 模型都在此定义。
# 结构分为三组：
#   - 分析相关（FilterSchema / AgentConfigSchema / AnalyzeRequest / Report* / Dashboard*）
#   - Skill 管理（SkillSchema / SkillImportRequest / SkillImportResponse）
#   - 失败诊断（DiagnoseRequest / DiagnoseResponse / SignatureClusterResponse / FailedRunSummary）
# schemas 只做数据验证，不含业务逻辑；routes.py / diagnose.py 负责将其转换为内部对象。

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class FilterSchema(BaseModel):
    """分析过滤条件：时间范围、workflow 名、运行状态、分支，均为可选。"""

    since: datetime | None = None
    until: datetime | None = None
    workflows: list[str] | None = None
    status: list[str] | None = None
    branches: list[str] | None = None


class AgentConfigSchema(BaseModel):
    """Agent 配置的可选覆盖项，用于 POST /analyze 的 per-request 覆盖，以及 PUT /config 的全局更新。
    所有字段均可选，None 表示"不覆盖，保留现有配置"。
    """

    provider: str | None = None  # "anthropic" or "openai"
    model: str | None = None
    fallback_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    github_token: str | None = None
    base_url: str | None = None
    max_turns: int | None = None
    language: str | None = None  # "en" or "zh"


class AnalyzeRequest(BaseModel):
    repo: str  # local path or GitHub URL
    filters: FilterSchema | None = None
    agent_config: AgentConfigSchema | None = None  # per-request overrides
    skills: list[str] | None = None  # dimension names to run, None = all


class FindingSchema(BaseModel):
    """单条分析发现的完整字段，用于 GET /reports/{id} 的响应体。"""

    id: int
    dimension: str
    skill_name: str | None = None  # which skill produced this finding
    severity: str
    title: str
    description: str
    file_path: str | None = None
    line: int | None = None
    suggestion: str | None = None
    impact: str | None = None
    code_snippet: str | None = None
    suggested_code: str | None = None

    @field_validator("line", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v):
        """Accept empty strings / whitespace / the literal 'null' as None.

        The LLM sometimes omits the line number or writes '' or 'null' in the
        JSON payload; older DB rows have these values. Coerce to None so the
        API does not fail with HTTP 500 when serving old reports.
        LLM 偶尔在 JSON 中写出空字符串或字面量 'null'，这里做兼容处理，避免旧报告导致 500。
        """
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s == "" or s.lower() == "null":
                return None
            try:
                return int(s)
            except ValueError:
                return None
        return v


class ReportSummary(BaseModel):
    id: int
    repo_owner: str | None = None
    repo_name: str | None = None
    created_at: datetime
    status: str
    finding_count: int = 0
    duration_ms: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ReportDetail(BaseModel):
    id: int
    repo_owner: str | None = None
    repo_name: str | None = None
    created_at: datetime
    status: str
    summary_md: str | None = None
    full_report_json: str | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    findings: list[FindingSchema] = []

    model_config = ConfigDict(from_attributes=True)


class ReportListResponse(BaseModel):
    reports: list[ReportSummary]
    total: int
    page: int
    limit: int


class RepositorySchema(BaseModel):
    id: int
    owner: str
    repo: str
    url: str | None = None
    last_analyzed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SkillSchema(BaseModel):
    """Skill definition exposed via API."""

    name: str
    description: str
    dimension: str
    source: str  # "builtin" or "user"
    enabled: bool
    priority: int
    tools: list[str]
    requires_data: list[str]
    prompt: str = ""  # full prompt body (for the detail drawer)


class SkillImportRequest(BaseModel):
    """Request body for POST /skills/import."""

    source_type: Literal["claude-code", "opencode", "path", "github"]
    source: str  # skill name (claude-code/opencode), dir path, or repo URL
    dimension: str
    requires_data: list[str] | None = None
    name_override: str | None = None


class SkillImportResponse(BaseModel):
    name: str
    dimension: str
    target_path: str
    source_kind: str
    warnings: list[str]


class DashboardResponse(BaseModel):
    repo_count: int
    analysis_count: int
    severity_distribution: dict[str, int]
    dimension_distribution: dict[str, int]
    recent_reports: list[ReportSummary]


class DailySeverityPoint(BaseModel):
    date: str
    total: int
    critical: int
    major: int
    minor: int
    info: int


class DimensionTrendPoint(BaseModel):
    date: str
    efficiency: int
    security: int
    cost: int
    errors: int


class RepoComparisonItem(BaseModel):
    repo: str
    total: int
    critical: int
    major: int
    minor: int
    info: int


class TrendsResponse(BaseModel):
    daily_scores: list[DailySeverityPoint]
    dimension_trends: list[DimensionTrendPoint]
    repo_comparison: list[RepoComparisonItem]


# ── Failure Triage (issue #35) ───────────────────────────────────────────────

DiagnoseCategory = Literal[
    "flaky_test",
    "timeout",
    "dependency",
    "network",
    "resource_limit",
    "config",
    "build",
    "infra",
    "unknown",
]

DiagnoseConfidence = Literal["high", "medium", "low"]

DiagnoseTier = Literal["default", "deep"]


class DiagnoseRequest(BaseModel):
    """POST /ci-runs/diagnose 的请求体。tier 控制使用轻量还是深度分析模型。"""

    repo: str  # "owner/name"
    run_id: int  # GitHub workflow_run.id
    run_attempt: int = 1
    tier: DiagnoseTier = "default"


class DiagnoseResponse(BaseModel):
    """诊断结果响应体。cached=True 表示命中了精确缓存或签名缓存（未产生新 LLM 费用）。"""

    category: DiagnoseCategory
    confidence: DiagnoseConfidence
    root_cause: str
    quick_fix: str | None
    failing_step: str | None
    error_excerpt: str
    error_signature: str
    workflow: str
    model: str
    cost_usd: float | None
    cached: bool = False
    # How the diagnosis was produced: fresh / exact-cache / signature-cache / webhook
    source: Literal["manual", "webhook_auto"] = "manual"


class DiagnoseSiblingRun(BaseModel):
    """One entry in the signature cluster list."""

    repo: str
    run_id: int
    run_attempt: int
    workflow: str
    failing_step: str | None
    created_at: datetime


class SignatureClusterResponse(BaseModel):
    signature: str
    count: int
    days: int
    category: DiagnoseCategory | None
    runs: list[DiagnoseSiblingRun]


class FailedRunSummary(BaseModel):
    """A single failed GitHub workflow run, shown in the diagnose picker."""

    run_id: int
    run_attempt: int
    workflow: str
    branch: str | None
    event: str | None
    created_at: datetime | None
    html_url: str | None
    actor: str | None
