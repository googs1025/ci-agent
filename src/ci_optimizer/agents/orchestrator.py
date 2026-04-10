"""Orchestrator — routes analysis to the configured engine (Anthropic or OpenAI)."""

import json
import time
from dataclasses import dataclass, field

from ci_optimizer.config import AgentConfig
from ci_optimizer.prefetch import AnalysisContext


@dataclass
class AnalysisResult:
    """Structured result from analysis."""

    executive_summary: str = ""
    findings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    raw_report: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0


def _try_parse_json(raw_text: str) -> dict | None:
    """Try multiple strategies to extract JSON from raw text."""
    # Strategy 1: entire text is JSON
    try:
        return json.loads(raw_text.strip())
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: JSON inside markdown code fence
    import re
    fence_match = re.search(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```", raw_text)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: first { to last } (original approach)
    json_start = raw_text.find("{")
    json_end = raw_text.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        try:
            return json.loads(raw_text[json_start:json_end])
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _parse_result(raw_text: str) -> tuple[str, list[dict], dict]:
    """Parse the orchestrator's output into structured data."""
    try:
        data = _try_parse_json(raw_text)
        if data:

            summary = data.get("executive_summary", "")
            # Handle case where summary is a list of bullet points
            if isinstance(summary, list):
                summary = "\n".join(str(item) for item in summary)
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

    return raw_text, [], {"total_findings": 0}


async def run_analysis(
    ctx: AnalysisContext,
    config: AgentConfig | None = None,
    selected_skills: list[str] | None = None,
) -> AnalysisResult:
    """Run analysis using the configured provider engine.

    Routes to:
      - Anthropic engine (Claude Agent SDK) when provider="anthropic"
      - OpenAI engine (OpenAI SDK) when provider="openai"

    selected_skills: list of dimension names to run, or None for all.
    """
    if config is None:
        config = AgentConfig.load()

    from ci_optimizer.agents.skill_registry import SkillRegistry
    registry = SkillRegistry().load()
    skills = registry.get_active_skills(selected=selected_skills)

    if not skills:
        raise RuntimeError("No active skills found. Check skills/ directory.")

    if config.provider == "openai":
        from ci_optimizer.agents.openai_engine import run_analysis_openai
        return await run_analysis_openai(ctx, config, skills)
    else:
        from ci_optimizer.agents.anthropic_engine import run_analysis_anthropic
        return await run_analysis_anthropic(ctx, config, skills)
