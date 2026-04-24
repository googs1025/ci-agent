# Chat Tool Use 实现计划

> **给执行 Agent 的提示：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行本计划。步骤使用 `- [ ]` 语法跟踪进度。

**目标：** 让 `/api/chat` 端点支持多轮 tool use，使 AI 能主动读取仓库文件、搜索代码、执行命令——将 TUI 变成完整的 CI 诊断 Agent。

**架构：** Anthropic `messages.create()` API 原生支持 tool 定义并返回 `tool_use` content block。Server 端运行一个循环：调用 LLM → 如果返回 tool_use block，在本地执行工具，把结果送回 → 重复直到 LLM 只返回文本。SSE 事件类型扩展 `tool_use` 和 `tool_result`，让 TUI 能展示工具调用状态。所有工具限制在已确认的仓库路径内（沙箱）。

**技术栈：** anthropic Python SDK（tool use）、FastAPI（SSE 流式）、httpx（TUI 客户端）、Rich（TUI 渲染）、pathlib/subprocess（工具执行）

---

## 文件结构

```
src/ci_optimizer/
├── api/
│   ├── chat.py             # 修改：添加 tool-use agent 循环，新 SSE 事件
│   └── tools.py            # 新建：工具定义、执行、沙箱安全
├── tui/
│   ├── app.py              # 修改：处理新 SSE 事件类型（tool_use, tool_result）
│   └── renderer.py         # 不需要改动——TUI 的 app.py 直接处理 SSE
tests/
├── test_tools.py           # 新建：工具执行和沙箱的单元测试
├── tui/
│   └── test_app_sse.py     # 新建：SSE 事件解析测试
```

---

### 任务 1：定义并实现 CI 工具

**文件：**
- 新建：`src/ci_optimizer/api/tools.py`
- 测试：`tests/test_tools.py`

- [ ] **步骤 1：编写工具定义的失败测试**

```python
# tests/test_tools.py
"""测试 api.tools —— 工具定义和执行。"""

from pathlib import Path

import pytest

from ci_optimizer.api.tools import (
    TOOL_DEFINITIONS,
    execute_tool,
    validate_path,
)


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_tool_names(self):
        names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
        assert "read_file" in names
        assert "glob_files" in names
        assert "grep_content" in names
        assert "list_workflows" in names


class TestValidatePath:
    def test_allows_path_within_repo(self, tmp_path):
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir(parents=True)
        target.touch()
        result = validate_path(str(target), repo_root=tmp_path)
        assert result == target

    def test_rejects_path_traversal(self, tmp_path):
        with pytest.raises(PermissionError, match="outside"):
            validate_path("/etc/passwd", repo_root=tmp_path)

    def test_rejects_symlink_escape(self, tmp_path):
        link = tmp_path / "escape"
        link.symlink_to("/etc")
        with pytest.raises(PermissionError, match="outside"):
            validate_path(str(link / "passwd"), repo_root=tmp_path)


class TestExecuteTool:
    @pytest.fixture()
    def repo(self, tmp_path):
        """创建最小仓库结构。"""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs: {}")
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("def main():\n    pass\n")
        return tmp_path

    async def test_read_file(self, repo):
        result = await execute_tool("read_file", {"path": ".github/workflows/ci.yml"}, repo_root=repo)
        assert "name: CI" in result

    async def test_read_file_not_found(self, repo):
        result = await execute_tool("read_file", {"path": "nonexistent.txt"}, repo_root=repo)
        assert "not found" in result.lower() or "error" in result.lower()

    async def test_glob_files(self, repo):
        result = await execute_tool("glob_files", {"pattern": "**/*.yml"}, repo_root=repo)
        assert "ci.yml" in result

    async def test_grep_content(self, repo):
        result = await execute_tool("grep_content", {"pattern": "def main", "glob": "**/*.py"}, repo_root=repo)
        assert "main.py" in result

    async def test_list_workflows(self, repo):
        result = await execute_tool("list_workflows", {}, repo_root=repo)
        assert "ci.yml" in result

    async def test_unknown_tool(self, repo):
        result = await execute_tool("rm_rf", {}, repo_root=repo)
        assert "unknown" in result.lower()

    async def test_path_traversal_blocked(self, repo):
        result = await execute_tool("read_file", {"path": "/etc/passwd"}, repo_root=repo)
        assert "outside" in result.lower() or "error" in result.lower()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run pytest tests/test_tools.py -v`
