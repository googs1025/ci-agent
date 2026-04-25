# TUI Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-run setup wizard to `ci-agent chat` that guides users through initial configuration (provider, API key, GitHub token, model, language) and validates API connectivity on every startup.

**Architecture:** A new `src/ci_optimizer/tui/setup.py` module handles all setup logic. It has three public functions: `needs_setup()` checks if config.json exists, `run_setup_wizard()` runs the full first-time guided flow, and `run_config_review()` shows existing config and lets the user modify items one-by-one. Both flows end with `verify_api()` which sends a lightweight API call to confirm connectivity. The `run_tui()` entry point in `app.py` calls setup before repo confirmation.

**Tech Stack:** Python 3.10+, prompt_toolkit 3.x (async prompts, password input), Rich 13.x (panels, console output), httpx (API test call)

---

## File Map

| Path | Action | Responsibility |
|------|--------|----------------|
| `src/ci_optimizer/tui/setup.py` | Create | Setup wizard: `needs_setup()`, `run_setup_wizard()`, `run_config_review()`, `verify_api()` |
| `src/ci_optimizer/tui/app.py` | Modify | Insert setup call in `run_tui()` before repo confirmation |
| `tests/tui/test_setup.py` | Create | Unit tests for setup logic |
| `docs/guides/zh/tui-guide.md` | Modify | Add setup wizard section to TUI docs |

---

## Task 1: `needs_setup()` and `mask_key()` helpers

**Files:**
- Create: `src/ci_optimizer/tui/setup.py`
- Create: `tests/tui/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/tui/test_setup.py`:

```python
"""Tests for TUI setup wizard logic."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_optimizer.tui.setup import mask_key, needs_setup


def test_needs_setup_no_config_file(tmp_path):
    with patch("ci_optimizer.tui.setup.CONFIG_FILE", tmp_path / "config.json"):
        assert needs_setup() is True


def test_needs_setup_config_exists(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"provider": "anthropic"}))
    with patch("ci_optimizer.tui.setup.CONFIG_FILE", config_file):
        assert needs_setup() is False


def test_mask_key_long():
    assert mask_key("sk-ant-api03-abcdefghij1234") == "sk-ant-a...1234"


def test_mask_key_short():
    assert mask_key("short") == "***"


def test_mask_key_none():
    assert mask_key(None) == "(未设置)"


def test_mask_key_empty():
    assert mask_key("") == "(未设置)"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/tui/test_setup.py -v
```

Expected: `ModuleNotFoundError` — `ci_optimizer.tui.setup` not found.

- [ ] **Step 3: Implement the helpers**

Create `src/ci_optimizer/tui/setup.py`:

```python
"""First-run setup wizard and config review for TUI."""

from __future__ import annotations

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/tui/test_setup.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ci_optimizer/tui/setup.py tests/tui/test_setup.py
git commit -m "feat(tui): add needs_setup() and mask_key() helpers"
```

---

## Task 2: `verify_api()` — API connectivity test

**Files:**
- Modify: `src/ci_optimizer/tui/setup.py`
- Modify: `tests/tui/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tui/test_setup.py`:

```python
import httpx
from unittest.mock import AsyncMock, MagicMock

from ci_optimizer.tui.setup import verify_api


@pytest.mark.asyncio
async def test_verify_api_anthropic_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "type": "message",
        "content": [{"type": "text", "text": "Hi"}],
        "model": "claude-sonnet-4-20250514",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = mock_response

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="anthropic",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
        )
    assert ok is True
    assert "claude-sonnet" in msg


@pytest.mark.asyncio
async def test_verify_api_anthropic_auth_error():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock(status_code=401, text="invalid api key")
    )

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="anthropic",
            api_key="bad-key",
            model="claude-sonnet-4-20250514",
        )
    assert ok is False
    assert "401" in msg or "错误" in msg


@pytest.mark.asyncio
async def test_verify_api_openai_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hi"}}],
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = mock_response

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="openai",
            api_key="sk-test",
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
        )
    assert ok is True
    assert "gpt-4o" in msg


@pytest.mark.asyncio
async def test_verify_api_network_error():
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    with patch("ci_optimizer.tui.setup.httpx.AsyncClient", return_value=mock_client):
        ok, msg = await verify_api(
            provider="anthropic",
            api_key="sk-ant-test",
            model="claude-sonnet-4-20250514",
        )
    assert ok is False
    assert "网络" in msg or "connect" in msg.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/tui/test_setup.py::test_verify_api_anthropic_success -v
```

