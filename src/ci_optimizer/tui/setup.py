"""First-run setup wizard and config review for TUI."""

from __future__ import annotations

import time

import httpx
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel

from ci_optimizer.config import CONFIG_DIR, CONFIG_FILE, DEFAULT_MODEL, AgentConfig


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


async def run_setup_wizard(console: Console) -> AgentConfig:
    """Run the full first-time setup wizard. Returns configured AgentConfig."""
    console.print(
        Panel(
            "[bold]首次使用，需要进行初始配置[/bold]",
            title="ci-agent Setup",
            border_style="cyan",
        )
    )
    console.print()

    session = PromptSession()
    config = AgentConfig()

    # 1. Provider
    console.print("[bold]1. AI 引擎[/bold]")
    console.print("   [1] Anthropic (Claude)")
    console.print("   [2] OpenAI (兼容)")
    choice = (await session.prompt_async("   请选择 [1]: ")).strip() or "1"
    config.provider = "openai" if choice == "2" else "anthropic"
    console.print()

    # 2. API Key
    console.print("[bold]2. API Key[/bold]")
    if config.provider == "anthropic":
        key = (await session.prompt_async("   请输入 Anthropic API Key: ", is_password=True)).strip()
        if key:
            config.anthropic_api_key = key
    else:
        key = (await session.prompt_async("   请输入 OpenAI API Key: ", is_password=True)).strip()
        if key:
            config.openai_api_key = key
        console.print("   [dim]如需自定义 Base URL，请稍后通过 ci-agent config set base_url <url> 设置[/dim]")
    console.print()

    # 3. GitHub Token
    console.print("[bold]3. GitHub Token[/bold] [dim](用于拉取 CI 数据，回车跳过)[/dim]")
    token = (await session.prompt_async("   请输入 GitHub Token: ", is_password=True)).strip()
    if token:
        config.github_token = token
    else:
        config.github_token = None
    console.print()

    # 4. Model
    default_model = DEFAULT_MODEL if config.provider == "anthropic" else "gpt-4o"
    console.print(f"[bold]4. 模型[/bold] [dim](默认: {default_model})[/dim]")
    model = (await session.prompt_async("   请输入模型名称 (回车使用默认): ")).strip()
    config.model = model if model else default_model
    console.print()

    # 5. Language
    console.print("[bold]5. 输出语言[/bold]")
    console.print("   [1] English")
    console.print("   [2] 中文")
    lang_choice = (await session.prompt_async("   请选择 [1]: ")).strip() or "1"
    config.language = "zh" if lang_choice == "2" else "en"
    console.print()

    # Save
    config.save()
    console.print(f"[green]✓ 配置已保存到 {CONFIG_FILE}[/green]")
    console.print()

    # Verify
    await _run_verify(console, config)

    return config


async def _run_verify(console: Console, config: AgentConfig) -> None:
    """Run API verification and print result."""
    api_key = config.get_api_key()
    if not api_key:
        console.print("[yellow]⚠ 未设置 API Key，跳过连通性验证[/yellow]")
        return

    console.print("[dim]⠸ 正在验证 API 连通性...[/dim]")
    ok, msg = await verify_api(
        provider=config.provider,
        api_key=api_key,
        model=config.model,
        base_url=config.base_url,
        anthropic_base_url=config.anthropic_base_url,
    )
    if ok:
        console.print(f"[green]✓ API 连通正常 ({msg})[/green]")
    else:
        console.print(f"[red]✗ API 验证失败: {msg}[/red]")
        console.print("[dim]  可稍后通过 /model 或 ci-agent config set 修改配置[/dim]")
    console.print()