预期：FAIL，报 `ModuleNotFoundError: No module named 'ci_optimizer.api.tools'`

- [ ] **步骤 3：实现工具模块**

```python
# src/ci_optimizer/api/tools.py
"""CI 专用工具——用于 chat agent。

每个工具在确认的仓库根目录内执行。路径经过验证，防止越界访问。
"""

from __future__ import annotations

import re
from pathlib import Path

# ── 工具定义（Anthropic 格式）────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取仓库中的文件内容。用于查看 workflow 文件、源码、配置等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于仓库根目录的路径（如 '.github/workflows/ci.yml'、'src/main.py'）",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "按 glob 模式查找仓库中的文件，返回匹配的文件路径列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob 模式（如 '**/*.yml'、'.github/workflows/*.yaml'、'src/**/*.py'）",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_content",
            "description": "用正则表达式搜索文件内容，返回匹配的行及文件路径和行号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "正则表达式（如 'actions/checkout'、'runs-on:'、'cache.*hit'）",
                    },
                    "glob": {
                        "type": "string",
                        "description": "可选，用 glob 过滤搜索范围（默认 '**/*'）",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": "列出 .github/workflows/ 下所有 GitHub Actions workflow 文件，包含触发事件和 job 名称。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在仓库内执行只读 shell 命令。仅允许安全命令（git log、git diff、ls 等），写操作被禁止。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell 命令（如 'git log --oneline -10'、'ls -la .github/'）",
                    },
                },
                "required": ["command"],
            },
        },
    },
]

# 转换为 Anthropic SDK 格式（name + description + input_schema）
ANTHROPIC_TOOLS = [
    {
        "name": t["function"]["name"],
        "description": t["function"]["description"],
        "input_schema": t["function"]["parameters"],
    }
    for t in TOOL_DEFINITIONS
]

# ── 路径沙箱 ─────────────────────────────────────────────────────────────────


def validate_path(path_str: str, *, repo_root: Path) -> Path:
    """解析路径并确保在 repo_root 范围内。越界则抛出 PermissionError。"""
    resolved = (repo_root / path_str).resolve()
    repo_resolved = repo_root.resolve()
    if not str(resolved).startswith(str(repo_resolved)):
        raise PermissionError(f"Path {path_str} resolves outside repository root")
    return resolved


# ── 命令安全检查 ──────────────────────────────────────────────────────────────

ALLOWED_COMMAND_PREFIXES = (
    "git log", "git diff", "git show", "git status", "git branch",
    "git tag", "git rev-parse", "git remote",
    "ls", "cat", "head", "tail", "wc", "find", "tree",
    "grep", "rg", "awk", "sort", "uniq",
)

BLOCKED_COMMANDS = {"rm", "mv", "cp", "chmod", "chown", "sudo", "curl", "wget", "pip", "npm", "docker"}


def _is_command_safe(command: str) -> bool:
    """判断命令是否为只读安全命令。"""
    cmd_stripped = command.strip()
    first_word = cmd_stripped.split()[0] if cmd_stripped else ""
    if first_word in BLOCKED_COMMANDS:
        return False
    return any(cmd_stripped.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES)


# ── 工具执行器 ────────────────────────────────────────────────────────────────


async def execute_tool(name: str, inputs: dict, *, repo_root: Path) -> str:
    """按名称执行工具，限定在仓库沙箱内。返回字符串结果。"""
    try:
        if name == "read_file":
            return _exec_read_file(inputs, repo_root)
        if name == "glob_files":
            return _exec_glob_files(inputs, repo_root)
        if name == "grep_content":
            return _exec_grep_content(inputs, repo_root)
        if name == "list_workflows":
            return _exec_list_workflows(repo_root)
        if name == "run_command":
            return await _exec_run_command(inputs, repo_root)
        return f"Error: unknown tool '{name}'"
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error executing {name}: {e}"


def _exec_read_file(inputs: dict, repo_root: Path) -> str:
    path = validate_path(inputs["path"], repo_root=repo_root)
    if not path.exists():
        return f"Error: file not found: {inputs['path']}"
    if not path.is_file():
        return f"Error: not a file: {inputs['path']}"
    content = path.read_text(errors="replace")
    max_chars = 50_000
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n... (已截断，共 {len(content)} 字符)"
    return content


def _exec_glob_files(inputs: dict, repo_root: Path) -> str:
    pattern = inputs["pattern"]
    matches = sorted(repo_root.glob(pattern))
    files = []
    for m in matches:
        if m.is_file():
            try:
                files.append(str(m.relative_to(repo_root)))
            except ValueError:
                continue
    if not files:
        return f"未找到匹配 {pattern} 的文件"
    if len(files) > 100:
        return "\n".join(files[:100]) + f"\n\n... (共 {len(files)} 个，仅显示前 100 个)"
    return "\n".join(files)


def _exec_grep_content(inputs: dict, repo_root: Path) -> str:
    pattern = inputs["pattern"]
    file_glob = inputs.get("glob", "**/*")
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: 无效正则 '{pattern}': {e}"

    matches = []
    for path in sorted(repo_root.glob(file_glob)):
        if not path.is_file():
            continue
        if path.stat().st_size > 500_000:
            continue
        try:
            rel = str(path.relative_to(repo_root))
        except ValueError:
            continue
        try:
            for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(matches) >= 50:
                        matches.append("... (仅显示前 50 条匹配)")
                        return "\n".join(matches)
        except (OSError, UnicodeDecodeError):
            continue

    if not matches:
        return f"未找到匹配 {pattern} 的内容"
    return "\n".join(matches)


def _exec_list_workflows(repo_root: Path) -> str:
    wf_dir = repo_root / ".github" / "workflows"
    if not wf_dir.exists():
        return "未找到 .github/workflows/ 目录"

    import yaml

    results = []
    for f in sorted(wf_dir.iterdir()):
        if not f.is_file() or f.suffix not in (".yml", ".yaml"):
            continue
        rel = str(f.relative_to(repo_root))
        try:
            data = yaml.safe_load(f.read_text())
            name = data.get("name", f.stem)
            triggers = list(data.get("on", {}).keys()) if isinstance(data.get("on"), dict) else [str(data.get("on", "?"))]
            jobs = list(data.get("jobs", {}).keys())
            results.append(f"{rel}\n  name: {name}\n  triggers: {', '.join(triggers)}\n  jobs: {', '.join(jobs)}")
        except Exception:
            results.append(f"{rel}\n  (解析错误)")

    if not results:
        return "未找到 workflow 文件"
    return "\n\n".join(results)


async def _exec_run_command(inputs: dict, repo_root: Path) -> str:
    import asyncio

    command = inputs.get("command", "")
    if not _is_command_safe(command):
        return f"Error: 不允许执行此命令（仅允许只读命令）: {command}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        return "Error: 命令超时（15 秒）"

    output = stdout.decode(errors="replace")
    if stderr:
        output += "\nSTDERR:\n" + stderr.decode(errors="replace")

    if len(output) > 30_000:
        output = output[:30_000] + "\n... (已截断)"

    return output or "(无输出)"
```

