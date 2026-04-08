"""Anthropic engine — runs analysis via Claude Agent SDK."""

import json
import logging
import time

logger = logging.getLogger(__name__)

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
from ci_optimizer.agents.prompts import LANGUAGE_INSTRUCTIONS
from ci_optimizer.agents.security import security_agent
from ci_optimizer.config import AgentConfig
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


def _build_analysis_prompt(ctx: AnalysisContext, language: str = "en") -> str:
    """Build the prompt for the orchestrator with context paths."""
    parts = [
        f"Analyze the CI pipelines in: {ctx.local_path}",
        f"\nWorkflow files ({len(ctx.workflow_files)} found):",
    ]
    for wf in ctx.workflow_files:
        parts.append(f"  - {wf}")

    if ctx.runs_json_path:
        parts.append(f"\nCI run history data: {ctx.runs_json_path}")
    if ctx.jobs_json_path:
        parts.append(f"All jobs data (with step timing, runner labels): {ctx.jobs_json_path}")
    if ctx.usage_stats_json_path:
        parts.append(f"Pre-computed usage statistics: {ctx.usage_stats_json_path}")
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
    parts.append(LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"]))

    return "\n".join(parts)


def _build_agents(config: AgentConfig) -> dict[str, AgentDefinition]:
    """Build agent definitions with model config."""
    if config.model:
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


async def run_analysis_anthropic(
    ctx: AnalysisContext, config: AgentConfig
) -> "AnalysisResult":
    """Run analysis using Claude Agent SDK."""
    from ci_optimizer.agents.orchestrator import AnalysisResult

    prompt = _build_analysis_prompt(ctx, language=config.language)
    start_time = time.time()

    collected_text = []
    result = AnalysisResult()

    agents = _build_agents(config)

    lang_instruction = LANGUAGE_INSTRUCTIONS.get(config.language, LANGUAGE_INSTRUCTIONS["en"])
    system_prompt = ORCHESTRATOR_PROMPT + lang_instruction

    sdk_options = ClaudeAgentOptions(
        system_prompt=system_prompt,
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

    logger.info(f"Starting Anthropic analysis: model={config.model}, lang={config.language}, max_turns={config.max_turns}")
    message_count = 0
    try:
        async for message in query(
            prompt=prompt,
            options=sdk_options,
        ):
            message_count += 1
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        collected_text.append(block.text)
            elif isinstance(message, ResultMessage):
                result.cost_usd = message.total_cost_usd or 0.0
                logger.info(f"Analysis complete: cost=${result.cost_usd}, session={message.session_id}")
    except Exception as e:
        logger.error(f"Agent SDK query failed: {e}", exc_info=True)
        raise RuntimeError(f"Agent SDK analysis failed: {e}") from e

    result.raw_report = "\n".join(collected_text)
    result.duration_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Collected {message_count} messages, {len(collected_text)} text blocks, raw_report={len(result.raw_report)} chars")

    if not result.raw_report.strip():
        raise RuntimeError("Agent returned empty analysis result")

    from ci_optimizer.agents.orchestrator import _parse_result
    summary, findings, stats = _parse_result(result.raw_report)
    result.executive_summary = summary
    result.findings = findings
    result.stats = stats

    return result