Expected: `ImportError` — `verify_api` not found.

- [ ] **Step 3: Implement `verify_api`**

Add to `src/ci_optimizer/tui/setup.py`:

```python
import time

import httpx


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
    start = time.monotonic()
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/tui/test_setup.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ci_optimizer/tui/setup.py tests/tui/test_setup.py
git commit -m "feat(tui): add verify_api() for API connectivity testing"
```

---

## Task 3: `run_setup_wizard()` — full first-run flow

**Files:**
- Modify: `src/ci_optimizer/tui/setup.py`
- Modify: `tests/tui/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tui/test_setup.py`:

```python
from io import StringIO
from rich.console import Console


@pytest.mark.asyncio
async def test_run_setup_wizard_anthropic(tmp_path):
    """Full wizard flow: anthropic provider, all fields filled."""
    from ci_optimizer.tui.setup import run_setup_wizard

    config_file = tmp_path / "config.json"
    config_dir = tmp_path

    # Simulate user inputs:
    # 1 = anthropic, sk-ant-key, ghp-token, (enter for default model), 2 = zh
    inputs = iter(["1", "sk-ant-test-key-123456", "ghp-token-abc", "", "2"])
    mock_session = AsyncMock()
    mock_session.prompt_async = AsyncMock(side_effect=lambda *a, **kw: next(inputs))

    with (
        patch("ci_optimizer.tui.setup.CONFIG_FILE", config_file),
        patch("ci_optimizer.tui.setup.CONFIG_DIR", config_dir),
        patch("ci_optimizer.tui.setup.PromptSession", return_value=mock_session),
        patch("ci_optimizer.tui.setup.verify_api", new=AsyncMock(return_value=(True, "claude-sonnet-4-20250514, 响应 1.0s"))),
    ):
        console = Console(file=StringIO())
        config = await run_setup_wizard(console)

    assert config.provider == "anthropic"
    assert config.anthropic_api_key == "sk-ant-test-key-123456"
    assert config.github_token == "ghp-token-abc"
    assert config.language == "zh"
    assert config_file.exists()


@pytest.mark.asyncio
async def test_run_setup_wizard_openai(tmp_path):
    """Wizard flow: openai provider."""
    from ci_optimizer.tui.setup import run_setup_wizard

    config_file = tmp_path / "config.json"
    config_dir = tmp_path

    # 2 = openai, sk-key, (enter skip github), model-name, 1 = en
    inputs = iter(["2", "sk-openai-key-123456", "", "gpt-4o", "1"])
    mock_session = AsyncMock()
    mock_session.prompt_async = AsyncMock(side_effect=lambda *a, **kw: next(inputs))

    with (
        patch("ci_optimizer.tui.setup.CONFIG_FILE", config_file),
        patch("ci_optimizer.tui.setup.CONFIG_DIR", config_dir),
        patch("ci_optimizer.tui.setup.PromptSession", return_value=mock_session),
        patch("ci_optimizer.tui.setup.verify_api", new=AsyncMock(return_value=(True, "gpt-4o, 响应 0.8s"))),
    ):
        console = Console(file=StringIO())
        config = await run_setup_wizard(console)

    assert config.provider == "openai"
    assert config.openai_api_key == "sk-openai-key-123456"
    assert config.github_token is None
    assert config.model == "gpt-4o"
    assert config.language == "en"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/tui/test_setup.py::test_run_setup_wizard_anthropic -v
```

Expected: `ImportError` — `run_setup_wizard` not found.

- [ ] **Step 3: Implement `run_setup_wizard`**

Add to `src/ci_optimizer/tui/setup.py`:

```python
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel

from ci_optimizer.config import CONFIG_DIR, CONFIG_FILE, DEFAULT_MODEL, AgentConfig

# (keep existing needs_setup, mask_key, verify_api, etc.)


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
    model = (await session.prompt_async(f"   请输入模型名称 (回车使用默认): ")).strip()
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/tui/test_setup.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ci_optimizer/tui/setup.py tests/tui/test_setup.py
git commit -m "feat(tui): add run_setup_wizard() for first-run configuration"
```

