"""Anthropic engine — runs analysis via Claude Agent SDK."""

import json
import logging
import time
from typing import TYPE_CHECKING

from ci_optimizer.agents.tracing import flush as _langfuse_flush
from ci_optimizer.agents.tracing import langfuse_observe

logger = logging.getLogger(__name__)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from ci_optimizer.agents.prompts import LANGUAGE_INSTRUCTIONS
from ci_optimizer.config import AgentConfig
from ci_optimizer.prefetch import AnalysisContext

if TYPE_CHECKING:
    from ci_optimizer.agents.skill_registry import Skill


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
    if ctx.action_shas_json_path:
        parts.append(f"Resolved action SHAs (use these in suggested_code, not placeholders): {ctx.action_shas_json_path}")

    if ctx.owner and ctx.repo:
        parts.append(f"\nRepository: {ctx.owner}/{ctx.repo}")

    if ctx.filters:
        filter_desc = ctx.filters.to_dict()
        if filter_desc:
            parts.append(f"\nApplied filters: {json.dumps(filter_desc)}")

    parts.append("\nPlease dispatch all specialist agents to analyze these files, then produce the unified report.")
    parts.append(LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"]))

    return "\n".join(parts)


@langfuse_observe(name="anthropic-analysis")
async def run_analysis_anthropic(ctx: AnalysisContext, config: AgentConfig, skills: "list[Skill]") -> "AnalysisResult":
    """Run analysis using Claude Agent SDK with dynamically loaded skills."""
    from ci_optimizer.agents.orchestrator import AnalysisResult
    from ci_optimizer.agents.skill_registry import SkillRegistry

    # Build agents from skills
    agents = {s.name: s.to_agent_definition(config.model) for s in skills}

    # Build orchestrator prompt dynamically
    registry = SkillRegistry()
    orchestrator_prompt = registry.build_orchestrator_prompt(skills)

    prompt = _build_analysis_prompt(ctx, language=config.language)
    start_time = time.time()

    collected_text = []
    result = AnalysisResult()

    lang_instruction = LANGUAGE_INSTRUCTIONS.get(config.language, LANGUAGE_INSTRUCTIONS["en"])
    system_prompt = orchestrator_prompt + lang_instruction

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

    logger.info(
        f"Starting Anthropic analysis: model={config.model}, lang={config.language}, "
        f"max_turns={config.max_turns}, skills={[s.name for s in skills]}"
    )
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

    dim_to_skill = {s.dimension: s.name for s in skills}
    summary, findings, stats = _parse_result(result.raw_report, dim_to_skill)
    result.executive_summary = summary
    result.findings = findings
    result.stats = stats

    _langfuse_flush()
    return result
