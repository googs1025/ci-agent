"""First-run setup wizard and config review for TUI."""

from __future__ import annotations

import time

import httpx

from ci_optimizer.config import CONFIG_FILE, AgentConfig


def needs_setup() -> bool:
    """Return True if config.json does not exist (first run)."""
    return not CONFIG_FILE.exists()


def mask_key(value: str | None) -> str:
    """Mask a sensitive value for display."""
    if not value:
        return "(未设置)"
    if len(value) > 12:
        return f"{value[:8]}...{value[-4:]}"
    return "***"


async def verify_api(
    provider: str,
    api_key: str,
    model: str,
    base_url: str | None = None,
    anthropic_base_url: str | None = None,
) -> tuple[bool, str]:
    """Send a lightweight API call to verify connectivity.

    Returns (success: bool, message: str).
    """
    try:
        if provider == "openai":
            return await _verify_openai(api_key, model, base_url)
        else:
            return await _verify_anthropic(api_key, model, anthropic_base_url)
    except httpx.ConnectError:
        return False, "网络连接失败，请检查网络或 API 地址"
    except httpx.TimeoutException:
        return False, "请求超时，请检查网络连接"
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 401:
            return False, f"认证失败 (HTTP {code})，请检查 API Key"
        if code == 403:
            return False, f"权限不足 (HTTP {code})，请检查 API Key 权限"
        return False, f"API 错误 (HTTP {code})"
    except Exception as e:
        return False, f"验证失败: {e}"


async def _verify_anthropic(api_key: str, model: str, base_url: str | None) -> tuple[bool, str]:
    url = (base_url or "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        elapsed = time.monotonic() - start
        data = resp.json()
        model_used = data.get("model", model)
        return True, f"{model_used}, 响应 {elapsed:.1f}s"


async def _verify_openai(api_key: str, model: str, base_url: str | None) -> tuple[bool, str]:
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        elapsed = time.monotonic() - start
        data = resp.json()
        model_used = data.get("model", model)
        return True, f"{model_used}, 响应 {elapsed:.1f}s"