- [ ] **步骤 4：运行测试确认通过**

运行：`uv run pytest tests/test_tools.py -v`
预期：全部 10 个测试 PASS

- [ ] **步骤 5：运行 lint**

运行：`uv run ruff check src/ci_optimizer/api/tools.py tests/test_tools.py`
预期：All checks passed

- [ ] **步骤 6：提交**

```bash
git add src/ci_optimizer/api/tools.py tests/test_tools.py
git commit -m "feat(chat): 添加 CI 专用工具定义和沙箱执行"
```

---

### 任务 2：为 /api/chat 添加 Tool-Use Agent 循环

**文件：**
- 修改：`src/ci_optimizer/api/chat.py`
- 新建测试：`tests/test_chat_tools.py`

- [ ] **步骤 1：编写 agent 循环的失败测试**

```python
# tests/test_chat_tools.py
"""测试 /api/chat 的 tool-use agent 循环。"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ci_optimizer.api.chat import _run_agentic_loop


class TestAgenticLoop:
    """测试多轮 tool-use 循环。"""

    @pytest.fixture()
    def repo(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest")
        return tmp_path

    async def test_no_tool_use_returns_text(self, repo):
        """模型返回纯文本时，循环输出 text 事件后停止。"""
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(type="text", text="你好！")]
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        mock_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "hi"}],
            repo_root=repo,
            max_turns=5,
        ):
            events.append(event)

        # 应包含 text 事件和 done 事件
        assert any('"content":' in e for e in events)
        assert any('"input_tokens"' in e for e in events)

    async def test_tool_use_then_text(self, repo):
        """模型使用工具时，循环执行工具后继续。"""
        # 第一次响应：tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool_1"
        tool_block.name = "list_workflows"
        tool_block.input = {}

        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        first_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        first_response.model = "claude-3-5-sonnet"

        # 第二次响应：纯文本
        second_response = MagicMock()
        second_response.stop_reason = "end_turn"
        second_response.content = [MagicMock(type="text", text="找到 1 个 workflow。")]
        second_response.usage = MagicMock(input_tokens=50, output_tokens=10)
        second_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "列出 workflows"}],
            repo_root=repo,
            max_turns=5,
        ):
            events.append(event)

        # 应包含 tool_use、tool_result、text、done 事件
        event_str = "\n".join(events)
        assert "tool_use" in event_str
        assert "tool_result" in event_str
        assert "找到 1 个 workflow" in event_str

    async def test_max_turns_limit(self, repo):
        """达到 max_turns 上限时停止，即使模型持续请求工具。"""
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool_1"
        tool_block.name = "list_workflows"
        tool_block.input = {}

        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [tool_block]
        response.usage = MagicMock(input_tokens=10, output_tokens=5)
        response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "无限循环"}],
            repo_root=repo,
            max_turns=2,
        ):
            events.append(event)

        # 最多调用 2 次 create
        assert mock_client.messages.create.call_count <= 2
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run pytest tests/test_chat_tools.py -v`
预期：FAIL，报 `ImportError: cannot import name '_run_agentic_loop'`

