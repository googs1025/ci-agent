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


def _parse_result(raw_text: str) -> tuple[str, list[dict], dict]:
    """Parse the orchestrator's output into structured data."""
    try:
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

    return raw_text, [], {"total_findings": 0}


async def run_analysis(
    ctx: AnalysisContext, config: AgentConfig | None = None
) -> AnalysisResult:
    """Run analysis using the configured provider engine.

    Routes to:
      - Anthropic engine (Claude Agent SDK) when provider="anthropic"
      - OpenAI engine (OpenAI SDK) when provider="openai"
    """
    if config is None:
        config = AgentConfig.load()

    if config.provider == "openai":
        from ci_optimizer.agents.openai_engine import run_analysis_openai
        return await run_analysis_openai(ctx, config)
    else:
        from ci_optimizer.agents.anthropic_engine import run_analysis_anthropic
        return await run_analysis_anthropic(ctx, config)
