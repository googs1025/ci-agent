# ci-agent 架构设计文档

## 概述

ci-agent 是一个 AI 驱动的 GitHub CI 流水线分析和优化系统。用户输入仓库地址，系统自动分析 GitHub Actions workflow 文件和 CI 运行历史，输出四维度结构化分析报告。

**核心能力**:
- 四维度分析：执行效率、安全最佳实践、成本优化、错误分析
- 双 AI 引擎：Anthropic (Claude Agent SDK) / OpenAI (兼容 API)
- 双交互方式：CLI 命令行 + Web UI (Next.js Dashboard)
- 多语言报告：中文 / 英文
- CI 使用率统计：Job 耗时、排队时间、Runner 分布、计费估算

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Clients                                  │
│                                                                  │
│  ┌──────────┐         ┌──────────────────────────────────────┐  │
│  │   CLI    │         │       Next.js Web UI (:3000)          │  │
│  │ ci-agent │         │  Dashboard / Analyze / Reports        │  │
│  └────┬─────┘         └──────────────┬───────────────────────┘  │
│       │                              │                           │
│       ▼                              ▼                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              FastAPI Backend (:8000)                        │  │
│  │  POST /api/analyze    GET /api/reports   GET /api/config   │  │
│  │  GET  /api/dashboard  GET /api/repositories                │  │
│  └──────────────────────────┬────────────────────────────────┘  │
│                              │                                   │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │                Core Analysis Engine                         │  │
│  │                                                             │  │
│  │  ┌──────────┐   ┌──────────┐   ┌───────────────────────┐  │  │
│  │  │ Resolver │──▶│ Prefetch │──▶│  Agent Orchestrator   │  │  │
│  │  │(URL/Path │   │(GitHub   │   │                       │  │  │
│  │  │ /owner/  │   │ API +    │   │  ┌── config.provider  │  │  │
│  │  │  repo)   │   │ Usage    │   │  │                    │  │  │
│  │  └──────────┘   │ Stats)   │   │  ├─▶ anthropic_engine │  │  │
│  │                  └──────────┘   │  │   (Claude SDK)     │  │  │
│  │                                 │  │                    │  │  │
│  │                                 │  └─▶ openai_engine    │  │  │
│  │                                 │      (OpenAI stream)  │  │  │
│  │                                 └───────────────────────┘  │  │
│  │                                          │                  │  │
│  │                    ┌─────────┬────────┬──┴─────┐           │  │
│  │                    ▼         ▼        ▼        ▼           │  │
│  │                efficiency security   cost    error          │  │
│  │                analyst    analyst   analyst  analyst         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌───────────────────────────▼───────────────────────────────┐   │
│  │         SQLite (via SQLAlchemy async)                       │   │
│  │  repositories │ analysis_reports │ findings                 │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                               │
                    External Services
              ┌────────────────┼────────────┐
              ▼                ▼             ▼
         Anthropic API    GitHub API     Git Clone
         / OpenAI API    (Run History)  (Repo Files)
