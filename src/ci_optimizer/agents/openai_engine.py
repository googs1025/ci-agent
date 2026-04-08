"""OpenAI-compatible engine — runs analysis via OpenAI chat completions API."""

import asyncio
import json
import logging
import time

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

from ci_optimizer.agents.prompts import (
    LANGUAGE_INSTRUCTIONS,
    ORCHESTRATOR_PROMPT,
)
from ci_optimizer.agents.efficiency import EFFICIENCY_PROMPT
from ci_optimizer.agents.security import SECURITY_PROMPT
from ci_optimizer.agents.cost import COST_PROMPT
from ci_optimizer.agents.errors import ERRORS_PROMPT
from ci_optimizer.config import AgentConfig
from ci_optimizer.prefetch import AnalysisContext


SPECIALISTS = {
    "efficiency": EFFICIENCY_PROMPT,
    "security": SECURITY_PROMPT,
    "cost": COST_PROMPT,
    "error": ERRORS_PROMPT,
}


def _build_context_text(ctx: AnalysisContext) -> str:
    """Build context description for the LLM."""
    parts = [f"Repository: {ctx.owner}/{ctx.repo}" if ctx.owner else f"Path: {ctx.local_path}"]
    parts.append(f"Workflow files ({len(ctx.workflow_files)}):")
    for wf in ctx.workflow_files:
        parts.append(f"  - {wf.name}")

    # Read workflow files content
    for wf in ctx.workflow_files:
        try:
            content = wf.read_text()
            parts.append(f"\n--- {wf.name} ---\n{content}")
        except OSError:
            pass

    # Read usage stats
    if ctx.usage_stats_json_path and ctx.usage_stats_json_path.exists():
        try:
            stats = ctx.usage_stats_json_path.read_text()
            parts.append(f"\n--- Usage Statistics ---\n{stats}")
        except OSError:
            pass

    # Read jobs data (summarized)
    if ctx.jobs_json_path and ctx.jobs_json_path.exists():
        try:
            jobs_text = ctx.jobs_json_path.read_text()
            # Truncate if too large
            if len(jobs_text) > 30000:
                jobs_text = jobs_text[:30000] + "\n... (truncated)"
            parts.append(f"\n--- Jobs Data ---\n{jobs_text}")
        except OSError:
            pass

    # Read failure logs
    if ctx.logs_json_path and ctx.logs_json_path.exists():
        try:
            logs_text = ctx.logs_json_path.read_text()
            if len(logs_text) > 20000:
                logs_text = logs_text[:20000] + "\n... (truncated)"
            parts.append(f"\n--- Failure Logs ---\n{logs_text}")
        except OSError:
            pass

    return "\n".join(parts)


async def _call_specialist(
    client: AsyncOpenAI,
    model: str,
    specialist_prompt: str,
    context_text: str,
    language: str,
) -> str:
    """Call a single specialist and return its response via streaming."""
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])

    # Use streaming to work around proxies that return content:null in non-stream mode
    collected: list[str] = []
    stream = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": specialist_prompt + lang_instruction},
            {"role": "user", "content": context_text},
        ],
        temperature=0.2,
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                collected.append(delta.content)

    return "".join(collected)


async def run_analysis_openai(
    ctx: AnalysisContext, config: AgentConfig
) -> "AnalysisResult":
    """Run analysis using OpenAI-compatible API with parallel specialist calls."""
    from ci_optimizer.agents.orchestrator import AnalysisResult, _parse_result

    start_time = time.time()

    client = AsyncOpenAI(
        api_key=config.openai_api_key,
        base_url=config.base_url,
    )

    context_text = _build_context_text(ctx)
    model = config.model
    language = config.language

    # Step 1: Run all 4 specialists in parallel
    logger.info(f"Starting 4 specialist analyses with model={model}, language={language}")

    async def _run_specialist(name: str, prompt: str) -> tuple[str, str]:
        try:
            result = await _call_specialist(client, model, prompt, context_text, language)
            logger.info(f"Specialist {name} returned {len(result)} chars")
            return name, result
        except Exception as e:
            logger.error(f"Specialist {name} failed: {e}")
            return name, json.dumps({
                "findings": [{
                    "severity": "info",
                    "title": f"Analysis failed for {name}",
                    "description": str(e),
                    "file": "",
                    "suggestion": "Check API configuration",
                    "impact": "N/A",
                }]
            })

    results = await asyncio.gather(
        *[_run_specialist(name, prompt) for name, prompt in SPECIALISTS.items()]
    )
    specialist_results = dict(results)

    # Step 2: Orchestrator synthesizes all results
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])
    synthesis_prompt = (
        ORCHESTRATOR_PROMPT + lang_instruction +
        "\n\nSynthesize the following specialist reports into a unified analysis. "
        "Output ONLY the JSON object described above."
    )

    specialist_summary = "\n\n".join(
        f"=== {name.upper()} ANALYST REPORT ===\n{report}"
        for name, report in specialist_results.items()
    )

    logger.info(f"Synthesizing {len(specialist_results)} specialist reports ({len(specialist_summary)} chars)")

    try:
        collected: list[str] = []
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": synthesis_prompt},
                {"role": "user", "content": specialist_summary},
            ],
            temperature=0.1,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    collected.append(delta.content)
        raw_report = "".join(collected)
        logger.info(f"Synthesis returned {len(raw_report)} chars")
    except Exception as e:
        logger.error(f"Synthesis failed: {e}, using fallback combine")
        raw_report = _fallback_combine(specialist_results)

    # Log parse result
    summary, findings, stats = _parse_result(raw_report)
    logger.info(f"Parsed: {len(findings)} findings, stats={stats}")

    if not findings:
        # If synthesis didn't produce findings, try fallback combine
        logger.warning("No findings from synthesis, trying fallback combine from specialist results")
        fallback = _fallback_combine(specialist_results)
        fb_summary, fb_findings, fb_stats = _parse_result(fallback)
        if fb_findings:
            summary = fb_summary if not summary else summary
            findings = fb_findings
            stats = fb_stats
            raw_report = fallback
            logger.info(f"Fallback produced {len(findings)} findings")

    duration_ms = int((time.time() - start_time) * 1000)

    return AnalysisResult(
        executive_summary=summary,
        findings=findings,
        stats=stats,
        raw_report=raw_report,
        duration_ms=duration_ms,
    )


def _fallback_combine(specialist_results: dict[str, str]) -> str:
    """Combine specialist results without orchestrator synthesis."""
    all_findings = []
    for dim_name, report_text in specialist_results.items():
        try:
            json_start = report_text.find("{")
            json_end = report_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(report_text[json_start:json_end])
                for f in data.get("findings", []):
                    f.setdefault("dimension", dim_name)
                    all_findings.append(f)
        except (json.JSONDecodeError, ValueError):
            pass

    result = {
        "executive_summary": "Combined analysis from all specialists.",
        "dimensions": {},
        "stats": {
            "total_findings": len(all_findings),
            "critical": sum(1 for f in all_findings if f.get("severity") == "critical"),
            "major": sum(1 for f in all_findings if f.get("severity") == "major"),
            "minor": sum(1 for f in all_findings if f.get("severity") == "minor"),
            "info": sum(1 for f in all_findings if f.get("severity") == "info"),
        },
    }

    for dim in ("efficiency", "security", "cost", "error"):
        result["dimensions"][dim] = {
            "findings": [f for f in all_findings if f.get("dimension") == dim]
        }

    return json.dumps(result)
