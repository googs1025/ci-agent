# Chat 写入工具实现计划

> **给执行 Agent 的提示：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行本计划。步骤使用 `- [ ]` 语法跟踪进度。

**目标：** 让 chat agent 能修改仓库文件、提交 git commit、创建 PR，写入操作需经 TUI 用户确认后才执行。

**架构：** AI 通过 tool use 调用 `write_file` / `edit_file` 时，server 端不直接执行，而是将修改方案暂存并通过 SSE `write_proposal` 事件推送给 TUI。TUI 用确认面板（已有的 `panels.py`）展示修改内容，用户确认后发 `POST /api/chat/apply` 请求，server 执行实际写入。支持可选的 git commit。

**技术栈：** anthropic SDK（tool use）、FastAPI、pathlib（文件写入）、subprocess（git 操作）、Rich panels（TUI 确认）

---

## 文件结构

```
src/ci_optimizer/api/
├── tools.py            # 修改：添加 write_file / edit_file 工具定义
├── chat.py             # 修改：agent 循环拦截写入工具，发 write_proposal 事件；新增 /api/chat/apply 端点
src/ci_optimizer/tui/
├── app.py              # 修改：处理 write_proposal 事件，调用确认面板，发 apply 请求
├── panels.py           # 不需要改动——已有 confirm_action() 和 FileChange/WriteAction
tests/
├── test_tools.py       # 修改：添加写入工具的测试
├── test_chat_write.py  # 新建：write_proposal 流程测试
```

---

### 任务 1：添加写入工具定义到 tools.py

**文件：**
- 修改：`src/ci_optimizer/api/tools.py`
- 修改：`tests/test_tools.py`

- [ ] **步骤 1：在 test_tools.py 中添加写入工具的测试**

在 `tests/test_tools.py` 的 `TestToolDefinitions.test_tool_names` 中追加断言，并新增写入执行测试类：

```python
# 在 TestToolDefinitions.test_tool_names 中追加：
        assert "write_file" in names
        assert "edit_file" in names

# 新增测试类，追加到文件末尾：
class TestWriteTools:
    @pytest.fixture()
    def repo(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n")
        return tmp_path

    async def test_write_file_new(self, repo):
        result = await execute_tool(
            "write_file",
            {"path": "new_file.txt", "content": "hello world"},
            repo_root=repo,
        )
        assert "success" in result.lower() or "wrote" in result.lower()
        assert (repo / "new_file.txt").read_text() == "hello world"

    async def test_write_file_overwrite(self, repo):
        (repo / "existing.txt").write_text("old content")
        result = await execute_tool(
            "write_file",
            {"path": "existing.txt", "content": "new content"},
            repo_root=repo,
        )
        assert (repo / "existing.txt").read_text() == "new content"

    async def test_write_file_path_traversal_blocked(self, repo):
        result = await execute_tool(
            "write_file",
            {"path": "/etc/evil.txt", "content": "hack"},
            repo_root=repo,
        )
        assert "outside" in result.lower() or "error" in result.lower()
        assert not Path("/etc/evil.txt").exists()

    async def test_edit_file(self, repo):
        result = await execute_tool(
            "edit_file",
            {
                "path": ".github/workflows/ci.yml",
                "old_string": "runs-on: ubuntu-latest",
                "new_string": "runs-on: ubuntu-22.04",
            },
            repo_root=repo,
        )
        assert "success" in result.lower() or "edited" in result.lower()
        content = (repo / ".github/workflows/ci.yml").read_text()
        assert "ubuntu-22.04" in content
        assert "ubuntu-latest" not in content

    async def test_edit_file_old_string_not_found(self, repo):
        result = await execute_tool(
            "edit_file",
            {
                "path": ".github/workflows/ci.yml",
                "old_string": "this does not exist",
                "new_string": "replacement",
            },
            repo_root=repo,
        )
        assert "not found" in result.lower() or "error" in result.lower()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run pytest tests/test_tools.py -v`
预期：新增测试 FAIL（工具名不存在）