- [ ] **步骤 3：在 chat.py 中实现 agent 循环**

修改 `src/ci_optimizer/api/chat.py`，添加 `_run_agentic_loop` 函数，并更新 `_query_anthropic` 使用它：

```python
# 在文件顶部添加导入
from pathlib import Path

from ci_optimizer.api.tools import ANTHROPIC_TOOLS, execute_tool


async def _run_agentic_loop(
    *,
    client,
    model: str,
    system: str,
    messages: list[dict],
    repo_root: Path | None,
    max_turns: int = 10,
):
    """多轮 tool-use 循环。Yield SSE 事件字符串。"""
    tools = ANTHROPIC_TOOLS if repo_root else []
    total_input = 0
    total_output = 0

    for turn in range(max_turns):
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=tools or None,
        )

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        # 处理 content blocks
        tool_use_blocks = []
        for block in response.content:
            if block.type == "text" and block.text.strip():
                yield _sse_event("text", {"content": block.text})
            elif block.type == "tool_use":
                tool_use_blocks.append(block)
                yield _sse_event("tool_use", {
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        # 无 tool use，结束循环
        if response.stop_reason != "tool_use" or not tool_use_blocks:
            break

        # 执行工具并构建 tool results
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tool_block in tool_use_blocks:
            result = await execute_tool(
                tool_block.name,
                tool_block.input,
                repo_root=repo_root,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result,
            })
            yield _sse_event("tool_result", {
                "id": tool_block.id,
                "name": tool_block.name,
                "result_preview": result[:200] + "..." if len(result) > 200 else result,
            })

        messages.append({"role": "user", "content": tool_results})

    # 完成事件，累计 usage
    yield _sse_event("done", {
        "usage": {"input_tokens": total_input, "output_tokens": total_output},
        "model": response.model,
        "turns": turn + 1,
    })
```

同时更新 `_query_anthropic` 调用 `_run_agentic_loop`，并在 `_generate()` 中传入 `repo_root`：

```python
# _generate() 中解析 repo_root
repo_root = None
if request.repo_root:
    candidate = Path(request.repo_root)
    if candidate.exists() and candidate.is_dir():
        repo_root = candidate

# 传给 _query_anthropic
async for chunk in _query_anthropic(messages, system, model, api_key, base_url, repo_root=repo_root):
    yield chunk
```

- [ ] **步骤 4：运行测试确认通过**

运行：`uv run pytest tests/test_chat_tools.py -v`
预期：全部 3 个测试 PASS

- [ ] **步骤 5：运行 lint**

运行：`uv run ruff check src/ci_optimizer/api/chat.py tests/test_chat_tools.py`

- [ ] **步骤 6：提交**

```bash
git add src/ci_optimizer/api/chat.py tests/test_chat_tools.py
git commit -m "feat(chat): 添加多轮 tool-use agent 循环"
```

