"""Pydantic request/response schemas for the API."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


class FilterSchema(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    workflows: list[str] | None = None
    status: list[str] | None = None
    branches: list[str] | None = None


class AgentConfigSchema(BaseModel):
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


class DashboardResponse(BaseModel):
    repo_count: int
    analysis_count: int
    severity_distribution: dict[str, int]
    dimension_distribution: dict[str, int]
    recent_reports: list[ReportSummary]
