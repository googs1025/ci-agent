"""Streaming chat endpoint for the CI Agent TUI and web frontend."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ci_optimizer.api.auth import verify_api_key
from ci_optimizer.api.tools import ANTHROPIC_TOOLS, TOOL_DEFINITIONS, WRITE_TOOL_NAMES, execute_tool, preview_write
from ci_optimizer.config import AgentConfig

logger = logging.getLogger(__name__)

chat_router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])

# ── CI-only scope guard ──────────────────────────────────────────────────────

CI_SCOPE_SYSTEM_PROMPT = """\
You are CI Agent, a specialized assistant that ONLY helps with CI/CD related topics.

Your scope is strictly limited to:
- GitHub Actions workflow analysis and optimization
- CI/CD pipeline debugging and failure diagnosis
- Workflow file (.yml) editing and best practices
- CI build time, cost, and efficiency optimization
- CI security (pinning actions, secrets management, supply chain)
- Flaky test diagnosis in CI context
- GitHub Actions runner configuration
- CI/CD architecture and design patterns

You have access to tools that can read files, search code, run shell/gh commands, and list workflows.
Use these tools proactively to answer questions — don't ask the user to paste file contents.

TOOL USAGE STRATEGY (follow this priority order):
1. For failure diagnosis: FIRST run `gh run list --limit 10 --json databaseId,workflowName,conclusion,headBranch,createdAt` to find recent failures, THEN `gh run view <id> --log-failed` for the failing step output. Only read workflow files if the log points to a config issue.
2. For workflow questions: read only the relevant workflow file, not all of them.
3. Use the minimum number of tools needed. Don't read files speculatively.
4. Prefer `gh` commands over reading files when checking live CI state.

OUTPUT RULES:
- Be concise and actionable. Lead with the root cause and fix, not background.
- Always answer in the user's language (中文 if they write in Chinese).
- When you hit the tool limit, summarize what you found so far and state what you still need.

IMPORTANT RULES:
- If the user asks about anything NOT related to CI/CD, politely decline and redirect.
  Example: "我是 CI Agent，只能帮助 CI/CD 相关的问题。"
"""


# ── Request / Response schemas ───────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    repo: str | None = None  # "owner/repo" or local path for context
    branch: str | None = None
    model: str | None = None  # override per-request
    repo_root: str | None = None  # absolute path to repo on server filesystem


# ── SSE helpers ──────────────────────────────────────────────────────────────


def _sse_event(event: str, data: dict) -> str:
    """Format a single SSE event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _serialize_content(content) -> list[dict]:
    """Serialize Anthropic content blocks to JSON-safe dicts for round-tripping."""
    result = []
    for block in content:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return result


# ── Multi-turn agentic loop ─────────────────────────────────────────────────


async def _run_agentic_loop(
    *,
    client,
    model: str,
    system: str,
    messages: list[dict],
    repo_root: Path | None,
    max_turns: int = 10,
):
    """多轮 tool-use 循环。Yield SSE 事件字符串。"""
    tools = ANTHROPIC_TOOLS if repo_root else []
    total_input = 0
    total_output = 0
    turn = 0

    for turn in range(max_turns):
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            **({"tools": tools} if tools else {}),
        )

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        # 处理 content blocks
        tool_use_blocks = []
        for block in response.content:
            if block.type == "text" and block.text.strip():
                yield _sse_event("text", {"content": block.text})
            elif block.type == "tool_use":
                tool_use_blocks.append(block)
                yield _sse_event(
                    "tool_use",
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    },
                )

        # 无 tool use，结束循环
        if response.stop_reason != "tool_use" or not tool_use_blocks:
            break

        # 分离只读工具和写入工具
        read_blocks = [b for b in tool_use_blocks if b.name not in WRITE_TOOL_NAMES]
        write_blocks = [b for b in tool_use_blocks if b.name in WRITE_TOOL_NAMES]

        # 如果有写入工具，生成预览并暂停循环等待用户确认
        if write_blocks:
            proposals = []
            for wb in write_blocks:
                preview = preview_write(wb.name, wb.input, repo_root=repo_root)
                preview["tool_id"] = wb.id
                preview["tool_name"] = wb.name
                preview["tool_input"] = wb.input
                proposals.append(preview)

            yield _sse_event(
                "write_proposal",
                {
                    "proposals": proposals,
                    "pending_tool_ids": [wb.id for wb in write_blocks],
                    "assistant_content": _serialize_content(response.content),
                },
            )

            # 暂停循环——TUI 需要发 /api/chat/apply 来继续
            # 累计 usage 并返回 done（带 pending 标记）
            yield _sse_event(
                "done",
                {
                    "usage": {"input_tokens": total_input, "output_tokens": total_output},
                    "model": response.model,
                    "turns": turn + 1,
                    "pending_writes": True,
                },
            )
            return  # 结束生成器，等待 apply 请求

        # 只读工具——直接执行
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tool_block in read_blocks:
            result = await execute_tool(
                tool_block.name,
                tool_block.input,
                repo_root=repo_root,
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result,
                }
            )
            yield _sse_event(
                "tool_result",
                {
                    "id": tool_block.id,
                    "name": tool_block.name,
                    "result_preview": result[:200] + "..." if len(result) > 200 else result,
                },
            )

        messages.append({"role": "user", "content": tool_results})

    # 如果 loop 因轮数耗尽而退出（stop_reason 仍是 tool_use），强制做一次文字总结
    if response.stop_reason == "tool_use":
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": "你已用完工具调用次数。请根据目前收集到的信息，直接给出结论和建议（不要再调用工具）。",
            }
        )
        summary_resp = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=messages,
        )
        total_input += summary_resp.usage.input_tokens
        total_output += summary_resp.usage.output_tokens
        for block in summary_resp.content:
            if block.type == "text" and block.text.strip():
                yield _sse_event("text", {"content": block.text})

    # 完成事件
    yield _sse_event(
        "done",
        {
            "usage": {"input_tokens": total_input, "output_tokens": total_output},
            "model": response.model,
            "turns": turn + 1,
        },
    )