```

---

## 模块说明

### 入口层

| 模块 | 文件 | 说明 |
|------|------|------|
| CLI | `cli.py` | argparse 命令行：`analyze` / `serve` / `config` |
| FastAPI App | `api/app.py` | Web 服务入口，CORS，lifespan |
| API Routes | `api/routes.py` | REST 端点，background task 调度 |
| API Schemas | `api/schemas.py` | Pydantic request/response 模型 |

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
| Anthropic Engine | `agents/anthropic_engine.py` | Claude Agent SDK：编排器 + 子 Agent 模式 |
| OpenAI Engine | `agents/openai_engine.py` | OpenAI SDK：4 specialist 并行 streaming + 合成 |
| Shared Prompts | `agents/prompts.py` | 多语言指令、输出格式定义 |
| Efficiency Agent | `agents/efficiency.py` | 并行化 / 缓存 / 条件执行 / Matrix 分析 |
| Security Agent | `agents/security.py` | 权限 / Action 版本 / Secrets / 供应链安全 |
| Cost Agent | `agents/cost.py` | Runner 选择 / 触发优化 / 计费分析 |
| Error Agent | `agents/errors.py` | 失败模式 / Flaky 检测 / 根因分析 |

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

## 双引擎架构

```
config.provider
    │
    ├── "anthropic"
    │   └── anthropic_engine.py
    │       ├── Claude Agent SDK query()
    │       ├── Orchestrator Agent (system_prompt)
    │       ├── 4 SubAgents via Agent tool
    │       │   每个 SubAgent 可调用 Read/Glob/Grep 读取文件
    │       └── 编排器综合生成 JSON 报告
    │
    └── "openai"
        └── openai_engine.py
            ├── AsyncOpenAI client (streaming)
            ├── 4 specialist 并行 asyncio.gather
            │   每个 specialist = 独立 chat completion (stream=True)
            │   context_text 包含 workflow 文件内容 + 使用率数据
            ├── Synthesis call: 合成 4 份报告为统一 JSON
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
4. Agent Analysis (orchestrator.py → engine)
   ├── Anthropic: 编排器调度 4 个子 Agent，每个读取文件分析
   └── OpenAI: 4 个 streaming chat completion 并行 + 合成
        │
5. Parse Result
   ├── 提取 executive_summary (支持 string 或 list)
   ├── 提取 findings[] (severity, title, description, file, suggestion)
   └── 计算 stats (critical/major/minor/info 计数)
        │
6. Format & Store
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
│   ├── design.md              ← 本文档
│   ├── deployment.md          ← K8s 部署指南
│   ├── roadmap.md             ← 产品 Roadmap + SLA
│   └── webhook-design.md      ← Webhook 实时监控设计
├── deploy/
│   └── k8s/                   ← K8s manifests
├── Dockerfile.backend
├── Dockerfile.frontend
├── docker-compose.yaml
├── src/ci_optimizer/
│   ├── cli.py                 ← CLI 入口
│   ├── config.py              ← 配置管理
│   ├── resolver.py            ← 输入解析 (URL/路径/简写)
│   ├── filters.py             ← 分析过滤条件
│   ├── github_client.py       ← GitHub REST API 客户端
│   ├── prefetch.py            ← 数据预取 + 使用率计算
│   ├── agents/
│   │   ├── orchestrator.py    ← 引擎路由
│   │   ├── anthropic_engine.py ← Claude Agent SDK 引擎
│   │   ├── openai_engine.py   ← OpenAI streaming 引擎
│   │   ├── prompts.py         ← 共享 prompt + i18n
│   │   ├── efficiency.py      ← 效率专家
│   │   ├── security.py        ← 安全专家
│   │   ├── cost.py            ← 成本专家
│   │   └── errors.py          ← 错误专家
│   ├── api/
│   │   ├── app.py             ← FastAPI 应用
│   │   ├── routes.py          ← API 路由
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
└── tests/                     ← 137+ tests
    ├── test_resolver.py
    ├── test_filters.py
    ├── test_github_client.py
    ├── test_prefetch.py
    ├── test_db.py
    ├── test_api.py
    ├── test_config.py
    ├── test_formatter.py
    ├── test_e2e.py
    └── test_integration.py    ← 真实 GitHub API 集成测试
```

---

## API 端点

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | 触发分析 (repo + filters + agent_config) |
| GET | `/api/reports` | 报告列表 (分页 + repo 过滤) |
| GET | `/api/reports/{id}` | 报告详情 (含 findings) |
| GET | `/api/dashboard` | Dashboard 聚合数据 |
| GET | `/api/repositories` | 已分析仓库列表 |
| GET | `/api/config` | 查看配置 (敏感值脱敏) |
| PUT | `/api/config` | 更新配置 |