---

## Task 4: `run_config_review()` — existing config review with per-item modify

**Files:**
- Modify: `src/ci_optimizer/tui/setup.py`
- Modify: `tests/tui/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/tui/test_setup.py`:

```python
@pytest.mark.asyncio
async def test_config_review_no_changes(tmp_path):
    """User declines all modifications."""
    from ci_optimizer.tui.setup import run_config_review

    config = AgentConfig(
        provider="anthropic",
        anthropic_api_key="sk-ant-test-key-123456",
        github_token="ghp-token-abc",
        model="claude-sonnet-4-20250514",
        language="zh",
    )

    # All "n" (or empty = default N)
    inputs = iter(["", "", "", "", ""])
    mock_session = AsyncMock()
    mock_session.prompt_async = AsyncMock(side_effect=lambda *a, **kw: next(inputs))

    with (
        patch("ci_optimizer.tui.setup.CONFIG_FILE", tmp_path / "config.json"),
        patch("ci_optimizer.tui.setup.CONFIG_DIR", tmp_path),
        patch("ci_optimizer.tui.setup.PromptSession", return_value=mock_session),
        patch("ci_optimizer.tui.setup.verify_api", new=AsyncMock(return_value=(True, "ok, 1.0s"))),
    ):
        console = Console(file=StringIO())
        result = await run_config_review(console, config)

    assert result.provider == "anthropic"
    assert result.anthropic_api_key == "sk-ant-test-key-123456"
    assert result.language == "zh"


@pytest.mark.asyncio
async def test_config_review_change_model(tmp_path):
    """User changes only the model."""
    from ci_optimizer.tui.setup import run_config_review

    config = AgentConfig(
        provider="anthropic",
        anthropic_api_key="sk-ant-test-key-123456",
        model="claude-sonnet-4-20250514",
        language="en",
    )

    # n, n, n, y + new model, n
    inputs = iter(["", "", "", "y", "claude-opus-4-20250514", ""])
    mock_session = AsyncMock()
    mock_session.prompt_async = AsyncMock(side_effect=lambda *a, **kw: next(inputs))

    with (
        patch("ci_optimizer.tui.setup.CONFIG_FILE", tmp_path / "config.json"),
        patch("ci_optimizer.tui.setup.CONFIG_DIR", tmp_path),
        patch("ci_optimizer.tui.setup.PromptSession", return_value=mock_session),
        patch("ci_optimizer.tui.setup.verify_api", new=AsyncMock(return_value=(True, "ok, 1.0s"))),
    ):
        console = Console(file=StringIO())
        result = await run_config_review(console, config)

    assert result.model == "claude-opus-4-20250514"
    assert result.provider == "anthropic"  # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/tui/test_setup.py::test_config_review_no_changes -v
```

Expected: `ImportError` — `run_config_review` not found.

- [ ] **Step 3: Implement `run_config_review`**

Add to `src/ci_optimizer/tui/setup.py`:

