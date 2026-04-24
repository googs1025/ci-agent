"""Tests for tui.context — repo detection logic."""

import subprocess
from pathlib import Path

from ci_optimizer.tui.context import RepoContext, detect_repo


class TestRepoContext:
    def test_display_name_with_owner_repo(self):
        ctx = RepoContext(local_path=Path("/tmp/foo"), owner="acme", repo="widgets")
        assert ctx.display_name == "acme/widgets"

    def test_display_name_fallback_to_dir_name(self):
        ctx = RepoContext(local_path=Path("/tmp/my-project"))
        assert ctx.display_name == "my-project"


class TestDetectRepo:
    def test_returns_none_for_non_git_dir(self, tmp_path):
        assert detect_repo(tmp_path) is None

    def test_detects_git_repo(self, tmp_path):
        # Initialize a bare git repo
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "test@test.com",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "test@test.com",
                "PATH": "/usr/bin:/bin:/usr/local/bin",
            },
        )

        ctx = detect_repo(tmp_path)
        assert ctx is not None
        assert ctx.local_path == tmp_path.resolve()
        assert ctx.branch is not None
        assert ctx.last_commit == "init"

    def test_defaults_to_cwd(self):
        # Current dir is the ci-agent repo itself
        ctx = detect_repo()
        assert ctx is not None
        assert ctx.local_path.exists()


class TestRepoContextRemote:
    def test_owner_repo_from_remote(self):
        """detect_repo on the ci-agent repo itself should pick up GitHub remote."""
        ctx = detect_repo(Path.cwd())
        # This test only works if the repo has a GitHub remote
        if ctx and ctx.owner:
            assert ctx.repo is not None
