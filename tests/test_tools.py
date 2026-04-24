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
        assert "write_file" in names
        assert "edit_file" in names
        assert "git_commit" in names


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




class TestWriteTools:
    @pytest.fixture()
    def repo(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n")
        return tmp_path

    async def test_write_file_new(self, repo):
        result = await execute_tool("write_file", {"path": "new_file.txt", "content": "hello world"}, repo_root=repo)
        assert "wrote" in result.lower()
        assert (repo / "new_file.txt").read_text() == "hello world"

    async def test_write_file_overwrite(self, repo):
        (repo / "existing.txt").write_text("old content")
        result = await execute_tool("write_file", {"path": "existing.txt", "content": "new content"}, repo_root=repo)
        assert (repo / "existing.txt").read_text() == "new content"

    async def test_write_file_path_traversal_blocked(self, repo):
        result = await execute_tool("write_file", {"path": "/etc/evil.txt", "content": "hack"}, repo_root=repo)
        assert "outside" in result.lower() or "error" in result.lower()
        assert not Path("/etc/evil.txt").exists()

    async def test_edit_file(self, repo):
        result = await execute_tool("edit_file", {"path": ".github/workflows/ci.yml", "old_string": "runs-on: ubuntu-latest", "new_string": "runs-on: ubuntu-22.04"}, repo_root=repo)
        assert "edited" in result.lower()
        content = (repo / ".github/workflows/ci.yml").read_text()
        assert "ubuntu-22.04" in content
        assert "ubuntu-latest" not in content

    async def test_edit_file_old_string_not_found(self, repo):
        result = await execute_tool("edit_file", {"path": ".github/workflows/ci.yml", "old_string": "this does not exist", "new_string": "replacement"}, repo_root=repo)
        assert "not found" in result.lower()


class TestGitTools:
    @pytest.fixture()
    def git_repo(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], capture_output=True, check=True)
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True, check=True)
        return tmp_path

    async def test_git_commit(self, git_repo):
        (git_repo / ".github" / "workflows" / "ci.yml").write_text("name: CI\non: push\njobs: {}")
        result = await execute_tool("git_commit", {"message": "fix: update ci.yml", "files": [".github/workflows/ci.yml"]}, repo_root=git_repo)
        assert "commit" in result.lower() or "success" in result.lower()
        import subprocess
        log = subprocess.run(["git", "-C", str(git_repo), "log", "--oneline", "-1"], capture_output=True, text=True)
        assert "fix: update ci.yml" in log.stdout

    async def test_git_commit_no_changes(self, git_repo):
        result = await execute_tool("git_commit", {"message": "empty", "files": [".github/workflows/ci.yml"]}, repo_root=git_repo)
        assert "nothing" in result.lower() or "no change" in result.lower() or "error" in result.lower()