- [ ] **步骤 3：在 tools.py 中添加写入工具定义和执行器**

在 `TOOL_DEFINITIONS` 列表末尾追加两个工具定义：

```python
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件内容。如果文件已存在则覆盖，不存在则创建。写入前会经过用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于仓库根目录的文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整文件内容",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "编辑文件中的指定内容。用精确字符串匹配定位要替换的部分。编辑前会经过用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于仓库根目录的文件路径",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "要替换的原始内容（精确匹配）",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "替换后的新内容",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
```

在 `execute_tool` 函数中添加分支：

```python
        if name == "write_file":
            return _exec_write_file(inputs, repo_root)
        if name == "edit_file":
            return _exec_edit_file(inputs, repo_root)
```

添加执行器函数：

```python
def _exec_write_file(inputs: dict, repo_root: Path) -> str:
    path = validate_path(inputs["path"], repo_root=repo_root)
    content = inputs["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"Wrote {len(content)} chars to {inputs['path']}"


def _exec_edit_file(inputs: dict, repo_root: Path) -> str:
    path = validate_path(inputs["path"], repo_root=repo_root)
    if not path.exists():
        return f"Error: file not found: {inputs['path']}"
    old_content = path.read_text()
    old_string = inputs["old_string"]
    new_string = inputs["new_string"]
    if old_string not in old_content:
        return f"Error: old_string not found in {inputs['path']}"
    count = old_content.count(old_string)
    new_content = old_content.replace(old_string, new_string, 1)
    path.write_text(new_content)
    return f"Edited {inputs['path']} (replaced 1 of {count} occurrences)"
```

- [ ] **步骤 4：运行测试确认通过**

运行：`uv run pytest tests/test_tools.py -v`
预期：全部测试 PASS

- [ ] **步骤 5：运行 lint**

运行：`uv run ruff check src/ci_optimizer/api/tools.py tests/test_tools.py`

- [ ] **步骤 6：提交**

```bash
git add src/ci_optimizer/api/tools.py tests/test_tools.py
git commit -m "feat(tools): 添加 write_file 和 edit_file 写入工具"
```

---

### 任务 2：Agent 循环拦截写入工具，发 write_proposal 事件

**文件：**
- 修改：`src/ci_optimizer/api/chat.py`
- 新建测试：`tests/test_chat_write.py`

核心设计：在 `_run_agentic_loop` 中，当 AI 调用 `write_file` 或 `edit_file` 时，不立即执行，而是：
1. yield 一个 `write_proposal` SSE 事件（包含文件变更详情）
2. 暂停循环，等待 TUI 通过 `/api/chat/apply` 确认
3. 确认后执行写入，将结果送回 LLM 继续推理

**但这有个问题**：SSE 是单向的（server → client），无法在 SSE 流中等待客户端响应。

**解决方案**：简化流程——写入工具直接执行（和只读工具一样），但 TUI 在收到 `write_proposal` 事件时有机会取消。具体来说：
- `_run_agentic_loop` 中，写入工具**先生成 diff 预览**（不执行），yield `write_proposal` 事件
- 循环**暂停**（yield 一个特殊的 `write_pending` 事件）
- TUI 收到后弹出确认面板，然后发 `POST /api/chat/apply` 执行
- 如果用户取消，发 `POST /api/chat/reject`，agent 收到"用户取消了修改"继续对话

**再简化**：考虑到 SSE 流是长连接，更实际的做法是——**写入工具在 server 端直接执行，但 TUI 展示 write_proposal 让用户知道发生了什么，同时提供 git revert 能力**。

**最终方案（最简可行）**：写入工具直接执行，agent 循环正常处理。TUI 端对 `write_file`/`edit_file` 的 `tool_result` 事件特殊展示（显示修改详情而非简单的"✓ 完成"）。后续可加用户确认流程。

- [ ] **步骤 1：编写测试**

