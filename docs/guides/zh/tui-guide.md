# TUI 交互模式使用指南

ci-agent 提供了一个基于终端的交互式 TUI（Terminal User Interface），让你可以像聊天一样与 AI 对话，实时分析 CI 流水线、诊断故障、并直接修复问题。

---

## 目录

- [快速开始](#快速开始)
- [启动 TUI](#启动-tui)
- [首次配置引导](#首次配置引导)
- [仓库确认](#仓库确认)
- [对话交互](#对话交互)
- [斜杠命令](#斜杠命令)
- [写入确认面板](#写入确认面板)
- [快捷键](#快捷键)
- [多行输入](#多行输入)
- [架构说明](#架构说明)
- [常见问题](#常见问题)

---

## 快速开始

```bash
# 1. 先启动后端 Server（TUI 依赖 Server 的 /api/chat 接口）
ci-agent serve

# 2. 在新终端中启动 TUI
ci-agent chat
```

TUI 会自动检测当前目录的 Git 仓库，确认后进入对话模式。

---

## 启动 TUI

### 基本用法

```bash
# 在 Git 仓库目录下直接启动
cd /path/to/your/repo
ci-agent chat

# 指定仓库路径
ci-agent chat --repo /path/to/another/repo

# 指定模型
ci-agent chat --model claude-opus-4-20250514
```

### 自动连接 Server

TUI 启动时会自动检测后端 Server 是否运行：

- 如果 Server 已运行，直接连接
- 如果 Server 未运行，TUI 会自动在后台启动一个 Server 进程，并显示启动进度

```
  ⠸ 正在启动 Server (port 8000) … 2s
  ✓ Server 已启动
```

Server 地址默认为 `http://localhost:8000`，可通过环境变量 `CI_AGENT_API_URL` 覆盖：

```bash
export CI_AGENT_API_URL=http://my-server:9000
ci-agent chat
```

---

## 首次配置引导

首次运行 `ci-agent chat` 时（`~/.ci-agent/config.json` 不存在），会自动进入配置引导流程：

```
╭──────── ci-agent Setup ────────╮
│  首次使用，需要进行初始配置     │
╰────────────────────────────────╯

1. AI 引擎
   [1] Anthropic (Claude)
   [2] OpenAI (兼容)
   请选择 [1]: 1

2. API Key
   请输入 Anthropic API Key: ****

3. GitHub Token (用于拉取 CI 数据，回车跳过)
   请输入 GitHub Token: ****

4. 模型 (默认: claude-sonnet-4-20250514)
   请输入模型名称 (回车使用默认):

5. 输出语言
   [1] English
   [2] 中文
   请选择 [1]: 2

✓ 配置已保存到 ~/.ci-agent/config.json

⠸ 正在验证 API 连通性...
✓ API 连通正常 (claude-sonnet-4-20250514, 响应 1.2s)
```

### 再次启动时的配置确认

如果配置文件已存在，启动时会展示当前配置并逐项询问是否修改：

```
╭──────── 当前配置 ────────╮
│  Provider:  anthropic     │
│  API Key:   sk-ant-***4f  │
│  GitHub:    ghp_***a3     │
│  Model:     claude-sonnet │
│  Language:  zh            │
╰──────────────────────────╯

Provider [anthropic] — 修改？(y/N):
API Key [sk-ant-***4f] — 修改？(y/N):
GitHub Token [ghp_***a3] — 修改？(y/N):
Model [claude-sonnet-4-20250514] — 修改？(y/N):
Language [中文] — 修改？(y/N):
```

直接回车跳过不修改。输入 `y` 后按提示输入新值。

### API 连通性验证

每次启动都会验证 API Key 和模型是否可用：
- 成功：显示模型名称和响应耗时
- 失败：显示错误原因（认证失败 / 网络问题 / 超时），但仍可进入 TUI

---

## 仓库确认

启动后，TUI 会检测当前目录（或 `--repo` 指定的路径）的 Git 仓库信息，并要求确认：

```
╭──────────── ci-agent ────────────╮
│ 检测到 Git 仓库：myorg/my-repo  │
│   分支：main                      │
│   最近提交：feat: add caching     │
╰──────────────────────────────────╯
使用此仓库？[Y/n] Y
```

- 输入 `Y` 或直接回车 — 确认使用该仓库
- 输入 `n` — 手动输入其他仓库路径或 `owner/repo` 格式的 GitHub 仓库

确认后显示连接信息并进入 REPL 交互：

```
✓ 已连接 myorg/my-repo
  Model: claude-sonnet-4-20250514 · Server: http://localhost:8000
  输入 /help 查看命令，Ctrl+C 清空输入，Ctrl+D 退出

›
```

---

## 对话交互

在 `›` 提示符后直接输入自然语言问题，AI 会实时分析并流式输出结果。

### 示例对话

```
› 最近 CI 失败的主要原因是什么

  ⠸ 列出 workflow 文件
  ✓ list_workflows
  ⠸ 读取 .github/workflows/ci.yml
  ✓ read_file → name: CI...
  ⠸ 搜索内容 timeout|fail|error
  ✓ grep_content → 12 matches

AI ›
根据分析，最近 CI 失败的主要原因有：

1. **Flaky Test (43%)** — `test_auth_timeout` 在高负载时随机超时
2. **依赖缓存失效 (31%)** — pip cache key 未包含 Python 版本
3. **Action SHA 未固定 (26%)** — 3 个 action 使用浮动 tag

claude-sonnet-4-20250514 · 1234↑ 567↓ · $0.0223
```

### 输出说明

| 元素 | 含义 |
|------|------|
| `⠸ 读取 ...` | 工具调用进行中（spinner） |
| `✓ tool_name → preview` | 工具调用完成，显示简短预览 |
| `AI ›` | AI 回复内容，以 Markdown 格式渲染 |
| `1234↑ 567↓` | 输入/输出 token 数 |
| `$0.0223` | 本次查询预估花费（USD） |
| `2 轮` | 如果 agent 进行了多轮推理，显示轮次 |

### 你可以问的问题

- "这个仓库有哪些 workflow 文件？"
- "分析 CI 配置有哪些安全问题"
- "最近一次 CI 失败的原因是什么"
- "帮我优化 ci.yml 的缓存配置"
- "把所有 action 固定到具体的 commit SHA"
- "这个 workflow 的执行时间能缩短吗"

---

## 斜杠命令

在 `›` 提示符输入以 `/` 开头的命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/repo [path]` | 切换工作仓库 |
| `/skills` | 列出当前加载的分析技能 |
| `/clear` | 清空对话历史 |
| `/compact` | 压缩对话历史，保留最近 6 条消息（释放上下文窗口） |
| `/cost` | 显示本次会话的累计查询次数和花费 |
| `/model [name]` | 查看或切换模型 |
| `/quit` | 退出 TUI |

### 命令示例

```
› /cost
Session Stats
  查询次数: 3
  总花费:   $0.0685

› /model claude-opus-4-20250514
模型已切换为: claude-opus-4-20250514

› /compact
已压缩：保留最近 6 条消息，丢弃 14 条

› /skills
┌─────────┬───────────────────┬─────────┐
│ 维度    │ 名称              │ 来源    │
├─────────┼───────────────────┼─────────┤
│ security│ security-analyst  │ builtin │
│ cost    │ cost-analyst      │ builtin │
│ ...     │ ...               │ ...     │
└─────────┴───────────────────┴─────────┘
```

斜杠命令支持 Tab 补全，输入 `/` 后按 Tab 键即可看到可用命令列表。

---

## 写入确认面板

当 AI 提出修改文件、创建 commit 或 PR 等写操作时，TUI 会显示一个红色边框的确认面板，**必须经过你的明确同意才会执行**。

```
╭──────── ⚠  即将执行以下操作 ────────╮
│                                       │
│ 📝 修改文件                            │
│    .github/workflows/ci.yml  (+3 行, -3 行)  │
│ 📦 Git commit                          │
│    fix: pin action SHAs                 │
│                                       │
╰───────────────────────────────────────╯
[y] 确认执行   [n] 取消   [d] 查看 diff   [e] 只修改不提 PR
请输入 y/n/d/e >
```

### 确认选项

| 按键 | 作用 |
|------|------|
| `y` | 确认执行所有操作（修改文件 + commit + PR） |
| `n` | 取消，不执行任何操作 |
| `d` | 显示 unified diff，查看具体改动内容，然后重新选择 |
| `e` | 仅修改本地文件，不执行 commit 和 PR |

查看 diff 后面板会重新出现，供你再次选择。

---

## 快捷键

| 快捷键 | 作用 |
|--------|------|
| `Enter` | 提交当前输入 |
| `Alt+Enter` (或 `Esc` 然后 `Enter`) | 插入换行（多行输入） |
| `Ctrl+C` | 清空当前输入缓冲区；查询进行中时中断请求 |
| `Ctrl+D` | 退出 TUI |
| `↑` / `↓` | 浏览历史输入 |
| `Tab` | 斜杠命令自动补全 |

也可以直接输入 `exit`、`quit` 或 `q` 退出。

---

## 多行输入

默认情况下，按 `Enter` 直接提交输入。如果需要输入多行内容：

1. 按 `Alt+Enter`（macOS 上是 `Option+Enter`，部分终端可能需要按 `Esc` 然后 `Enter`）插入换行
2. 继续输入下一行
3. 输入完成后按 `Enter` 提交

```
› 帮我修改 ci.yml，做以下改动：
  1. 固定所有 action 到 SHA
  2. 添加 pip 缓存
  3. 并行运行 lint 和 test
```

---

## 架构说明

TUI 模式基于 Client-Server 架构，TUI 作为客户端通过 SSE（Server-Sent Events）连接后端 API：

```
┌──────────────────────────────┐
│  TUI Client (prompt_toolkit) │
│  ┌────────┐  ┌────────────┐  │
│  │  REPL  │  │  Renderer  │  │
│  │(input) │  │(Rich输出)  │  │
│  └───┬────┘  └─────▲──────┘  │
│      │             │          │
│      └──── SSE ────┘          │
│           stream              │
└──────────┬───────────────────┘
           │ HTTP POST /api/chat (SSE)
┌──────────▼───────────────────┐
│    FastAPI Server             │
│  ┌─────────────────────────┐ │
│  │ Orchestrator + Skills   │ │
│  │ (AI Agent + Tools)      │ │
│  └─────────────────────────┘ │
└──────────────────────────────┘
```

### SSE 事件类型

TUI 接收的 SSE 事件流包含以下类型：

| 事件类型 | 说明 |
|---------|------|
| `text` | AI 生成的文本片段（流式） |
| `tool_use` | 工具调用开始（显示 spinner） |
| `tool_result` | 工具调用完成（显示结果预览） |
| `write_proposal` | 写操作提案（触发确认面板） |
| `done` | 请求完成（显示 token 统计和花费） |
| `error` | 服务端错误 |

---

## 常见问题

### TUI 启动报错 "Server 启动超时"

TUI 会自动启动 Server，但如果 10 秒内 Server 未就绪，会报错。解决方法：

```bash
# 手动启动 Server
ci-agent serve

# 然后在另一个终端启动 TUI
ci-agent chat
```

### 连接远程 Server

如果 Server 运行在其他机器或端口上：

```bash
export CI_AGENT_API_URL=http://192.168.1.100:8000
ci-agent chat
```

### 没有 API Key

TUI 本身不直接调用 AI 模型，而是通过 Server 代理。确保 Server 端已配置好 API Key：

```bash
# 通过环境变量
export ANTHROPIC_API_KEY=sk-ant-...
ci-agent serve

# 或通过配置文件
ci-agent config set anthropic_api_key sk-ant-...
```

### 中断正在进行的查询

如果 AI 正在处理一个耗时较长的请求，按 `Ctrl+C` 可以中断当前查询并返回到输入提示符。TUI 会显示 `已中断` 提示。

### 对话过长导致 token 超限

使用 `/compact` 命令压缩对话历史，只保留最近 6 条消息。或使用 `/clear` 完全清空重新开始。

### 输入历史

TUI 会自动保存输入历史到 `~/.ci-agent/history`，使用 `↑` / `↓` 方向键可以浏览历史输入，跨会话保留。