```python
async def run_config_review(console: Console, config: AgentConfig) -> AgentConfig:
    """Show current config and let user modify each item. Returns updated config."""
    session = PromptSession()
    changed = False

    # Display current config
    console.print(
        Panel(
            f"  Provider:  [bold]{config.provider}[/bold]\n"
            f"  API Key:   [bold]{mask_key(config.get_api_key())}[/bold]\n"
            f"  GitHub:    [bold]{mask_key(config.github_token)}[/bold]\n"
            f"  Model:     [bold]{config.model}[/bold]\n"
            f"  Language:  [bold]{'中文' if config.language == 'zh' else 'English'}[/bold]",
            title="当前配置",
            border_style="cyan",
        )
    )
    console.print()

    # 1. Provider
    ans = (await session.prompt_async(f"Provider [{config.provider}] — 修改？(y/N): ")).strip().lower()
    if ans in ("y", "yes"):
        console.print("   [1] Anthropic (Claude)")
        console.print("   [2] OpenAI (兼容)")
        choice = (await session.prompt_async("   请选择: ")).strip()
        new_provider = "openai" if choice == "2" else "anthropic"
        if new_provider != config.provider:
            config.provider = new_provider
            changed = True
            # Clear old provider's key since provider changed
            console.print(f"   [dim]已切换到 {config.provider}，请重新设置 API Key[/dim]")

    # 2. API Key
    key_display = mask_key(config.get_api_key())
    ans = (await session.prompt_async(f"API Key [{key_display}] — 修改？(y/N): ")).strip().lower()
    if ans in ("y", "yes"):
        key_label = "Anthropic" if config.provider == "anthropic" else "OpenAI"
        new_key = (await session.prompt_async(f"   请输入 {key_label} API Key: ", is_password=True)).strip()
        if new_key:
            if config.provider == "anthropic":
                config.anthropic_api_key = new_key
            else:
                config.openai_api_key = new_key
            changed = True

    # 3. GitHub Token
    gh_display = mask_key(config.github_token)
    ans = (await session.prompt_async(f"GitHub Token [{gh_display}] — 修改？(y/N): ")).strip().lower()
    if ans in ("y", "yes"):
        new_token = (await session.prompt_async("   请输入 GitHub Token (留空清除): ", is_password=True)).strip()
        config.github_token = new_token if new_token else None
        changed = True

    # 4. Model
    ans = (await session.prompt_async(f"Model [{config.model}] — 修改？(y/N): ")).strip().lower()
    if ans in ("y", "yes"):
        new_model = (await session.prompt_async("   请输入模型名称: ")).strip()
        if new_model:
            config.model = new_model
            changed = True

    # 5. Language
    lang_display = "中文" if config.language == "zh" else "English"
    ans = (await session.prompt_async(f"Language [{lang_display}] — 修改？(y/N): ")).strip().lower()
    if ans in ("y", "yes"):
        console.print("   [1] English")
        console.print("   [2] 中文")
        choice = (await session.prompt_async("   请选择: ")).strip()
        new_lang = "zh" if choice == "2" else "en"
        if new_lang != config.language:
            config.language = new_lang
            changed = True

    # Save if changed
    if changed:
        config.save()
        console.print(f"\n[green]✓ 配置已更新[/green]")
    console.print()

    # Always verify API
    await _run_verify(console, config)

    return config
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/tui/test_setup.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ci_optimizer/tui/setup.py tests/tui/test_setup.py
git commit -m "feat(tui): add run_config_review() for per-item config modification"
```

---

## Task 5: Wire setup into `app.py` `run_tui()`

**Files:**
- Modify: `src/ci_optimizer/tui/app.py` (lines 298-313)

- [ ] **Step 1: Update `run_tui()` to call setup before repo confirmation**

In `src/ci_optimizer/tui/app.py`, replace lines 298-313:

```python
async def run_tui(repo_path: Path | None = None) -> None:
    """Main TUI entry point: banner → repo confirm → REPL loop."""
    console = Console()
    renderer = StreamRenderer(console=console)

    _print_banner(console)

    # Detect and confirm repo
    ctx = detect_repo(repo_path)
    try:
        ctx = await confirm_repo(ctx)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]已退出[/dim]")
        return

    config = AgentConfig.load()
```

With:

```python
async def run_tui(repo_path: Path | None = None) -> None:
    """Main TUI entry point: setup → banner → repo confirm → REPL loop."""
    console = Console()
    renderer = StreamRenderer(console=console)

    _print_banner(console)

    # Setup / config review
    from ci_optimizer.tui.setup import needs_setup, run_config_review, run_setup_wizard

    try:
        if needs_setup():
            config = await run_setup_wizard(console)
        else:
            config = AgentConfig.load()
            config = await run_config_review(console, config)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]已退出[/dim]")
        return

    # Detect and confirm repo
    ctx = detect_repo(repo_path)
    try:
        ctx = await confirm_repo(ctx)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]已退出[/dim]")
        return
```

Also remove the now-redundant `config = AgentConfig.load()` line that was after `confirm_repo` (around old line 313), since `config` is already set by the setup flow above.

- [ ] **Step 2: Verify TUI import works**

```bash
uv run python -c "from ci_optimizer.tui.app import run_tui; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Run all TUI tests**

```bash
uv run pytest tests/tui/ -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/ci_optimizer/tui/app.py
git commit -m "feat(tui): wire setup wizard into run_tui() entry point"
```

---

## Task 6: Update TUI documentation

**Files:**
- Modify: `docs/guides/zh/tui-guide.md`

- [ ] **Step 1: Add setup wizard section after "启动 TUI" section**

In `docs/guides/zh/tui-guide.md`, after the `## 启动 TUI` section and before `## 仓库确认`, add:

```markdown
---

## 首次配置引导

首次运行 `ci-agent chat` 时（`~/.ci-agent/config.json` 不存在），会自动进入配置引导流程：

```
╭──────── ci-agent Setup ────────╮
│  首次使用，需要进行初始配置     │
╰────────────────────────────────╯

1. AI 引擎
   [1] Anthropic (Claude)
   [2] OpenAI (兼容)
   请选择 [1]: 1

2. API Key
   请输入 Anthropic API Key: ****

3. GitHub Token (用于拉取 CI 数据，回车跳过)
   请输入 GitHub Token: ****

4. 模型 (默认: claude-sonnet-4-20250514)
   请输入模型名称 (回车使用默认):

5. 输出��言
   [1] English
   [2] 中文
   请选择 [1]: 2

✓ 配置已保存到 ~/.ci-agent/config.json

⠸ 正在验证 API 连通性...
✓ API 连通正常 (claude-sonnet-4-20250514, 响应 1.2s)
```

### 再次启动时的配置确认

如果配置文件已存在，启动时会展示当前配置并逐项询问是否修改：

```
╭──────── 当前配置 ────────╮
│  Provider:  anthropic     │
│  API Key:   sk-ant-***4f  │
│  GitHub:    ghp_***a3     │
│  Model:     claude-sonnet │
│  Language:  zh            │
╰──────────────────────────╯

Provider [anthropic] — 修改？(y/N):
API Key [sk-ant-***4f] — 修改？(y/N):
GitHub Token [ghp_***a3] — 修改？(y/N):
Model [claude-sonnet-4-20250514] — 修改？(y/N):
Language [中文] — 修改？(y/N):
```

直接回车跳过不修改。输入 `y` 后按提示输入新值。

### API 连通性验证

每次启动都会验证 API Key 和模型是否可用：
- 成功：显示模型名称和响应耗时
- 失败：显示错误原因（认证失败 / 网络问题 / 超时），但仍可进入 TUI
```

- [ ] **Step 2: Update 目录索引**

In `docs/guides/zh/tui-guide.md`, update the table of contents section, adding the new entry after `- [启动 TUI](#启动-tui)`:

```markdown
- [首次配置引导](#首次配置引导)
```

- [ ] **Step 3: Commit**

```bash
git add docs/guides/zh/tui-guide.md
git commit -m "docs: add setup wizard section to TUI guide"
```

---

## Self-Review

**Spec coverage:**

| 需求 | Task |
|------|------|
| 首次无 config.json → 全量引导 | Task 3 (`run_setup_wizard`) |
| 已有 config → 展示 + 逐项修改 | Task 4 (`run_config_review`) |
| Provider 选择 (anthropic/openai) | Task 3 Step 1, Task 4 Step 1 |
| API Key 输入（密码隐藏） | Task 3 (`is_password=True`), Task 4 |
| GitHub Token（可跳过） | Task 3, Task 4 |
| Model 选择 | Task 3, Task 4 |
| Language 选择 | Task 3, Task 4 |
| 每次启动 API 连通性测试 | Task 2 (`verify_api`), Task 3/4 (`_run_verify`) |
| 测试失败仍可进入 TUI | Task 3/4 (`_run_verify` 只打印，不阻断) |
| 文档更新 | Task 6 |

**Placeholder scan:** 所有 Task 包含完整代码。无 TBD / TODO。✓

**Type consistency:**
- `needs_setup() -> bool` — Task 1 定义, Task 5 调用 ✓
- `run_setup_wizard(console) -> AgentConfig` — Task 3 定义, Task 5 调用 ✓
- `run_config_review(console, config) -> AgentConfig` — Task 4 定义, Task 5 调用 ✓
- `verify_api(provider, api_key, model, base_url, anthropic_base_url) -> tuple[bool, str]` — Task 2 定义, Task 3/4 通过 `_run_verify` 调用 ✓
- `mask_key(value) -> str` — Task 1 定义, Task 4 调用 ✓
- `AgentConfig.save()`, `AgentConfig.load()`, `AgentConfig.get_api_key()` — 已有，未修改 ✓
