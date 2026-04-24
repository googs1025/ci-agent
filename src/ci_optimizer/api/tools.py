"""CI 专用工具——用于 chat agent。

每个工具在确认的仓库根目录内执行。路径经过验证，防止越界访问。
"""

from __future__ import annotations

import difflib
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
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将内容写入仓库中的文件（新建或覆盖）。路径必须在仓库根目录内。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于仓库根目录的路径（如 '.github/workflows/ci.yml'、'src/main.py'）",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入文件的内容",
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
            "description": "将文件中的指定字符串替换为新字符串（替换第一个匹配项）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于仓库根目录的路径",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "要替换的原始字符串",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "替换后的新字符串",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "将指定文件的修改提交为一个 git commit。提交前会经过用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message（使用 conventional commit 格式）"},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "要提交的文件路径列表"},
                },
                "required": ["message", "files"],
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
    "git log",
    "git diff",
    "git show",
    "git status",
    "git branch",
    "git tag",
    "git rev-parse",
    "git remote",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "find",
    "tree",
    "grep",
    "rg",
    "awk",
    "sort",
    "uniq",
    # Script execution / utilities
    "python3",
    "python",
    "curl",
    "jq",
    "sed",
    "cut",
    "echo",
    "printf",
    # GitHub CLI — read-only subcommands
    "gh run list",
    "gh run view",
    "gh run watch",
    "gh pr list",
    "gh pr view",
    "gh pr checks",
    "gh pr status",
    "gh issue list",
    "gh issue view",
    "gh issue status",
    "gh workflow list",
    "gh workflow view",
    "gh repo view",
    "gh release list",
    "gh release view",
)

BLOCKED_COMMANDS = {"rm", "mv", "cp", "chmod", "chown", "sudo", "wget", "pip", "npm", "docker"}


def _is_command_safe(command: str) -> bool:
    """判断命令是否为只读安全命令。"""
    cmd_stripped = command.strip()
    first_word = cmd_stripped.split()[0] if cmd_stripped else ""
    if first_word in BLOCKED_COMMANDS:
        return False
    return any(cmd_stripped.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES)


# ── 写入工具名称集合（需要用户确认才能执行）─────────────────────────────────

WRITE_TOOL_NAMES = {"write_file", "edit_file", "git_commit"}


# ── 写入预览（生成 diff 但不执行）─────────────────────────────────────────────


def preview_write(name: str, inputs: dict, *, repo_root: Path) -> dict:
    """为写入工具生成预览信息（diff），不实际执行。

    返回 dict: {"path": str, "diff": str, "added": int, "removed": int, "action": str}
    """
    if name == "write_file":
        return _preview_write_file(inputs, repo_root)
    if name == "edit_file":
        return _preview_edit_file(inputs, repo_root)
    if name == "git_commit":
        return {"action": "git_commit", "message": inputs.get("message", ""), "files": inputs.get("files", [])}
    return {"action": name, "error": f"unknown write tool: {name}"}


def _preview_write_file(inputs: dict, repo_root: Path) -> dict:
    path = validate_path(inputs["path"], repo_root=repo_root)
    new_content = inputs["content"]
    rel_path = inputs["path"]

    if path.exists():
        old_content = path.read_text(errors="replace")
        diff_lines = list(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
        )
    else:
        diff_lines = ["--- /dev/null\n", f"+++ b/{rel_path}\n"]
        diff_lines += [f"+{line}\n" for line in new_content.splitlines()]

    diff_text = "".join(diff_lines)
    added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

    return {"action": "write_file", "path": rel_path, "diff": diff_text, "added": added, "removed": removed}


def _preview_edit_file(inputs: dict, repo_root: Path) -> dict:
    path = validate_path(inputs["path"], repo_root=repo_root)
    rel_path = inputs["path"]

    if not path.exists():
        return {"action": "edit_file", "path": rel_path, "error": f"file not found: {rel_path}"}

    old_content = path.read_text()
    old_string = inputs["old_string"]
    new_string = inputs["new_string"]

    if old_string not in old_content:
        return {"action": "edit_file", "path": rel_path, "error": f"old_string not found in {rel_path}"}

    new_content = old_content.replace(old_string, new_string, 1)
    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )
    diff_text = "".join(diff_lines)
    added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

    return {"action": "edit_file", "path": rel_path, "diff": diff_text, "added": added, "removed": removed}


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
        if name == "write_file":
            return _exec_write_file(inputs, repo_root)
        if name == "edit_file":
            return _exec_edit_file(inputs, repo_root)
        if name == "git_commit":
            return await _exec_git_commit(inputs, repo_root)
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


async def _exec_git_commit(inputs: dict, repo_root: Path) -> str:
    import asyncio

    message = inputs.get("message", "")
    files = inputs.get("files", [])
    if not message:
        return "Error: commit message is required"
    if not files:
        return "Error: at least one file path is required"

    for f in files:
        validate_path(f, repo_root=repo_root)

    add_proc = await asyncio.create_subprocess_exec(
        "git",
        "add",
        *files,
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, add_err = await asyncio.wait_for(add_proc.communicate(), timeout=10)
    if add_proc.returncode != 0:
        return f"Error: git add failed: {add_err.decode()}"

    commit_proc = await asyncio.create_subprocess_exec(
        "git",
        "commit",
        "-m",
        message,
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
