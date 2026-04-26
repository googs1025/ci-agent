"""Repository detection and user confirmation for TUI startup."""
# 架构角色：TUI 启动流程中的仓库感知层，在进入 REPL 前完成仓库上下文的建立。
# 核心职责：
#   1. 通过 git 命令探测当前目录所在的 Git 工作树根、分支、最近提交
#   2. 调用 resolver 模块解析 GitHub remote，得到 owner/repo
#   3. 用 confirm_repo() 交互式地让用户确认或手动切换仓库路径
# 与其他模块的关系：
#   - app.py 在 setup 之后调用 detect_repo() + confirm_repo() 得到 RepoContext
#   - RepoContext 在整个 REPL 生命周期内作为仓库元数据随每次 /api/chat 请求一起发送

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ci_optimizer.resolver import detect_github_remote


@dataclass
class RepoContext:
    """已检测到的 Git 仓库上下文，贯穿整个 TUI 会话生命周期。
    display_name 属性在 owner/repo 已知时返回 GitHub 格式，否则降级为目录名。
    """

    local_path: Path
    owner: str | None = None
    repo: str | None = None
    branch: str | None = None
    last_commit: str | None = None

    @property
    def display_name(self) -> str:
        if self.owner and self.repo:
            return f"{self.owner}/{self.repo}"
        return self.local_path.name


def _git_output(cwd: Path, *args: str) -> str | None:
    """在指定目录执行 git 子命令，返回去除首尾空白的 stdout；超时或命令失败则返回 None。
    timeout=5 防止在挂载网络盘等慢路径上卡住 TUI 启动。
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def detect_repo(path: Path | None = None) -> RepoContext | None:
    """在 path（默认 cwd）处探测 Git 仓库，构建并返回 RepoContext。
    若路径不在任何 Git 工作树中，返回 None（由调用方决定如何提示用户）。
    """
    path = (path or Path.cwd()).resolve()

    toplevel = _git_output(path, "rev-parse", "--show-toplevel")
    if not toplevel:
        return None

    repo_root = Path(toplevel)
    branch = _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")

    # Last commit subject
    last_commit = _git_output(repo_root, "log", "-1", "--format=%s")

    remote = detect_github_remote(repo_root)
    owner, repo = remote if remote else (None, None)

    return RepoContext(
        local_path=repo_root,
        owner=owner,
        repo=repo,
        branch=branch,
        last_commit=last_commit,
    )


async def confirm_repo(ctx: RepoContext | None) -> RepoContext:
    """交互式确认或切换工作仓库，返回最终生效的 RepoContext。
    使用 prompt_toolkit 的 async API，与 asyncio 事件循环兼容，避免嵌套循环问题。
    用户输入 'q' 或 EOFError 时抛出 EOFError，由 app.py 捕获后优雅退出。
    """
    from prompt_toolkit import PromptSession
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    session = PromptSession()

    if ctx:
        info_lines = [f"  分支：{ctx.branch or 'unknown'}"]
        if ctx.last_commit:
            info_lines.append(f"  最近提交：{ctx.last_commit}")
        info_text = "\n".join(info_lines)

        console.print(
            Panel(
                f"检测到 Git 仓库：[bold]{ctx.display_name}[/bold]\n{info_text}",
                title="ci-agent",
                border_style="cyan",
            )
        )

        answer = await session.prompt_async("使用此仓库？[Y/n] ", default="Y")
        if answer.strip().lower() not in ("n", "no"):
            return ctx

    # Manual path input
    while True:
        raw = await session.prompt_async("请输入仓库路径或 owner/repo（输入 q 退出）：")
        raw = raw.strip()
        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            raise EOFError
        new_ctx = detect_repo(Path(raw))
        if new_ctx:
            return new_ctx
        console.print(f"[red]未检测到 Git 仓库：{raw}[/red]")