---

### 任务 3：TUI 传递仓库路径到 Server

**文件：**
- 修改：`src/ci_optimizer/tui/app.py`
- 修改：`src/ci_optimizer/api/chat.py`（ChatRequest schema）

- [ ] **步骤 1：更新 ChatRequest 接受 repo_root**

在 `src/ci_optimizer/api/chat.py` 中更新 schema：

```python
class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    repo: str | None = None
    branch: str | None = None
    model: str | None = None
    repo_root: str | None = None  # 仓库在服务器文件系统上的绝对路径
```

- [ ] **步骤 2：更新 _generate() 使用 request.repo_root**

```python
repo_root = None
if request.repo_root:
    candidate = Path(request.repo_root)
    if candidate.exists() and candidate.is_dir():
        repo_root = candidate
```

- [ ] **步骤 3：TUI payload 中添加 repo_root**

在 `src/ci_optimizer/tui/app.py` 的 `_query_via_server()` 中：

```python
payload = {
    "messages": conversation,
    "repo": ctx.display_name,
    "branch": ctx.branch,
    "model": config.model,
    "repo_root": str(ctx.local_path),  # 传递本地路径给 server 执行工具
}
```

- [ ] **步骤 4：手动端到端测试**

运行：`uv run ci-agent chat`
输入：`列出所有 workflow 文件`
预期：AI 使用 `list_workflows` 工具，读取文件，返回 workflow 详情

- [ ] **步骤 5：提交**

```bash
git add src/ci_optimizer/api/chat.py src/ci_optimizer/tui/app.py
git commit -m "feat(chat): TUI 传递 repo_root 给 server 执行工具"
```

---

### 任务 4：TUI 渲染工具调用事件

**文件：**
- 修改：`src/ci_optimizer/tui/app.py`
- 新建测试：`tests/tui/test_app_sse.py`

- [ ] **步骤 1：编写 SSE 事件解析测试**

```python
# tests/tui/test_app_sse.py
"""测试 TUI 的 SSE 事件处理。"""

import json


def make_sse(event: str, data: dict) -> list[str]:
    """模拟 aiter_lines() 返回的 SSE 行。"""
    return [f"event: {event}", f"data: {json.dumps(data)}"]


class TestSSEEventTypes:
    def test_parse_text_event(self):
        lines = make_sse("text", {"content": "Hello"})
        assert lines[0] == "event: text"
        data = json.loads(lines[1][6:])
        assert data["content"] == "Hello"

    def test_parse_tool_use_event(self):
        lines = make_sse("tool_use", {"id": "t1", "name": "read_file", "input": {"path": "ci.yml"}})
        data = json.loads(lines[1][6:])
        assert data["name"] == "read_file"
        assert data["input"]["path"] == "ci.yml"

    def test_parse_tool_result_event(self):
        lines = make_sse("tool_result", {"id": "t1", "name": "read_file", "result_preview": "name: CI..."})
        data = json.loads(lines[1][6:])
        assert data["name"] == "read_file"
        assert "CI" in data["result_preview"]

    def test_parse_done_event_with_turns(self):
        lines = make_sse("done", {"usage": {"input_tokens": 100, "output_tokens": 50}, "model": "claude", "turns": 3})
        data = json.loads(lines[1][6:])
        assert data["turns"] == 3
```

- [ ] **步骤 2：运行测试确认通过**（纯解析测试，不需要新代码即可通过）

运行：`uv run pytest tests/tui/test_app_sse.py -v`
预期：全部 4 个测试 PASS

- [ ] **步骤 3：更新 TUI SSE 处理器渲染工具事件**

在 `src/ci_optimizer/tui/app.py` 的 `_query_via_server()` 中，在现有 `text` 和 `done` 处理器之后添加：

```python
elif event_type == "tool_use":
    tool_name = data.get("name", "?")
    tool_input = data.get("input", {})
    desc = _tool_status(tool_name, tool_input)
    renderer.console.print(f"  [dim]⠸ {desc}[/dim]")

elif event_type == "tool_result":
    tool_name = data.get("name", "?")
    renderer.console.print(f"  [green]✓[/green] [dim]{tool_name} 完成[/dim]")
```

添加辅助函数：

