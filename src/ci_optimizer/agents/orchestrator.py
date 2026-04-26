"""Orchestrator — routes analysis to the configured engine (Anthropic or OpenAI).

架构角色：agents 层的入口调度器，负责将分析请求路由到正确的引擎（Anthropic 或 OpenAI）。
核心职责：
  1. 从 SkillRegistry 获取当前激活的技能列表
  2. 根据 AgentConfig.provider 分发到 anthropic_engine 或 openai_engine
  3. 定义通用数据结构 AnalysisResult，以及 JSON 解析工具函数
与其他模块的关系：被上层 API 路由（FastAPI handler）调用；引擎层（anthropic/openai_engine）
  反向导入 AnalysisResult 和 _parse_result 以填充并返回统一的结果对象。
"""

import json
from dataclasses import dataclass, field

from ci_optimizer.agents.tracing import langfuse_observe
from ci_optimizer.config import AgentConfig
from ci_optimizer.prefetch import AnalysisContext


@dataclass
class AnalysisResult:
    """跨引擎统一的分析结果结构。

    由 anthropic_engine 或 openai_engine 填充并返回给上层调用者。
    findings 是所有 specialist 产出的扁平化 finding 列表，每条已注入 dimension 字段。
    """

    executive_summary: str = ""
    findings: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    raw_report: str = ""
    duration_ms: int = 0
    cost_usd: float = 0.0


def _try_parse_json(raw_text: str) -> dict | None:
    """尝试多种策略从 LLM 原始输出中提取 JSON 对象。

    LLM 输出格式不稳定（裸 JSON / Markdown 代码块 / 混合文本），
    此函数按优先级依次尝试三种解析方式，降低因格式差异导致的解析失败率。
    """
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


def _parse_result(
    raw_text: str,
    dimension_to_skill: dict[str, str] | None = None,
) -> tuple[str, list[dict], dict]:
    """将 orchestrator 的原始输出解析为结构化数据三元组 (summary, findings, stats)。

    dimension_to_skill: optional mapping from dimension name to skill name,
    used to tag each finding with the skill that produced it. Callers can
    build this from the active skills list.

    解析失败时优雅降级：返回 (raw_text, [], {"total_findings": 0})，
    不抛出异常，确保 API 层始终得到可用响应。
    """
    dim_map = dimension_to_skill or {}
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
                    # Tag the finding with the skill that produced it
                    if "skill_name" not in f and dim_name in dim_map:
                        f["skill_name"] = dim_map[dim_name]
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


@langfuse_observe(name="ci-analysis")
async def run_analysis(
    ctx: AnalysisContext,
    config: AgentConfig | None = None,
    selected_skills: list[str] | None = None,
) -> AnalysisResult:
    """执行 CI 分析的顶层入口，按配置的 provider 路由到对应引擎。

    Routes to:
      - Anthropic engine (Claude Agent SDK) when provider="anthropic"
      - OpenAI engine (OpenAI SDK) when provider="openai"

    selected_skills: list of dimension names to run, or None for all.

    此函数是 Langfuse 追踪的根 span，所有子引擎的调用都将挂载在该 trace 下。
    """
    if config is None:
        config = AgentConfig.load()

    from ci_optimizer.agents.skill_registry import get_registry

    registry = get_registry()
    skills = registry.get_active_skills(selected=selected_skills)

    if not skills:
        raise RuntimeError("No active skills found. Check skills/ directory.")

    if config.provider == "openai":
        from ci_optimizer.agents.openai_engine import run_analysis_openai

        return await run_analysis_openai(ctx, config, skills)
    else:
        from ci_optimizer.agents.anthropic_engine import run_analysis_anthropic

        return await run_analysis_anthropic(ctx, config, skills)
