"""Single-run CI failure diagnosis runner.

架构角色：独立的 standalone skill 执行器，专门处理 /api/ci-runs/diagnose 端点的单次故障诊断请求。
核心职责：
  1. 从 SkillRegistry 加载 "failure-triage" skill 的 prompt
  2. 对单条错误日志片段发起一次性 LLM 调用（无工具调用、无并行、无综合步骤）
  3. 解析并严格校验返回的 JSON（category、confidence 枚举值），提供优雅降级而非抛出异常
与其他模块的关系：不经过 orchestrator 调度，直接被 API 路由层调用；
  通过 provider routing（model 名称前缀判断）支持 Anthropic 和 OpenAI 两套 SDK。

Invokes the ``failure-triage`` skill on a single error excerpt and parses
the resulting strict JSON. Unlike the multi-specialist orchestrator, this
is a **one-shot** LLM call — no tool use, no parallelism, no synthesis.

Provider routing:
- Anthropic models (``claude*``) → Anthropic Messages API
- Any other model → OpenAI Chat Completions API (supports OpenAI-compatible endpoints)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ci_optimizer.agents.skill_registry import get_registry
from ci_optimizer.agents.tracing import langfuse_observe
from ci_optimizer.config import AgentConfig

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "flaky_test",
    "timeout",
    "dependency",
    "network",
    "resource_limit",
    "config",
    "build",
    "infra",
    "unknown",
}
VALID_CONFIDENCE = {"high", "medium", "low"}

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class FailureTriageError(Exception):
    """技能不可用或 LLM 调用无法恢复时抛出，区别于可降级的格式解析错误。

    Raised when the skill is unavailable or the LLM call fails irrecoverably.
    """


def _load_prompt() -> str:
    """从注册表获取 failure-triage skill 的 prompt，若首次未找到则强制 reload 后重试。

    reload 重试是为了应对注册表在 skill 文件写入之前已经初始化的竞态场景。
    """
    skill = get_registry().get_skill("failure-triage")
    if skill is None:
        # Try a reload in case the registry was loaded before the skill was created.
        get_registry().reload()
        skill = get_registry().get_skill("failure-triage")
    if skill is None:
        raise FailureTriageError("failure-triage skill not registered")
    return skill.prompt


def _build_user_message(*, workflow: str, failing_step: str | None, excerpt: str) -> str:
    return f"workflow: {workflow}\nfailing_step: {failing_step if failing_step else 'null'}\nexcerpt:\n{excerpt}"


def _parse_diagnosis(raw: str, failing_step: str | None) -> dict[str, Any]:
    """从 LLM 原始响应中提取 JSON，校验枚举字段，返回规范化的诊断结果。

    Extract the JSON object, validate enums, return a clean dict.
    Falls back to category=unknown / confidence=low on malformed output so
    callers always get a usable response.

    root_cause 截断至 300 字符、quick_fix 截断至 500 字符，防止异常长输出污染 API 响应。
    """
    match = _JSON_OBJECT_RE.search(raw.strip())
    if not match:
        logger.warning("failure-triage: no JSON object in response (%d chars)", len(raw))
        return {
            "category": "unknown",
            "confidence": "low",
            "root_cause": "Model did not return a parseable diagnosis",
            "quick_fix": None,
            "failing_step": failing_step,
        }

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        logger.warning("failure-triage: JSON decode error: %s", e)
        return {
            "category": "unknown",
            "confidence": "low",
            "root_cause": "Model returned malformed JSON",
            "quick_fix": None,
            "failing_step": failing_step,
        }

    category = parsed.get("category", "unknown")
    if category not in VALID_CATEGORIES:
        category = "unknown"

    confidence = parsed.get("confidence", "low")
    if confidence not in VALID_CONFIDENCE:
        confidence = "low"

    root_cause = str(parsed.get("root_cause") or "No root cause identified")[:300]

    quick_fix = parsed.get("quick_fix")
    if quick_fix is not None:
        quick_fix = str(quick_fix)[:500] or None

    return {
        "category": category,
        "confidence": confidence,
        "root_cause": root_cause,
        "quick_fix": quick_fix,
        "failing_step": failing_step,
    }


async def _call_anthropic(
    prompt: str,
    user_message: str,
    model: str,
    config: AgentConfig,
) -> tuple[str, float | None]:
    """向 Anthropic Messages API 发起单次调用，返回 (原始文本, 估算费用)。

    Single Anthropic Messages API call. Returns (raw_text, cost_usd).
    使用低 temperature（0.1）以获得稳定、可重复的诊断结果。
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as e:
        raise FailureTriageError("anthropic SDK not installed") from e

    client = AsyncAnthropic(api_key=config.anthropic_api_key)
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=800,
            temperature=0.1,
            system=prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        text = "".join(parts)
        # Anthropic SDK exposes usage but not cost; caller may compute via Langfuse.
        # Anthropic SDK exposes usage but not cost; caller may compute via Langfuse.
        # 此处基于内置价格表做本地估算，Langfuse 可提供更精确的追踪数据
        cost = _estimate_anthropic_cost(model, resp.usage.input_tokens, resp.usage.output_tokens)
        return text, cost
    finally:
        await client.close()


async def _call_openai(
    prompt: str,
    user_message: str,
    model: str,
    config: AgentConfig,
) -> tuple[str, float | None]:
    """Single OpenAI Chat Completions API call (also works with OpenAI-compatible endpoints)."""
    try:
        from openai import AsyncOpenAI
    except ImportError as e:
        raise FailureTriageError("openai SDK not installed") from e

    client = AsyncOpenAI(api_key=config.openai_api_key, base_url=config.base_url)
    try:
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=800,
            temperature=0.1,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
        )
        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content or "") if choice else ""
        cost = _estimate_openai_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens) if resp.usage else None
        return text, cost
    finally:
        await client.close()


# 粗略费用估算表（美元/百万 token），未知模型返回 None 而非猜测。
# Rough cost table (USD per 1M tokens). Undercounts on unknown models by returning None.
_ANTHROPIC_PRICES = {
    # (input, output) per 1M tokens
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
}

_OPENAI_PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.0),
}


def _estimate_anthropic_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = _ANTHROPIC_PRICES.get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


def _estimate_openai_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = _OPENAI_PRICES.get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


@langfuse_observe(name="failure-triage")
async def diagnose(
    *,
    excerpt: str,
    failing_step: str | None,
    workflow: str,
    model: str,
    config: AgentConfig,
) -> dict[str, Any]:
    """对单条 CI 错误日志片段执行故障诊断，是本模块对外暴露的唯一公共接口。

    Run the failure-triage skill on a single error excerpt.

    Returns a dict with keys:
        category, confidence, root_cause, quick_fix, failing_step,
        model, cost_usd

    The ``category`` and ``confidence`` fields are always validated against
    their enums; malformed LLM output degrades to ``unknown`` / ``low`` rather
    than raising.

    通过 model 名称前缀（"claude" 开头）选择 provider，避免暴露额外配置项。
    """
    if not excerpt.strip():
        raise FailureTriageError("empty excerpt — nothing to diagnose")

    prompt = _load_prompt()
    user_message = _build_user_message(workflow=workflow, failing_step=failing_step, excerpt=excerpt)

    if model.startswith("claude"):
        raw, cost = await _call_anthropic(prompt, user_message, model, config)
    else:
        raw, cost = await _call_openai(prompt, user_message, model, config)

    logger.info("failure-triage: model=%s, raw_len=%d, cost_usd=%s", model, len(raw), cost)

    result = _parse_diagnosis(raw, failing_step)
    result["model"] = model
    result["cost_usd"] = cost
    return result