# ── Endpoint ─────────────────────────────────────────────────────────────────


@chat_router.post("/chat")
async def chat(request: ChatRequest):
    """Streaming chat endpoint. Returns SSE (Server-Sent Events).

    Events:
      - event: text         data: {"content": "..."}
      - event: tool_use     data: {"id": "...", "name": "...", "input": {...}}
      - event: tool_result  data: {"id": "...", "name": "...", "result_preview": "..."}
      - event: done         data: {"usage": {...}, "model": "...", "turns": N}
      - event: error        data: {"message": "..."}
    """

    async def _generate():
        config = AgentConfig.load()
        model = request.model or config.model
        api_key = config.anthropic_api_key
        base_url = config.anthropic_base_url

        # 解析 repo_root
        repo_root = None
        if request.repo_root:
            candidate = Path(request.repo_root)
            if candidate.exists() and candidate.is_dir():
                repo_root = candidate

        # 构建 system prompt
        system = CI_SCOPE_SYSTEM_PROMPT
        if request.repo:
            system += f"\nCurrently working on repository: {request.repo}"
        if request.branch:
            system += f"\nBranch: {request.branch}"

        # 构建 messages
        messages = [{"role": m.role, "content": m.content} for m in request.messages]

        try:
            if config.provider == "openai":
                async for chunk in _query_openai(messages, system, model, config, repo_root):
                    yield chunk
            else:
                async for chunk in _query_anthropic(messages, system, model, api_key, base_url, repo_root):
                    yield chunk
        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Apply endpoint (执行用户确认的写入操作) ──────────────────────────────────


class ApplyRequest(BaseModel):
    proposals: list[dict]  # 来自 write_proposal 事件的 proposals
    repo_root: str


@chat_router.post("/chat/apply")
async def apply_writes(request: ApplyRequest):
    """执行用户确认的写入操作。返回每个操作的结果。"""
    repo_root = Path(request.repo_root)
    if not repo_root.exists() or not repo_root.is_dir():
        return {"error": "repo_root not found"}

    results = []
    for proposal in request.proposals:
        tool_name = proposal.get("tool_name", proposal.get("action", ""))
        tool_input = proposal.get("tool_input", {})
        if not tool_name or not tool_input:
            # git_commit 的 proposal 格式不同
            if proposal.get("action") == "git_commit":
                tool_name = "git_commit"
                tool_input = {"message": proposal.get("message", ""), "files": proposal.get("files", [])}

        result = await execute_tool(tool_name, tool_input, repo_root=repo_root)
        results.append({"tool_name": tool_name, "result": result})

    return {"results": results}


async def _query_anthropic(
    messages: list[dict],
    system: str,
    model: str,
    api_key: str | None,
    base_url: str | None,
    repo_root: Path | None = None,
):
    """通过 Anthropic SDK 查询，支持 tool use 和代理。"""
    import anthropic

    # 去掉 /v1/messages 或 /v1 — SDK 自动拼接
    if base_url:
        base_url = base_url.rstrip("/")
        for suffix in ("/v1/messages", "/v1"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
                break

    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)

    config = AgentConfig.load()
    async for event in _run_agentic_loop(
        client=client,
        model=model,
        system=system,
        messages=messages,
        repo_root=repo_root,
        max_turns=config.max_turns,
    ):
        yield event


async def _query_openai(
    messages: list[dict],
    system: str,
    model: str,
    config: AgentConfig,
    repo_root: "Path | None" = None,
):
    """通过 OpenAI SDK 查询，支持多轮 tool use（OpenAI function calling 格式）。"""
    import json

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.openai_api_key, base_url=config.base_url)

    oai_messages: list[dict] = [{"role": "system", "content": system}, *messages]
    tools = TOOL_DEFINITIONS if repo_root else []
    total_tokens = 0
    turn = 0

    for turn in range(config.max_turns):
        kwargs: dict = {"model": model, "messages": oai_messages, "max_tokens": 4096}
        if tools:
            kwargs["tools"] = tools

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message
        if response.usage:
            total_tokens += response.usage.total_tokens

        # Text response
        if msg.content:
            yield _sse_event("text", {"content": msg.content})

        # No tool calls → done
        if choice.finish_reason != "tool_calls" or not msg.tool_calls:
            break

        # Append assistant turn (with tool_calls)
        oai_messages.append(msg.model_dump(exclude_unset=True))

        # Execute each tool call
        for tc in msg.tool_calls:
            name = tc.function.name
            inputs = json.loads(tc.function.arguments)
            yield _sse_event("tool_use", {"id": tc.id, "name": name, "input": inputs})
            result = await execute_tool(name, inputs, repo_root=repo_root)
            preview = result[:200] + "..." if len(result) > 200 else result
            yield _sse_event("tool_result", {"id": tc.id, "name": name, "result_preview": preview})
            oai_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    yield _sse_event("done", {"usage": {"total_tokens": total_tokens}, "model": model, "turns": turn + 1})