```python
def _tool_status(name: str, inputs: dict) -> str:
    """工具调用的中文状态描述。"""
    if name == "read_file":
        return f"读取 {inputs.get('path', '...')}"
    if name == "glob_files":
        return f"搜索文件 {inputs.get('pattern', '...')}"
    if name == "grep_content":
        return f"搜索内容 {inputs.get('pattern', '...')}"
    if name == "list_workflows":
        return "列出 workflow 文件"
    if name == "run_command":
        cmd = inputs.get("command", "")
        return f"执行 {cmd[:50]}{'...' if len(cmd) > 50 else ''}"
    return f"{name} ..."
```

更新 `done` 处理器显示轮数：

```python
elif event_type == "done":
    renderer.console.print()
    usage = data.get("usage", {})
    model_used = data.get("model", config.model)
    input_t = usage.get("input_tokens", 0)
    output_t = usage.get("output_tokens", 0)
    turns = data.get("turns", 1)
    renderer.stats.query_count += 1
    turns_str = f" · {turns} 轮" if turns > 1 else ""
    renderer.console.print(
        f"[dim]model: {model_used} · "
        f"tokens: {input_t}↑ {output_t}↓{turns_str}[/dim]"
    )
```

- [ ] **步骤 4：运行全部 TUI 测试**

运行：`uv run pytest tests/tui/ -v`
预期：全部测试 PASS

- [ ] **步骤 5：提交**

```bash
git add src/ci_optimizer/tui/app.py tests/tui/test_app_sse.py
git commit -m "feat(tui): 渲染 tool_use 和 tool_result SSE 事件为状态行"
```

---

### 任务 5：集成测试和收尾

**文件：**
- 修改：`src/ci_optimizer/api/chat.py`（清理调试日志）
- 手动端到端测试

- [ ] **步骤 1：清理 chat.py 中的调试日志**

移除调试阶段添加的 `logger.info(f"Chat request: ...")` 行（如果还在的话）。

- [ ] **步骤 2：运行完整测试套件**

运行：`uv run pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_integration.py`
预期：全部测试 PASS

- [ ] **步骤 3：对所有改动文件运行 lint**

运行：`uv run ruff check src/ci_optimizer/api/chat.py src/ci_optimizer/api/tools.py src/ci_optimizer/tui/app.py`
预期：All checks passed

- [ ] **步骤 4：手动端到端测试**

启动 TUI：
```bash
uv run ci-agent chat
```

测试以下交互：
1. `列出所有 workflow 文件` → 应使用 `list_workflows` 工具
2. `读取 .github/workflows/ci.yml 的内容` → 应使用 `read_file` 工具
3. `搜索哪些地方用了 actions/checkout` → 应使用 `grep_content` 工具
4. `今天天气怎么样` → 应拒绝回答（CI-only scope guard）
5. `exit` → 正常退出

预期 TUI 输出格式：
```
› 列出所有 workflow 文件
  ⠸ 列出 workflow 文件
  ✓ list_workflows 完成

找到以下 workflow 文件：
...

model: claude-3-5-sonnet-20241022 · tokens: 320↑ 180↓ · 2 轮
```

- [ ] **步骤 5：提交**

```bash
git add -A
git commit -m "feat(chat): 完成 tool-use 集成和 TUI 渲染"
```

---

## 总结

| 任务 | 做什么 | 文件 |
|------|--------|------|
| 1 | 工具定义 + 沙箱执行 | `api/tools.py`、`tests/test_tools.py` |
| 2 | /api/chat 多轮 agent 循环 | `api/chat.py`、`tests/test_chat_tools.py` |
| 3 | TUI → Server 传递仓库路径 | `tui/app.py`、`api/chat.py` |
| 4 | TUI 渲染工具调用事件 | `tui/app.py`、`tests/tui/test_app_sse.py` |
| 5 | 集成测试和收尾 | 所有文件 |

## 数据流

```
用户输入
  │
  ├─ /command  → commands.py（本地处理）
  │
  └─ 自然语言 → TUI POST /api/chat (SSE)
                    │
                    ▼
                Server: _run_agentic_loop()
                    │
                    ├─ LLM 返回纯文本 → SSE event: text → TUI 显示
                    │
                    └─ LLM 返回 tool_use → SSE event: tool_use → TUI 显示 ⠸
                         │
                         ├─ 本地执行工具（沙箱内）
                         ├─ SSE event: tool_result → TUI 显示 ✓
                         └─ 将结果送回 LLM → 继续循环
                              │
                              └─ 最终文本 → SSE event: text + done
```
