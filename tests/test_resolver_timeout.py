"""Tests for clone_repo error handling and workflow file limits."""

import subprocess
from unittest.mock import patch

import pytest

from ci_optimizer.prefetch import MAX_WORKFLOW_FILES, prepare_context
from ci_optimizer.resolver import ResolvedInput, clone_repo


class TestCloneRepoTimeout:
    def test_timeout_raises_runtime_error(self):
        with patch(
            "ci_optimizer.resolver.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git clone", timeout=120),
        ):
            with pytest.raises(RuntimeError, match="clone timed out after 120s"):
                clone_repo("https://github.com/owner/repo")

    def test_timeout_cleans_up_temp_dir(self, tmp_path):
        fake_temp = tmp_path / "ci-agent-test"
        fake_temp.mkdir()

        with (
            patch("ci_optimizer.resolver.tempfile.mkdtemp", return_value=str(fake_temp)),
            patch(
                "ci_optimizer.resolver.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git clone", timeout=120),
            ),
        ):
            with pytest.raises(RuntimeError):
                clone_repo("https://github.com/owner/repo")

        assert not fake_temp.exists()

    def test_custom_timeout_value(self):
        with patch(
            "ci_optimizer.resolver.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git clone", timeout=30),
        ):
            with pytest.raises(RuntimeError, match="clone timed out after 30s"):
                clone_repo("https://github.com/owner/repo", timeout=30)


class TestCloneRepoFailure:
    def test_called_process_error_raises_runtime_error(self):
        with patch(
            "ci_optimizer.resolver.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                128, "git clone", stderr="fatal: repository not found"
            ),
        ):
            with pytest.raises(RuntimeError, match="Failed to clone repository"):
                clone_repo("https://github.com/owner/repo")

    def test_stderr_included_in_message(self):
        with patch(
            "ci_optimizer.resolver.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                128, "git clone", stderr="fatal: repository not found"
            ),
        ):
            with pytest.raises(RuntimeError, match="repository not found"):
                clone_repo("https://github.com/owner/repo")

    def test_failure_cleans_up_temp_dir(self, tmp_path):
        fake_temp = tmp_path / "ci-agent-test"
        fake_temp.mkdir()

        with (
            patch("ci_optimizer.resolver.tempfile.mkdtemp", return_value=str(fake_temp)),
            patch(
                "ci_optimizer.resolver.subprocess.run",
                side_effect=subprocess.CalledProcessError(128, "git clone", stderr="error"),
            ),
        ):
            with pytest.raises(RuntimeError):
                clone_repo("https://github.com/owner/repo")

        assert not fake_temp.exists()


class TestWorkflowFileLimit:
    @pytest.mark.asyncio
    async def test_workflow_files_truncated_at_limit(self, tmp_path):
        """Repos with more than MAX_WORKFLOW_FILES should be truncated."""
        workflows_dir = tmp_path / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        # Create more workflow files than the limit
        for i in range(MAX_WORKFLOW_FILES + 5):
            (workflows_dir / f"wf-{i:03d}.yml").write_text(f"name: Workflow {i}\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n")

        resolved = ResolvedInput(local_path=tmp_path)
        ctx = await prepare_context(resolved)

        assert len(ctx.workflow_files) == MAX_WORKFLOW_FILES

    @pytest.mark.asyncio
    async def test_workflow_files_under_limit_unchanged(self, tmp_repo):
        """Repos under the limit should keep all workflow files."""
        resolved = ResolvedInput(local_path=tmp_repo)
        ctx = await prepare_context(resolved)

        assert len(ctx.workflow_files) == 2