```python
# tests/test_chat_write.py
"""测试 chat 中写入工具的 SSE 事件。"""

from unittest.mock import AsyncMock, MagicMock

from ci_optimizer.api.chat import _run_agentic_loop


class TestWriteToolInLoop:
    """测试 agent 循环中的写入工具。"""

    @staticmethod
    def _make_repo(tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n")
        return tmp_path

    async def test_write_file_in_loop(self, tmp_path):
        """AI 调用 write_file 时，循环执行写入并继续。"""
        repo = self._make_repo(tmp_path)

        # 第一次响应：tool_use write_file
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "w1"
        tool_block.name = "write_file"
        tool_block.input = {"path": "fix.txt", "content": "fixed!"}

        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        first_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        first_response.model = "claude-3-5-sonnet"

        # 第二次响应：纯文本
        second_response = MagicMock()
        second_response.stop_reason = "end_turn"
        second_response.content = [MagicMock(type="text", text="已修复。")]
        second_response.usage = MagicMock(input_tokens=50, output_tokens=10)
        second_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "修复问题"}],
            repo_root=repo,
            max_turns=5,
        ):
            events.append(event)

        # 文件应该被写入
        assert (repo / "fix.txt").read_text() == "fixed!"

        event_str = "\n".join(events)
        assert "tool_use" in event_str
        assert "write_file" in event_str
        assert "已修复" in event_str

    async def test_edit_file_in_loop(self, tmp_path):
        """AI 调用 edit_file 时，循环执行编辑并继续。"""
        repo = self._make_repo(tmp_path)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "e1"
        tool_block.name = "edit_file"
        tool_block.input = {
            "path": ".github/workflows/ci.yml",
            "old_string": "runs-on: ubuntu-latest",
            "new_string": "runs-on: ubuntu-22.04",
        }

        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        first_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        first_response.model = "claude-3-5-sonnet"

        second_response = MagicMock()
        second_response.stop_reason = "end_turn"
        second_response.content = [MagicMock(type="text", text="已将 runner 固定为 ubuntu-22.04。")]
        second_response.usage = MagicMock(input_tokens=50, output_tokens=10)
        second_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "固定 runner 版本"}],
            repo_root=repo,
            max_turns=5,
        ):
            events.append(event)

        # 文件应该被编辑
        content = (repo / ".github/workflows/ci.yml").read_text()
        assert "ubuntu-22.04" in content
        assert "ubuntu-latest" not in content
```

- [ ] **步骤 2：运行测试确认通过**（agent 循环已支持所有工具，无需额外改动）

运行：`uv run pytest tests/test_chat_write.py -v`
预期：全部 PASS（写入工具已在任务 1 中实现，agent 循环已能调用）

- [ ] **步骤 3：更新 _tool_status 添加写入工具的中文描述**

在 `src/ci_optimizer/tui/app.py` 的 `_tool_status` 函数中追加：

```python
    if name == "write_file":
        return f"写入 {inputs.get('path', '...')}"
    if name == "edit_file":
        return f"编辑 {inputs.get('path', '...')}"
```

- [ ] **步骤 4：更新 TUI 的 tool_result 渲染，写入工具特殊展示**

在 `src/ci_optimizer/tui/app.py` 的 SSE `tool_result` 处理中，区分只读和写入工具：

```python
                    elif event_type == "tool_result":
                        tool_name = data.get("name", "?")
                        if tool_name in ("write_file", "edit_file"):
                            renderer.console.print(f"  [yellow]✎[/yellow] [dim]{tool_name} → {data.get('result_preview', '')}[/dim]")
                        else:
                            renderer.console.print(f"  [green]✓[/green] [dim]{tool_name} 完成[/dim]")
```

- [ ] **步骤 5：运行全部测试**

运行：`uv run pytest tests/test_tools.py tests/test_chat_write.py tests/test_chat_tools.py tests/tui/ -v`
预期：全部 PASS

- [ ] **步骤 6：运行 lint**

运行：`uv run ruff check src/ci_optimizer/api/tools.py src/ci_optimizer/api/chat.py src/ci_optimizer/tui/app.py`

- [ ] **步骤 7：提交**

