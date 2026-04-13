"""Input resolver: detect local path vs GitHub URL and extract repo info."""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

GITHUB_URL_PATTERN = re.compile(r"(?:https?://)?github\.com/([^/]+)/([^/\s.]+?)(?:\.git)?/?$")

# Matches "owner/repo" shorthand (no slashes beyond the one separator, no spaces)
GITHUB_SHORTHAND_PATTERN = re.compile(r"^([a-zA-Z0-9\-_.]+)/([a-zA-Z0-9\-_.]+)$")


@dataclass
class ResolvedInput:
    local_path: Path
    owner: str | None = None
    repo: str | None = None
    is_remote: bool = False
    temp_dir: str | None = None  # set if we cloned to a temp dir


def is_github_url(input_str: str) -> bool:
    return bool(GITHUB_URL_PATTERN.match(input_str))


def is_github_shorthand(input_str: str) -> bool:
    """Check if input is 'owner/repo' shorthand (not a local path)."""
    if GITHUB_SHORTHAND_PATTERN.match(input_str):
        # Make sure it's not an existing local path
        return not Path(input_str).exists()
    return False


def parse_github_url(url: str) -> tuple[str, str]:
    """Extract owner/repo from a GitHub URL."""
    match = GITHUB_URL_PATTERN.match(url)
    if not match:
        raise ValueError(f"Invalid GitHub URL: {url}")
    return match.group(1), match.group(2)


def detect_github_remote(local_path: Path) -> tuple[str, str] | None:
    """Parse owner/repo from a local git repo's remote URL."""
    git_config = local_path / ".git" / "config"
    if not git_config.exists():
        return None

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=local_path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        remote_url = result.stdout.strip()
        # Handle SSH URLs: git@github.com:owner/repo.git
        ssh_match = re.match(r"git@github\.com:([^/]+)/([^/\s.]+?)(?:\.git)?$", remote_url)
        if ssh_match:
            return ssh_match.group(1), ssh_match.group(2)
        # Handle HTTPS URLs
        https_match = GITHUB_URL_PATTERN.match(remote_url)
        if https_match:
            return https_match.group(1), https_match.group(2)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def clone_repo(url: str, timeout: int = 120) -> tuple[Path, str]:
    """Shallow clone a GitHub repo to a temp directory. Returns (path, temp_dir)."""
    temp_dir = tempfile.mkdtemp(prefix="ci-agent-")
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", url, temp_dir],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(
            f"Repository clone timed out after {timeout}s. "
            "The repository may be too large or the network is slow. "
            "Try using a local path instead."
        )
    except subprocess.CalledProcessError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(
            f"Failed to clone repository: {e.stderr or e.stdout or str(e)}"
        )
    return Path(temp_dir), temp_dir


def resolve_input(input_str: str) -> ResolvedInput:
    """Resolve user input to a ResolvedInput with local path and optional GitHub info.

    Accepts:
      - GitHub URL: https://github.com/owner/repo
      - Shorthand: owner/repo (auto-expands to GitHub URL)
      - Local path: /path/to/repo or ./repo
    """
    if is_github_url(input_str):
        owner, repo = parse_github_url(input_str)
        local_path, temp_dir = clone_repo(input_str)
        return ResolvedInput(
            local_path=local_path,
            owner=owner,
            repo=repo,
            is_remote=True,
            temp_dir=temp_dir,
        )

    if is_github_shorthand(input_str):
        match = GITHUB_SHORTHAND_PATTERN.match(input_str)
        owner, repo = match.group(1), match.group(2)
        url = f"https://github.com/{owner}/{repo}"
        local_path, temp_dir = clone_repo(url)
        return ResolvedInput(
            local_path=local_path,
            owner=owner,
            repo=repo,
            is_remote=True,
            temp_dir=temp_dir,
        )

    local_path = Path(input_str).resolve()
    if not local_path.exists():
        raise FileNotFoundError(f"Path does not exist: {input_str}")

    remote = detect_github_remote(local_path)
    owner, repo = remote if remote else (None, None)

    return ResolvedInput(
        local_path=local_path,
        owner=owner,
        repo=repo,
        is_remote=False,
    )
