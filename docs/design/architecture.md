# ci-agent 架构设计文档

## 概述

ci-agent 是一个 AI 驱动的 GitHub CI 流水线分析和优化系统。支持交互式 TUI 对话、一次性 CLI 分析、以及 Web UI 三种交互方式。

**核心能力**:
- 四维度分析：执行效率、安全最佳实践、成本优化、错误分析
- 双 AI 引擎：Anthropic (Claude) / OpenAI (兼容 API)
- 三种交互方式：TUI 对话 (`ci-agent chat`) / CLI 命令行 / Web UI (Next.js Dashboard)
- TUI 对话：自然语言提问，AI 工具调用读写文件，写入操作需用户确认（diff 预览）
- 多语言报告：中文 / 英文
- CI 使用率统计：Job 耗时、排队时间、Runner 分布、计费估算

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                           Clients                                  │
│                                                                    │
│  ┌──────────────┐   ┌──────────────────────────┐   ┌──────────┐  │
│  │  TUI Chat    │   │   Next.js Web UI (:3000)  │   │   CLI    │  │
│  │ ci-agent chat│   │  Dashboard/Analyze/Reports│   │ analyze  │  │
│  └──────┬───────┘   └────────────┬─────────────┘   └────┬─────┘  │
└─────────┼───────────────────────┼─────────────────────────┼───────┘
          │ SSE stream            │ REST                    │ direct
          ▼                       ▼                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (:8000)                         │
│                                                                    │
│  ┌──────────────────────────┐   ┌─────────────────────────────┐  │
│  │  Chat API (api/chat.py)  │   │  Analysis API (api/routes.py)│  │
│  │  POST /api/chat (SSE)    │   │  POST /api/analyze           │  │
│  │  POST /api/chat/apply    │   │  GET  /api/reports           │  │
│  │         │                │   │  GET  /api/config            │  │
│  │  ┌──────▼─────────────┐  │   └──────────────┬──────────────┘  │
│  │  │  Agentic Loop      │  │                  │                  │
│  │  │  (multi-turn       │  │   ┌──────────────▼──────────────┐  │
│  │  │   tool_use)        │  │   │    Analysis Orchestrator     │  │
│  │  │                    │  │   │  Resolver → Prefetch →       │  │
│  │  │  read_file         │  │   │  anthropic_engine /          │  │
│  │  │  write_file*       │  │   │  openai_engine               │  │
│  │  │  edit_file*        │  │   │  (4 specialist agents)       │  │
│  │  │  glob_files        │  │   └─────────────────────────────┘  │
│  │  │  grep_content      │  │                                     │
│  │  │  list_workflows    │  │                                     │
│  │  │  run_command       │  │                                     │
│  │  │  git_commit*       │  │                                     │
│  │  └────────────────────┘  │                                     │
│  │  * write_proposal 确认流  │                                     │
│  └──────────────────────────┘                                     │
└──────────────────────────────────────────────────────────────────┘
                          │
           ┌──────────────┼──────────────┐
           ▼              ▼              ▼
      SQLite DB       GitHub API    Anthropic /
  (repositories,    (Run History)   OpenAI API
  analysis_reports,
    findings)
