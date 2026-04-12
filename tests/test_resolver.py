"""Tests for resolver module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ci_optimizer.resolver import (
    detect_github_remote,
    is_github_shorthand,
    is_github_url,
    parse_github_url,
    resolve_input,
)


class TestIsGithubUrl:
    def test_https_url(self):
        assert is_github_url("https://github.com/owner/repo") is True

    def test_https_url_with_git_suffix(self):
        assert is_github_url("https://github.com/owner/repo.git") is True

    def test_https_url_with_trailing_slash(self):
        assert is_github_url("https://github.com/owner/repo/") is True

    def test_http_url(self):
        assert is_github_url("http://github.com/owner/repo") is True

    def test_without_protocol(self):
        assert is_github_url("github.com/owner/repo") is True

    def test_local_path(self):
        assert is_github_url("/Users/foo/bar") is False

    def test_relative_path(self):
        assert is_github_url("./my-repo") is False

    def test_gitlab_url(self):
        assert is_github_url("https://gitlab.com/owner/repo") is False

    def test_empty_string(self):
        assert is_github_url("") is False


class TestIsGithubShorthand:
    def test_owner_repo(self):
        assert is_github_shorthand("vllm-project/aibrix") is True

    def test_simple(self):
        assert is_github_shorthand("octocat/hello-world") is True

    def test_with_dots(self):
        assert is_github_shorthand("kubernetes-sigs/descheduler") is True

    def test_full_url_not_shorthand(self):
        assert is_github_shorthand("https://github.com/owner/repo") is False

    def test_local_path_not_shorthand(self):
        assert is_github_shorthand("/Users/foo/bar") is False

    def test_single_word_not_shorthand(self):
        assert is_github_shorthand("myrepo") is False

    def test_existing_local_path(self, tmp_path):
        # Create a path that looks like owner/repo but exists locally
        (tmp_path / "fake").mkdir()
        with patch("ci_optimizer.resolver.Path") as MockPath:
            mock_instance = MagicMock()
            mock_instance.exists.return_value = True
            MockPath.return_value = mock_instance
            assert is_github_shorthand("fake/repo") is False


class TestParseGithubUrl:
    def test_simple_url(self):
        owner, repo = parse_github_url("https://github.com/octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_url_with_git_suffix(self):
        owner, repo = parse_github_url("https://github.com/octocat/hello-world.git")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_url_without_protocol(self):
        owner, repo = parse_github_url("github.com/octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            parse_github_url("https://not-github.com/owner/repo")

    def test_url_with_dashes_and_dots(self):
        owner, repo = parse_github_url("https://github.com/my-org/my-repo-v2")
        assert owner == "my-org"
        assert repo == "my-repo-v2"


class TestDetectGithubRemote:
    def test_no_git_dir(self, tmp_path):
        assert detect_github_remote(tmp_path) is None

    def test_with_https_remote(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://github.com/octocat/hello-world.git\n"

        with patch("subprocess.run", return_value=mock_result):
            result = detect_github_remote(tmp_path)
            assert result == ("octocat", "hello-world")

    def test_with_ssh_remote(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "git@github.com:octocat/hello-world.git\n"

        with patch("subprocess.run", return_value=mock_result):
            result = detect_github_remote(tmp_path)
            assert result == ("octocat", "hello-world")

    def test_git_command_fails(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("")

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            assert detect_github_remote(tmp_path) is None

    def test_non_github_remote(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://gitlab.com/owner/repo.git\n"

        with patch("subprocess.run", return_value=mock_result):
            assert detect_github_remote(tmp_path) is None


class TestResolveInput:
    def test_local_path(self, tmp_path):
        resolved = resolve_input(str(tmp_path))
        assert resolved.local_path == tmp_path
        assert resolved.is_remote is False

    def test_local_path_not_exists(self):
        with pytest.raises(FileNotFoundError, match="Path does not exist"):
            resolve_input("/nonexistent/path/that/does/not/exist")

    def test_github_url_clones(self):
        mock_path = Path("/tmp/ci-agent-test")
        with patch("ci_optimizer.resolver.clone_repo", return_value=(mock_path, "/tmp/ci-agent-test")) as mock_clone:
            resolved = resolve_input("https://github.com/octocat/hello-world")
            mock_clone.assert_called_once_with("https://github.com/octocat/hello-world")
            assert resolved.owner == "octocat"
            assert resolved.repo == "hello-world"
            assert resolved.is_remote is True
            assert resolved.local_path == mock_path

    def test_local_path_with_remote(self, tmp_path):
        with patch("ci_optimizer.resolver.detect_github_remote", return_value=("owner", "repo")):
            resolved = resolve_input(str(tmp_path))
            assert resolved.owner == "owner"
            assert resolved.repo == "repo"
            assert resolved.is_remote is False

    def test_local_path_without_remote(self, tmp_path):
        with patch("ci_optimizer.resolver.detect_github_remote", return_value=None):
            resolved = resolve_input(str(tmp_path))
            assert resolved.owner is None
            assert resolved.repo is None

    def test_shorthand_owner_repo(self):
        mock_path = Path("/tmp/ci-agent-test")
        with patch("ci_optimizer.resolver.clone_repo", return_value=(mock_path, "/tmp/ci-agent-test")) as mock_clone:
            resolved = resolve_input("vllm-project/aibrix")
            mock_clone.assert_called_once_with("https://github.com/vllm-project/aibrix")
            assert resolved.owner == "vllm-project"
            assert resolved.repo == "aibrix"
            assert resolved.is_remote is True
