"""测试 /api/chat 的 tool-use agent 循环。"""

from unittest.mock import AsyncMock, MagicMock

from ci_optimizer.api.chat import _run_agentic_loop


class TestAgenticLoop:
    """测试多轮 tool-use 循环。"""

    @staticmethod
    def _make_repo(tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: push\njobs:\n  build:\n    runs-on: ubuntu-latest")
        return tmp_path

    async def test_no_tool_use_returns_text(self, tmp_path):
        """模型返回纯文本时，循环输出 text 事件后停止。"""
        repo = self._make_repo(tmp_path)

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(type="text", text="你好！")]
        mock_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        mock_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "hi"}],
            repo_root=repo,
            max_turns=5,
        ):
            events.append(event)

        assert any('"content":' in e for e in events)
        assert any('"input_tokens"' in e for e in events)

    async def test_tool_use_then_text(self, tmp_path):
        """模型使用工具时，循环执行工具后继续。"""
        repo = self._make_repo(tmp_path)

        # 第一次响应：tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool_1"
        tool_block.name = "list_workflows"
        tool_block.input = {}

        first_response = MagicMock()
        first_response.stop_reason = "tool_use"
        first_response.content = [tool_block]
        first_response.usage = MagicMock(input_tokens=10, output_tokens=5)
        first_response.model = "claude-3-5-sonnet"

        # 第二次响应：纯文本
        second_response = MagicMock()
        second_response.stop_reason = "end_turn"
        second_response.content = [MagicMock(type="text", text="找到 1 个 workflow。")]
        second_response.usage = MagicMock(input_tokens=50, output_tokens=10)
        second_response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[first_response, second_response])

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "列出 workflows"}],
            repo_root=repo,
            max_turns=5,
        ):
            events.append(event)

        event_str = "\n".join(events)
        assert "tool_use" in event_str
        assert "tool_result" in event_str
        assert "找到 1 个 workflow" in event_str

    async def test_max_turns_limit(self, tmp_path):
        """达到 max_turns 上限时停止。"""
        repo = self._make_repo(tmp_path)

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.id = "tool_1"
        tool_block.name = "list_workflows"
        tool_block.input = {}

        response = MagicMock()
        response.stop_reason = "tool_use"
        response.content = [tool_block]
        response.usage = MagicMock(input_tokens=10, output_tokens=5)
        response.model = "claude-3-5-sonnet"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        events = []
        async for event in _run_agentic_loop(
            client=mock_client,
            model="claude-3-5-sonnet",
            system="test",
            messages=[{"role": "user", "content": "无限循环"}],
            repo_root=repo,
            max_turns=2,
        ):
            events.append(event)

        assert mock_client.messages.create.call_count <= 2
