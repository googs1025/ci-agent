# ci-agent TUI Design Spec

**Date:** 2026-04-22
**Status:** Approved
**Scope:** Interactive TUI interface for ci-agent, modeled after Claude Code CLI

---

## 1. Goals

Transform ci-agent from a one-shot CLI tool into an interactive terminal agent that can:

- Analyze CI pipelines conversationally
- Diagnose failures in real time
- Execute fixes end-to-end (modify workflow files, commit, create PRs)
- Feel like Claude Code — streaming output, inline tool status, confirmation panels

---

## 2. User-Facing Behavior

### Startup

```
$ ci-agent                        # no args → TUI mode
$ ci-agent chat                   # explicit TUI entry
$ ci-agent analyze <repo> ...     # existing one-shot mode, unchanged
$ ci-agent serve                  # existing API mode, unchanged
```

On startup, ci-agent detects the Git repository in the current working directory (or the path passed via `--repo`) and asks the user to confirm before entering the REPL:

```
╭─ ci-agent ──────────────────────────────────╮
│  🤖  CI Agent  v0.2.0                        │
╰──────────────────────────────────────────────╯

? 检测到 Git 仓库：myorg/my-service
  分支：main · 最近提交：feat: add caching
  使用此仓库？[Y]es / [n]o（手动输入路径）
> Y

✓ 已连接 myorg/my-service
  Model: claude-sonnet-4-6 · Skills: security, cost, efficiency, errors
  输入 /help 查看命令，Ctrl+C 退出

› _
```

If the user answers `n`, they are prompted to enter a local path or `owner/repo` GitHub reference manually.

### REPL Interaction

The user types natural language. Tool calls appear as inline spinner lines while running. Results stream in real time via Rich markdown rendering.

```
› 最近 CI 失败的原因是什么

  ⠸ 拉取最近 50 条 CI runs...
  ⠸ 读取 .github/workflows/ci.yml
  ⠴ security-analyst 分析中...
  ⠴ errors-analyst 分析中...

根据最近 14 天的 CI 数据，主要失败原因有：

● flaky test (43%) — test_auth_timeout 在高负载时随机超时
● 依赖缓存失效 (31%) — pip cache key 未包含 Python 版本
● action SHA 未固定 (26%) — 3 个 action 使用浮动 tag

用时 18.3s · 花费 $0.031 · 发现 3 个问题

› _
```

### Write Confirmation Panel

Any operation that modifies files, creates commits, or opens PRs requires explicit user confirmation. A red-bordered Rich panel is shown before any write is executed:

```
⚠  即将执行以下操作

📝 修改文件
   .github/workflows/ci.yml  (+3 行, -3 行)
📦 Git commit
   fix: pin action SHAs to prevent supply chain attack
🔀 Pull Request → main
   fix/pin-action-shas

[y] 确认执行   [n] 取消   [d] 查看 diff   [e] 只修改文件，不提 PR
```

- `y` — execute all actions
- `n` — cancel, return to REPL
- `d` — show unified diff inline (Rich Syntax), then re-prompt
- `e` — apply local file changes only, skip commit and PR

### Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/repo [path]` | Switch working repository |
| `/skills` | List / enable / disable skills |
| `/clear` | Clear conversation history |
| `/cost` | Show session token usage and cost |
| `/model [name]` | Switch model mid-session |

---

## 3. Architecture

### New Module: `src/ci_optimizer/tui/`

The TUI is fully self-contained in a new module. Existing code (`agents/`, `api/`, `cli.py`) is not modified except for adding the `chat` subcommand entry point in `cli.py`.

```
src/ci_optimizer/
├── cli.py              # add: "chat" subcommand → tui.app.run_tui()
└── tui/
    ├── __init__.py
    ├── app.py          # entry point: startup banner, repo confirm, REPL loop
    ├── context.py      # repo detection (git) + user confirmation prompt
    ├── repl.py         # prompt_toolkit PromptSession, FileHistory, key bindings
    ├── renderer.py     # Rich Console/Live, streaming AssistantMessage output
    ├── panels.py       # write confirmation panel, diff view
    └── commands.py     # slash command parser and handlers
```

