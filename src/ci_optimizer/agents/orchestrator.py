"""Orchestrator agent — coordinates specialist agents and synthesizes results."""

import asyncio
import json
import time
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AgentDefinition,
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from ci_optimizer.agents.cost import cost_agent
from ci_optimizer.agents.efficiency import efficiency_agent
from ci_optimizer.agents.errors import error_agent
from ci_optimizer.agents.security import security_agent
from ci_optimizer.config import AgentConfig
from ci_optimizer.filters import AnalysisFilters
from ci_optimizer.prefetch import AnalysisContext

ORCHESTRATOR_PROMPT = """You are a CI pipeline analysis orchestrator. Your role is to coordinate 4 specialist agents to produce a comprehensive analysis report.

## Your Workflow

1. Call ALL 4 specialist agents to analyze the CI pipeline:
   - **efficiency-analyst**: Execution efficiency (parallelization, caching, matrix optimization)
   - **security-analyst**: Security vulnerabilities and best practices
   - **cost-analyst**: Cost optimization (billable minutes, runner selection)
   - **error-analyst**: Failure patterns and reliability issues

2. After receiving all 4 specialist reports, synthesize them into a unified analysis.

3. Produce your final output as a JSON object with this structure:

```json
{
  "executive_summary": "Top 5 most impactful recommendations across all dimensions, ordered by priority",
  "dimensions": {
    "efficiency": { "findings": [...] },
    "security": { "findings": [...] },
    "cost": { "findings": [...] },
    "error": { "findings": [...] }
  },
  "stats": {
    "total_findings": 0,
    "critical": 0,
    "major": 0,
    "minor": 0,
    "info": 0
  }
}
```

## Important

- Call all 4 specialists. Do not skip any dimension.
- Each specialist will return findings in JSON format. Include them as-is in the dimensions section.
- The executive_summary should identify cross-cutting themes and prioritize the TOP 5 actions by impact.
- Add a "dimension" field to each finding if not already present.
"""

AGENTS = {
    "efficiency-analyst": efficiency_agent,
    "security-analyst": security_agent,
    "cost-analyst": cost_agent,
    "error-analyst": error_agent,
}


@dataclass
class AnalysisResult:
    """Structured result from the orchestrator analysis."""

    executive_summary: str = ""
    findings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    raw_report: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0


def _build_analysis_prompt(ctx: AnalysisContext) -> str:
    """Build the prompt for the orchestrator with context paths."""
    parts = [
        f"Analyze the CI pipelines in: {ctx.local_path}",
        f"\nWorkflow files ({len(ctx.workflow_files)} found):",
    ]
    for wf in ctx.workflow_files:
        parts.append(f"  - {wf}")

    if ctx.runs_json_path:
        parts.append(f"\nCI run history data: {ctx.runs_json_path}")
    if ctx.logs_json_path:
        parts.append(f"Failure logs data: {ctx.logs_json_path}")
    if ctx.workflows_json_path:
        parts.append(f"Workflow definitions: {ctx.workflows_json_path}")

    if ctx.owner and ctx.repo:
        parts.append(f"\nRepository: {ctx.owner}/{ctx.repo}")

    if ctx.filters:
        filter_desc = ctx.filters.to_dict()
        if filter_desc:
            parts.append(f"\nApplied filters: {json.dumps(filter_desc)}")

    parts.append(
        "\nPlease dispatch all 4 specialist agents to analyze these files, "
        "then produce the unified report."
    )

    return "\n".join(parts)


def _parse_result(raw_text: str) -> tuple[str, list[dict], dict]:
    """Parse the orchestrator's output into structured data."""
    # Try to extract JSON from the response
    try:
        # Find JSON block in the text
        json_start = raw_text.find("{")
        json_end = raw_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            data = json.loads(raw_text[json_start:json_end])

            summary = data.get("executive_summary", "")
            findings = []
            dimensions = data.get("dimensions", {})
            for dim_name, dim_data in dimensions.items():
                for f in dim_data.get("findings", []):
                    f.setdefault("dimension", dim_name)
                    findings.append(f)

            stats = data.get("stats", {})
            if not stats:
                stats = {
                    "total_findings": len(findings),
                    "critical": sum(1 for f in findings if f.get("severity") == "critical"),
                    "major": sum(1 for f in findings if f.get("severity") == "major"),
                    "minor": sum(1 for f in findings if f.get("severity") == "minor"),
                    "info": sum(1 for f in findings if f.get("severity") == "info"),
                }

            return summary, findings, stats
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: return raw text as summary
    return raw_text, [], {"total_findings": 0}


def _build_agents(config: AgentConfig | None = None) -> dict[str, AgentDefinition]:
    """Build agent definitions, optionally applying model config to sub-agents."""
    if config and config.model:
        return {
            name: AgentDefinition(
                description=agent.description,
                prompt=agent.prompt,
                tools=agent.tools,
                model=config.model,
            )
            for name, agent in AGENTS.items()
        }
    return AGENTS


async def run_analysis(
    ctx: AnalysisContext, config: AgentConfig | None = None
) -> AnalysisResult:
    """Run the full orchestrator analysis pipeline."""
    if config is None:
        config = AgentConfig.load()

    prompt = _build_analysis_prompt(ctx)
    start_time = time.time()

    collected_text = []
    result = AnalysisResult()

    agents = _build_agents(config)

    sdk_options = ClaudeAgentOptions(
        system_prompt=ORCHESTRATOR_PROMPT,
        allowed_tools=["Agent"],
        agents=agents,
        cwd=str(ctx.local_path),
        max_turns=config.max_turns,
    )

    if config.model:
        sdk_options.model = config.model
    if config.fallback_model:
        sdk_options.fallback_model = config.fallback_model

    sdk_env = config.get_sdk_env()
    if sdk_env:
        sdk_options.env = sdk_env

    async for message in query(
        prompt=prompt,
        options=sdk_options,
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    collected_text.append(block.text)
        elif isinstance(message, ResultMessage):
            result.cost_usd = message.total_cost_usd or 0.0

    result.raw_report = "\n".join(collected_text)
    result.duration_ms = int((time.time() - start_time) * 1000)

    summary, findings, stats = _parse_result(result.raw_report)
    result.executive_summary = summary
    result.findings = findings
    result.stats = stats

    return result