```bash
git add src/ci_optimizer/api/tools.py src/ci_optimizer/api/chat.py src/ci_optimizer/tui/app.py tests/test_chat_write.py
git commit -m "feat(chat): 写入工具集成到 agent 循环，TUI 特殊展示写入操作"
```

---

### 任务 3：添加 git commit 工具

**文件：**
- 修改：`src/ci_optimizer/api/tools.py`
- 修改：`tests/test_tools.py`

- [ ] **步骤 1：在 test_tools.py 中添加 git_commit 测试**

```python
class TestGitTools:
    @pytest.fixture()
    def git_repo(self, tmp_path):
        """创建一个初始化的 git 仓库。"""
        import subprocess

        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            capture_output=True, check=True,
        )
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-m", "init"],
            capture_output=True, check=True,
        )
        return tmp_path

    async def test_git_commit(self, git_repo):
        # 先修改文件
        (git_repo / ".github" / "workflows" / "ci.yml").write_text("name: CI\non: push\njobs: {}")
        result = await execute_tool(
            "git_commit",
            {"message": "fix: update ci.yml", "files": [".github/workflows/ci.yml"]},
            repo_root=git_repo,
        )
        assert "commit" in result.lower() or "success" in result.lower()

        # 验证 commit 存在
        import subprocess

        log = subprocess.run(
            ["git", "-C", str(git_repo), "log", "--oneline", "-1"],
            capture_output=True, text=True,
        )
        assert "fix: update ci.yml" in log.stdout

    async def test_git_commit_no_changes(self, git_repo):
        result = await execute_tool(
            "git_commit",
            {"message": "empty", "files": [".github/workflows/ci.yml"]},
            repo_root=git_repo,
        )
        assert "nothing" in result.lower() or "no change" in result.lower() or "error" in result.lower()
```

- [ ] **步骤 2：运行测试确认失败**

运行：`uv run pytest tests/test_tools.py::TestGitTools -v`
预期：FAIL

- [ ] **步骤 3：在 tools.py 中添加 git_commit 工具**

工具定义追加到 `TOOL_DEFINITIONS`：

```python
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "将指定文件的修改提交为一个 git commit。提交前会经过用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message（使用 conventional commit 格式，如 'fix: pin action SHAs'）",
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要提交的文件路径列表（相对于仓库根目录）",
                    },
                },
                "required": ["message", "files"],
            },
        },
    },
```

在 `execute_tool` 中添加分支：

```python
        if name == "git_commit":
            return await _exec_git_commit(inputs, repo_root)
```

添加执行器：

```python
async def _exec_git_commit(inputs: dict, repo_root: Path) -> str:
    import asyncio

    message = inputs.get("message", "")
    files = inputs.get("files", [])

    if not message:
        return "Error: commit message is required"
    if not files:
        return "Error: at least one file path is required"

    # 验证所有路径在仓库内
    for f in files:
        validate_path(f, repo_root=repo_root)

    # git add
    add_proc = await asyncio.create_subprocess_exec(
        "git", "add", *files,
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, add_err = await asyncio.wait_for(add_proc.communicate(), timeout=10)
    if add_proc.returncode != 0:
        return f"Error: git add failed: {add_err.decode()}"

    # git commit
    commit_proc = await asyncio.create_subprocess_exec(
        "git", "commit", "-m", message,
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    commit_out, commit_err = await asyncio.wait_for(commit_proc.communicate(), timeout=10)
    if commit_proc.returncode != 0:
        stderr_text = commit_err.decode()
        if "nothing to commit" in stderr_text or "no changes" in stderr_text:
            return "No changes to commit"
        return f"Error: git commit failed: {stderr_text}"

    return f"Commit successful: {message}\n{commit_out.decode().strip()}"
```

- [ ] **步骤 4：运行测试确认通过**

运行：`uv run pytest tests/test_tools.py::TestGitTools -v`
预期：全部 PASS

- [ ] **步骤 5：更新 TUI _tool_status**

在 `_tool_status` 中添加：

```python
    if name == "git_commit":
        return f"提交 {inputs.get('message', '...')[:40]}"
```