### Data Flow

```
User input
  │
  ├─ /command  → commands.py → Rich output
  │
  └─ natural language → orchestrator.run_analysis() [TUI mode]
                            │
                            ├─ AssistantMessage → renderer.py → Rich Live (streaming)
                            ├─ ToolUseBlock    → renderer.py → spinner status line
                            └─ WriteAction     → panels.py  → confirmation panel
```

### Agent Tool Permissions

| Mode | Allowed Tools |
|------|--------------|
| `ci-agent analyze` (one-shot) | Read, Glob, Grep, Agent |
| `ci-agent chat` (TUI) | Read, Glob, Grep, Agent, Write, Bash |

Write and Bash are only available in TUI mode, where the confirmation hook intercepts destructive actions before execution.

---

## 4. Technical Implementation

### Dependencies (additions)

```toml
"prompt_toolkit>=3.0",   # REPL input, history, key bindings
"rich>=13.0",            # streaming markdown, panels, diff syntax
```

Rich is likely already an indirect dependency. prompt_toolkit is a new direct dependency.

### Key Components

**`context.py`**
- `detect_repo(path: Path) -> RepoContext` — runs `git rev-parse --show-toplevel`, extracts `owner/repo` from remote URL, reads current branch
- `confirm_repo(ctx: RepoContext) -> RepoContext` — prompt_toolkit Q&A flow, supports manual path input fallback

**`renderer.py`**
- `StreamRenderer` — wraps `rich.console.Console` and `rich.live.Live`
- Consumes `async for message in query()`: renders `TextBlock` as `Markdown`, renders `ToolUseBlock` as a spinner line, renders `ResultMessage` as cost/duration summary

**`panels.py`**
- `confirm_action(action: WriteAction) -> ConfirmResult` — renders red-bordered `rich.panel.Panel`, reads single keypress via prompt_toolkit, handles `d` (show diff) recursively

**`repl.py`**
- `build_session() -> PromptSession` — configures `FileHistory(~/.ci-agent/history)`, `KeyBindings` (Ctrl+C cancel, Ctrl+D exit), `WordCompleter` for slash commands

**`app.py`**
- `run_tui(repo_path: Path | None = None)` — async main loop: startup banner → repo confirm → `while True: prompt → dispatch`

### History Persistence

```
~/.ci-agent/history     # prompt_toolkit FileHistory (input history across sessions)
```

---

## 5. MVP Scope

### Phase 1 — REPL Skeleton (~2 days)
`context.py` + `repl.py` + `app.py` + CLI entry point.
Goal: `ci-agent` starts, confirms repo, accepts input, echoes back.

### Phase 2 — Streaming Renderer (~1 day)
`renderer.py` wired to `claude_agent_sdk.query()`.
Goal: real-time agent output and tool status lines visible in terminal.

### Phase 3 — Write Confirmation + Slash Commands (~1 day)
`panels.py` + `commands.py`.
Goal: complete MVP, usable daily.

### Out of Scope (future iterations)
- Fixed sidebar / panel layout (would require Textual)
- Mouse support
- Multi-session / session restore
- Web UI integration
- Auto-complete for repo paths and skill names
- Inline diff editing

---

## 6. Testing

### Unit Tests (no LLM required)
- `test_context.py` — repo detection logic, path parsing, remote URL parsing
- `test_commands.py` — slash command parsing and dispatch
- `test_panels.py` — confirmation panel input parsing (`y`/`n`/`d`/`e`)

### Integration Tests
- `test_renderer.py` — mock `query()` yielding `AssistantMessage` and `ToolUseBlock` objects, assert Rich output format

### Manual Acceptance Criteria
1. `ci-agent` → confirm repo → type question → see streaming output
2. Ask agent to modify a file → confirmation panel appears → `d` shows diff → `y` executes
3. `/skills`, `/cost`, `/clear` commands work correctly
4. `Ctrl+C` exits gracefully with no stack trace