```

---

## 模块说明

### 入口层

| 模块 | 文件 | 说明 |
|------|------|------|
| CLI | `cli.py` | argparse 命令行：`chat` / `analyze` / `serve` / `config` / `skills` |
| FastAPI App | `api/app.py` | Web 服务入口，CORS，lifespan |
| API Routes | `api/routes.py` | REST 端点，background task 调度 |
| Chat API | `api/chat.py` | SSE streaming chat，multi-turn agentic loop，write proposal 流 |
| Tools | `api/tools.py` | AI 可调用工具：read/write/edit/glob/grep/git/CI |
| API Schemas | `api/schemas.py` | Pydantic request/response 模型 |

### TUI 层

| 模块 | 文件 | 说明 |
|------|------|------|
| TUI App | `tui/app.py` | 启动横幅、仓库确认、REPL 主循环、Server 自动启动 |
| REPL | `tui/repl.py` | prompt_toolkit PromptSession 配置（历史、补全） |
| Commands | `tui/commands.py` | 斜杠命令：`/help` `/clear` `/model` `/repo` `/quit` |
| Context | `tui/context.py` | 仓库检测（git remote / local path）与确认 |
| Panels | `tui/panels.py` | 写入确认面板：diff 展示 + y/n/d/e 交互 |
| Renderer | `tui/renderer.py` | SSE 流式输出渲染、Token 统计 |

### 核心引擎

| 模块 | 文件 | 说明 |
|------|------|------|
| Config | `config.py` | 用户配置：provider / model / API key / language |
| Resolver | `resolver.py` | 输入解析：GitHub URL / `owner/repo` 简写 / 本地路径 |
| Filters | `filters.py` | 分析过滤条件：时间 / workflow / 状态 / 分支 |
| GitHub Client | `github_client.py` | httpx 异步 GitHub REST API 客户端 |
| Prefetch | `prefetch.py` | 数据预取 + 使用率统计计算 |

### AI Agent 层

| 模块 | 文件 | 说明 |
|------|------|------|
| Orchestrator | `agents/orchestrator.py` | 路由层：根据 `config.provider` 选择引擎 |
| Skill Registry | `agents/skill_registry.py` | Skill 发现、解析、合并、校验 |
| Anthropic Engine | `agents/anthropic_engine.py` | Claude Agent SDK：编排器 + 子 Agent 模式 |
| OpenAI Engine | `agents/openai_engine.py` | OpenAI SDK：N specialist 并行 streaming + 合成 |
| Shared Prompts | `agents/prompts.py` | 多语言指令、输出格式定义 |

### Skill 定义（声明式）

| Skill | 文件 | 说明 |
|-------|------|------|
| Efficiency | `skills/efficiency/SKILL.md` | 并行化 / 缓存 / 条件执行 / Matrix 分析 |
| Security | `skills/security/SKILL.md` | 权限 / Action 版本 / Secrets / 供应链安全 |
| Cost | `skills/cost/SKILL.md` | Runner 选择 / 触发优化 / 计费分析 |
| Errors | `skills/errors/SKILL.md` | 失败模式 / Flaky 检测 / 根因分析 |
| 用户自定义 | `~/.ci-agent/skills/*/SKILL.md` | 用户可扩展的分析维度 |

### 数据层

| 模块 | 文件 | 说明 |
|------|------|------|
| Database | `db/database.py` | SQLAlchemy async engine + session |
| Models | `db/models.py` | Repository / AnalysisReport / Finding |
| CRUD | `db/crud.py` | 数据库读写操作 |

### 报告层

| 模块 | 文件 | 说明 |
|------|------|------|
| Formatter | `report/formatter.py` | Markdown / JSON 报告生成，中英文 i18n |

### 前端 (Next.js 14)

| 页面 | 文件 | 说明 |
|------|------|------|
| Dashboard | `app/page.tsx` | 统计卡片 / 维度分布 / 最近报告 |
| Analyze | `app/analyze/page.tsx` | 输入仓库 / 过滤面板 / 轮询进度 |
| Reports | `app/reports/page.tsx` | 报告列表 / 分页 |
| Report Detail | `app/reports/[id]/page.tsx` | 四维度 Tab / Finding 表格 / Markdown 摘要 |

---

## Skill System

分析维度以声明式 `SKILL.md` 文件定义，支持内置 + 用户自定义，由 `SkillRegistry` 统一发现和加载。

```
skills/                          ← 内置（随代码发布）
├── efficiency/SKILL.md
├── security/SKILL.md
├── cost/SKILL.md
└── errors/SKILL.md

~/.ci-agent/skills/              ← 用户自定义（同名覆盖内置）
└── reliability/SKILL.md
```

### SKILL.md 格式

```markdown
---
name: security-analyst           # 唯一标识 + Agent 名称
description: ...                 # Orchestrator prompt 中使用
dimension: security              # 报告维度 key
tools: [Read, Glob, Grep]       # Anthropic Engine 的工具列表
requires_data: [workflows]       # 声明需要的预取数据
enabled: true                    # 是否启用
priority: 100                    # 同名覆盖优先级
---

(Specialist Agent 的完整 prompt)
```

### 加载流程

```
SkillRegistry.load()
  │
  ├── 扫描 skills/ (内置) → 解析 SKILL.md → Skill 对象
  ├── 扫描 ~/.ci-agent/skills/ (用户) → 同名覆盖内置
  ├── 校验（必需字段、requires_data 合法性）
  └── 按 --skills 参数过滤 + 按 priority 排序
        │
        ├──→ collect_required_data()     → prefetch 按需获取
        ├──→ build_orchestrator_prompt() → 动态生成编排器 prompt
        ├──→ to_agent_definitions()      → Anthropic Engine
        └──→ to_specialist_prompts()     → OpenAI Engine
```

### 双引擎消费方式

| SKILL.md 字段 | Anthropic Engine | OpenAI Engine |
|---------------|-----------------|---------------|
| `prompt` | `AgentDefinition.prompt` | chat completion `system` message |
| `tools` | `AgentDefinition.tools` | 忽略（无 tool use） |
| `requires_data` | 按需 prefetch | 按需组装 context（减少 token） |

详细设计见 [Skill System 设计文档](./skill-system-design.md)。

---

## 双引擎架构

```
config.provider
    │
    ├── "anthropic"
    │   └── anthropic_engine.py
    │       ├── Claude Agent SDK query()
    │       ├── Orchestrator Agent (动态生成 system_prompt)
    │       ├── N SubAgents via Agent tool (从 SkillRegistry 加载)
    │       │   每个 SubAgent 可调用 Skill 声明的 tools 读取文件
    │       └── 编排器综合生成 JSON 报告
    │
    └── "openai"
        └── openai_engine.py
            ├── AsyncOpenAI client (streaming)
            ├── N specialist 并行 asyncio.gather (从 SkillRegistry 加载)
            │   每个 specialist = 独立 chat completion (stream=True)
            │   context 按 Skill 的 requires_data 按需组装
            ├── Synthesis call: 合成 N 份报告为统一 JSON
            └── Fallback: 合成失败时直接拼接 specialist 结果
```

### Agentic Loop 机制

两个引擎的执行模式有本质区别：

**Anthropic Engine — 嵌套 Agentic Loop**

```
async for message in query(prompt, options)     ← anthropic_engine.py
│
│  这是 Claude Agent SDK 的核心，内部运行 multi-turn agentic loop:
│
│  Orchestrator Agent 启动 (max_turns=20)
│  │
│  │  Turn 1: LLM 决定 → 调用 Agent tool ("efficiency-analyst")
│  │          SDK 启动子 Agent subprocess
│  │          │
│  │          │  子 Agent 内部 loop:
│  │          │  ├─ LLM 决定 → 调用 Read tool → 读取 ci.yml 内容
│  │          │  ├─ LLM 决定 → 调用 Grep tool → 搜索 "cache" 关键字
│  │          │  ├─ LLM 决定 → 调用 Read tool → 读取 deploy.yml
│  │          │  └─ LLM 生成 findings JSON → 子 Agent loop 结束
│  │          │
│  │          子 Agent 结果返回给 Orchestrator
│  │
│  │  Turn 2: LLM 决定 → 调用 Agent tool ("security-analyst")
│  │          └─ 子 Agent loop ... (同上)
│  │
│  │  Turn 3: LLM 决定 → 调用 Agent tool ("cost-analyst")
│  │          └─ 子 Agent loop ...
│  │
│  │  Turn 4: LLM 决定 → 调用 Agent tool ("error-analyst")
│  │          └─ 子 Agent loop ...
│  │
│  │  Turn 5: LLM 收到全部结果 → 生成综合报告 JSON
│  │          → Orchestrator loop 结束
│  │
│  每一步由 LLM 自主决策：调用哪个工具、读哪个文件、何时停止
│  这是真正的 Agentic Loop — Agent 具有自主规划和工具调用能力
```

**关键代码**: `anthropic_engine.py` → `query(prompt, options=ClaudeAgentOptions(agents=AGENTS, allowed_tools=["Agent"]))`

**OpenAI Engine — Pipeline 模式 (非 Agentic Loop)**

```
asyncio.gather(                                  ← openai_engine.py
    _call_specialist("efficiency", prompt, ctx),     ← 1 次 chat completion
    _call_specialist("security", prompt, ctx),       ← 1 次 chat completion
    _call_specialist("cost", prompt, ctx),           ← 1 次 chat completion
    _call_specialist("error", prompt, ctx),          ← 1 次 chat completion
)
│
│  4 个独立的 one-shot streaming chat completion，并行执行
│  没有 tool use，没有 multi-turn，没有自主决策
│  所有文件内容在调用前预注入 context_text
│
▼
synthesis_call(specialist_results)               ← 第 5 次 chat completion
│
│  合成 4 份报告为统一 JSON
│  同样是 one-shot，不是 loop
│
▼
最终报告
```

**关键区别**:
- Anthropic Engine 中 Agent **自主决定**读哪些文件、搜索什么关键字、调用几次工具
- OpenAI Engine 中所有数据**预先注入** prompt，LLM 只做一次分析，不调用任何工具

### 对比

| 特性 | Anthropic Engine | OpenAI Engine |
|------|-----------------|---------------|
| 执行模式 | **Agentic Loop** (嵌套 multi-turn) | **Pipeline** (one-shot 并行) |
| 自主决策 | Agent 决定读哪些文件、搜索什么 | 无决策，所有数据预注入 |
| Tool Use | Read / Glob / Grep / Agent | 无 |
| SDK | Claude Agent SDK | OpenAI Python SDK |
| 调用方式 | 子进程 CLI (多轮对话) | HTTP API (streaming, 单次) |
| 并行性 | 编排器顺序调度 | 4 specialist 强制并行 |
| 文件访问 | Agent 按需读取文件 | 文件内容预注入 context |
| 兼容性 | 仅 Anthropic API | 任何 OpenAI 兼容端点 |
| LLM 调用次数 | ~20+ 次 (编排器 + 子 Agent 多轮) | 5 次 (4 specialist + 1 synthesis) |
| 典型耗时 | 3-5 分钟 | 1-2 分钟 |
| 分析深度 | 更深 (Agent 可针对性深挖) | 受限于 context 窗口大小 |

---

## 数据流

```
1. 用户输入
   "kubernetes-sigs/descheduler"  或  "https://github.com/..." 或  "/local/path"
        │
2. Resolver (resolver.py)
   ├── GitHub URL → git clone --depth=1 → local path
   ├── owner/repo → expand to URL → clone
   └── local path → detect git remote
        │
3. Prefetch (prefetch.py)
   ├── 收集 .github/workflows/*.yml 文件
   ├── GitHub API: list_workflow_runs (最近 30 个)
   ├── GitHub API: get_run_jobs (每个 run 的 job 详情，限 20 个)
   │   包含: started_at, completed_at, labels, steps[]
   ├── GitHub API: get_run_logs (失败 run 的日志，限 5 个)
   ├── 计算 usage_stats:
   │   ├── 成功率 (per workflow / per job)
   │   ├── 平均耗时 / 排队时间
   │   ├── Runner 分布 (ubuntu/macos/windows)
   │   ├── 计费估算 (分钟 × Runner 倍率)
   │   └── 最慢 Step Top 10
   └── 写入临时 JSON 文件: runs.json, jobs.json, usage.json, logs.json
        │
4. Skill Discovery (skill_registry.py)
   ├── 扫描内置 skills/ + 用户 ~/.ci-agent/skills/
   ├── 解析 SKILL.md → Skill 对象列表
   └── collect_required_data → 告知 prefetch 按需获取
        │
5. Agent Analysis (orchestrator.py → engine)
   ├── Anthropic: 编排器调度 N 个子 Agent (来自 SkillRegistry)
   └── OpenAI: N 个 streaming chat completion 并行 + 合成
        │
6. Parse Result
   ├── 提取 executive_summary (支持 string 或 list)
   ├── 提取 findings[] (severity, title, description, file, suggestion)
   └── 计算 stats (critical/major/minor/info 计数)
        │
7. Format & Store
   ├── format_markdown(result, ctx, language) → summary_md
   ├── format_json(result, ctx, language) → full_report_json
   └── DB: complete_report(findings_data, duration_ms)
```

---

## 配置系统

优先级：CLI 参数 > 环境变量 > `~/.ci-agent/config.json` > 默认值

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| `provider` | `CI_AGENT_PROVIDER` | `anthropic` | AI 引擎：`anthropic` 或 `openai` |
| `model` | `CI_AGENT_MODEL` | `claude-sonnet-4-20250514` | 模型名 |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | - | Anthropic API Key |
| `openai_api_key` | `OPENAI_API_KEY` | - | OpenAI API Key |
| `base_url` | `CI_AGENT_BASE_URL` | - | 自定义 API 端点 |
| `github_token` | `GITHUB_TOKEN` | - | GitHub Token |
| `language` | `CI_AGENT_LANGUAGE` | `en` | 报告语言：`en` / `zh` |
| `max_turns` | - | `20` | Agent 最大轮次 |

---

## 项目结构

```
ci-agent/
├── pyproject.toml
├── .env / .env.example
├── docs/
│   ├── design/
│   │   ├── architecture.md    ← 本文档
│   │   ├── skill-system.md    ← Skill System 详细设计
│   │   ├── webhook.md         ← Webhook 实时监控设计（草案）
│   │   └── failure-triage.md  ← 失败诊断设计
│   ├── guides/zh/ + en/       ← 中英文使用 / 部署 / Langfuse 指南
│   └── roadmap.md             ← 产品 Roadmap
├── skills/                    ← 内置 Skill 定义（声明式 SKILL.md）
│   ├── efficiency/SKILL.md
│   ├── security/SKILL.md
│   ├── cost/SKILL.md
│   └── errors/SKILL.md
├── deploy/
│   └── k8s/                   ← K8s manifests
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yaml
├── src/ci_optimizer/
│   ├── cli.py                 ← CLI 入口 (chat/analyze/serve/config/skills)
│   ├── config.py              ← 配置管理
│   ├── resolver.py            ← 输入解析 (URL/路径/简写)
│   ├── filters.py             ← 分析过滤条件
│   ├── github_client.py       ← GitHub REST API 客户端
│   ├── prefetch.py            ← 数据预取 + 使用率计算
│   ├── tui/                   ← TUI 交互模式
│   │   ├── app.py             ← 启动横幅、仓库确认、REPL 主循环
│   │   ├── repl.py            ← prompt_toolkit session 配置
│   │   ├── commands.py        ← 斜杠命令 (/help /clear /model /repo /quit)
│   │   ├── context.py         ← 仓库检测与确认
│   │   ├── panels.py          ← 写入确认面板（diff 预览）
│   │   └── renderer.py        ← SSE 流输出渲染 + Token 统计
│   ├── agents/
│   │   ├── orchestrator.py    ← 引擎路由
│   │   ├── skill_registry.py  ← Skill 发现、解析、合并、校验
│   │   ├── anthropic_engine.py ← Claude 引擎（Agentic Loop）
│   │   ├── openai_engine.py   ← OpenAI streaming 引擎（Pipeline）
│   │   └── prompts.py         ← 共享 prompt 模板 + i18n
│   ├── api/
│   │   ├── app.py             ← FastAPI 应用
│   │   ├── chat.py            ← SSE chat endpoint + agentic loop
│   │   ├── tools.py           ← AI 工具实现 (read/write/edit/grep/git)
│   │   ├── routes.py          ← 分析 API 路由
│   │   ├── auth.py            ← API Key 认证
│   │   └── schemas.py         ← Pydantic 模型
│   ├── db/
│   │   ├── database.py        ← DB engine
│   │   ├── models.py          ← ORM 模型
│   │   └── crud.py            ← CRUD 操作
│   └── report/
│       └── formatter.py       ← Markdown/JSON 报告 (中英文)
├── web/                       ← Next.js 14 前端
│   └── src/
│       ├── app/               ← 页面 (Dashboard/Analyze/Reports)
│       ├── components/        ← UI 组件
│       ├── lib/api.ts         ← API 客户端
│       └── types/index.ts     ← TypeScript 类型
└── tests/
    ├── test_chat_tools.py     ← Chat tools 单元测试
    ├── test_chat_write.py     ← Write proposal 流程测试
    ├── test_tools.py          ← Tools 实现测试
    ├── tui/
    │   ├── test_app_sse.py    ← TUI SSE 流解析测试
    │   ├── test_commands.py   ← 斜杠命令测试
    │   ├── test_context.py    ← 仓库检测测试
    │   └── test_panels.py     ← 写入确认面板测试
    └── ...                    ← 其他现有测试
```

---

## API 端点

### Chat（TUI 使用）

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | SSE streaming 对话，multi-turn tool use，返回 `text`/`tool_use`/`tool_result`/`write_proposal`/`done` 事件 |
| POST | `/api/chat/apply` | 执行用户确认的写入操作（write_proposal 流程的第二步） |

### Analysis（CLI / Web 使用）

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | 触发分析 (repo + filters + agent_config) |
| GET | `/api/reports` | 报告列表 (分页 + repo 过滤) |
| GET | `/api/reports/{id}` | 报告详情 (含 findings) |
| GET | `/api/dashboard` | Dashboard 聚合数据 |
| GET | `/api/repositories` | 已分析仓库列表 |
| GET | `/api/config` | 查看配置 (敏感值脱敏) |
| PUT | `/api/config` | 更新配置 |
| GET | `/api/skills` | 列出已加载的 Skill |
| POST | `/api/skills/reload` | 热重载 Skill 注册表 |
| GET | `/health` | 健康检查（TUI 自动检测 Server 状态） |

### Write Proposal 确认流程

```
TUI                    Server (/api/chat SSE)
 │                          │
 │─── POST /api/chat ──────▶│
 │                          │  AI 决定调用写入工具
 │                          │  → 生成 diff，不执行
 │◀── event: write_proposal─│  proposals: [{path, diff, added, removed}]
 │◀── event: done ──────────│  pending_writes: true
 │                          │
 │  [用户查看 diff，输入 y/n/e]
 │                          │
 │─── POST /api/chat/apply ▶│  执行写入操作
 │◀── {results: [...]} ─────│
```