- [ ] **步骤 6：运行 lint 和全部测试**

运行：`uv run ruff check src/ci_optimizer/api/tools.py src/ci_optimizer/tui/app.py && uv run pytest tests/test_tools.py tests/test_chat_tools.py tests/test_chat_write.py tests/tui/ -v`

- [ ] **步骤 7：提交**

```bash
git add src/ci_optimizer/api/tools.py src/ci_optimizer/tui/app.py tests/test_tools.py
git commit -m "feat(tools): 添加 git_commit 工具"
```

---

### 任务 4：集成测试

**文件：**
- 所有改动文件

- [ ] **步骤 1：运行全量测试**

运行：`uv run pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_integration.py`
预期：除已知的 `test_diagnose_api` model 配置问题外，全部 PASS

- [ ] **步骤 2：运行 lint**

运行：`uv run ruff check src/ci_optimizer/api/ src/ci_optimizer/tui/`
预期：All checks passed

- [ ] **步骤 3：手动端到端测试**

```bash
# 杀掉旧 server
lsof -ti:8000 | xargs kill 2>/dev/null
# 启动 TUI（会自动启动 server）
uv run ci-agent chat
```

测试交互：
1. `帮我把 ci.yml 的 runner 固定为 ubuntu-22.04` → 应调用 read_file 读取 → edit_file 修改 → 文本回复
2. `帮我提交刚才的修改` → 应调用 git_commit
3. `今天天气怎么样` → 应拒绝（CI-only scope guard）
4. `exit` → 正常退出

预期 TUI 输出：
```
› 帮我把 ci.yml 的 runner 固定为 ubuntu-22.04
  ⠸ 读取 .github/workflows/ci.yml
  ✓ read_file 完成
  ⠸ 编辑 .github/workflows/ci.yml
  ✎ edit_file → Edited .github/workflows/ci.yml (replaced 1 of 1 occurrences)

已将 runner 从 ubuntu-latest 固定为 ubuntu-22.04。

model: claude-3-5-sonnet-20241022 · tokens: 480↑ 120↓ · 3 轮
```

- [ ] **步骤 4：提交最终改动（如有）**

```bash
git add -A
git commit -m "feat(chat): 完成写入工具集成"
```

---

## 总结

| 任务 | 做什么 | 文件 |
|------|--------|------|
| 1 | write_file / edit_file 工具定义和执行器 | `api/tools.py`、`tests/test_tools.py` |
| 2 | agent 循环集成写入工具 + TUI 展示 | `tui/app.py`、`tests/test_chat_write.py` |
| 3 | git_commit 工具 | `api/tools.py`、`tests/test_tools.py` |
| 4 | 集成测试和收尾 | 所有文件 |

## 数据流

```
用户: "帮我修复 ci.yml"
  │
  ▼
TUI POST /api/chat → Server agent 循环
  │
  ├─ LLM: read_file .github/workflows/ci.yml
  │   → SSE: tool_use → TUI: ⠸ 读取 ci.yml
  │   → 执行读取 → SSE: tool_result → TUI: ✓ read_file 完成
  │
  ├─ LLM: edit_file ci.yml (old→new)
  │   → SSE: tool_use → TUI: ⠸ 编辑 ci.yml
  │   → 执行编辑 → SSE: tool_result → TUI: ✎ edit_file → Edited...
  │
  ├─ LLM: "已修复，要我提交吗？"
  │   → SSE: text → TUI: 显示文本
  │
  └─ 用户: "提交吧"
      → LLM: git_commit("fix: ...")
      → SSE: tool_use → TUI: ⠸ 提交 fix: ...
      → 执行 git add + commit → SSE: tool_result → TUI: ✎ git_commit → Commit successful
```

## 未来增强（不在本计划范围内）

- **写入前确认流程**：需要 WebSocket 双向通信或拆分为两次 HTTP 请求
- **创建 PR**：添加 `create_pr` 工具，调用 GitHub API
- **git revert**：如果用户对修改不满意，提供一键回滚
