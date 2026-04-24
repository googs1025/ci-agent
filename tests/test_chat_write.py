"""测试 chat 中写入工具的 write_proposal 流程。"""

from unittest.mock import AsyncMock, MagicMock

from ci_optimizer.api.chat import _run_agentic_loop


class TestWriteToolInLoop:
    """测试 agent 循环中的写入工具——应该生成 write_proposal 而非直接执行。"""

    @staticmethod
    def _make_repo(tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n")
        return tmp_path

    async def test_write_file_yields_proposal(self, tmp_path):
        """AI 调用 write_file 时，循环应 yield write_proposal 并暂停，不直接写入。"""
        repo = self._make_repo(tmp_path)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "w1"
        tool_block.name = "write_file"
        tool_block.input = {"path": "fix.txt", "content": "fixed!"}

        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [tool_block]
        response.usage = MagicMock(input_tokens=10, output_tokens=5)
        response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        events = []
        async for event in _run_agentic_loop(
            client=mock_client, model="claude-3-5-sonnet", system="test",
            messages=[{"role": "user", "content": "写文件"}],
            repo_root=repo, max_turns=5,
        ):
            events.append(event)

        event_str = "\n".join(events)
        assert "write_proposal" in event_str
        assert "pending_writes" in event_str
        # 文件不应该被写入（还未确认）
        assert not (repo / "fix.txt").exists()
        # LLM 只被调用 1 次（循环暂停了）
        assert mock_client.messages.create.call_count == 1

    async def test_edit_file_yields_proposal_with_diff(self, tmp_path):
        """AI 调用 edit_file 时，write_proposal 应包含 diff。"""
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

        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [tool_block]
        response.usage = MagicMock(input_tokens=10, output_tokens=5)
        response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        events = []
        async for event in _run_agentic_loop(
            client=mock_client, model="claude-3-5-sonnet", system="test",
            messages=[{"role": "user", "content": "编辑文件"}],
            repo_root=repo, max_turns=5,
        ):
            events.append(event)

        event_str = "\n".join(events)
        assert "write_proposal" in event_str
        assert "ubuntu-22.04" in event_str
        assert "ubuntu-latest" in event_str
        # 文件不应该被修改
        content = (repo / ".github/workflows/ci.yml").read_text()
        assert "ubuntu-latest" in content

    async def test_read_tools_still_execute_directly(self, tmp_path):
        """只读工具应继续直接执行，不走 write_proposal。"""
        repo = self._make_repo(tmp_path)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "r1"
        tool_block.name = "list_workflows"
        tool_block.input = {}

        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        first_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        first_response.model = "claude-3-5-sonnet"

        second_response = MagicMock()
        second_response.stop_reason = "end_turn"
        second_response.content = [MagicMock(type="text", text="找到 1 个 workflow。")]
        second_response.usage = MagicMock(input_tokens=50, output_tokens=10)
        second_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

        events = []
        async for event in _run_agentic_loop(
            client=mock_client, model="claude-3-5-sonnet", system="test",
            messages=[{"role": "user", "content": "列出 workflows"}],
            repo_root=repo, max_turns=5,
        ):
            events.append(event)

        event_str = "\n".join(events)
        assert "write_proposal" not in event_str
        assert "tool_result" in event_str
        assert "找到 1 个 workflow" in event_str
