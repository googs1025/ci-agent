"""Repository detection and user confirmation for TUI startup."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ci_optimizer.resolver import detect_github_remote


@dataclass
class RepoContext:
    """Detected repository information."""

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
    """Run a git command and return stripped stdout, or None on failure."""
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
    """Detect a git repository at *path* (defaults to cwd).

    Returns a RepoContext if the path is inside a git worktree, else None.
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
    """Interactive prompt to confirm or switch the working repository.

    Uses prompt_toolkit's async API to avoid nested event loop issues.
    Returns the confirmed RepoContext.
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
