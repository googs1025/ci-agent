# ci-agent - Implementation Plan

## Context

构建一个 AI Agent 系统，用于分析和优化 GitHub 仓库的 CI 流水线。系统包含两种交互方式：
1. **CLI** — 命令行工具，快速分析
2. **Web UI** — React + Next.js 前端 + FastAPI 后端，提供 Dashboard、历史记录、可视化报告

核心能力：用户输入仓库（本地路径或 GitHub URL），Agent 分析 GitHub Actions workflow 和运行历史，输出四维度结构化分析报告（执行效率、安全最佳实践、成本优化、错误分析）。

支持过滤条件：时间范围、Workflow 筛选、运行状态、分支。

技术栈：Python Claude Agent SDK + FastAPI + SQLite + Next.js (React)。MVP 无用户认证，架构预留 OAuth 位置。

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Clients                               │
│  ┌──────────┐    ┌──────────────────────────────────────┐   │
│  │   CLI    │    │  Next.js Web UI                       │   │
│  │ (argparse)│    │  ├─ Dashboard (多仓库概览/趋势图)     │   │
│  │          │    │  ├─ Analysis (触发分析/查看报告)       │   │
│  └────┬─────┘    │  └─ History (历史记录/对比)           │   │
│       │          └──────────────┬───────────────────────┘   │
│       │                        │                             │
│       ▼                        ▼                             │
│  ┌─────────────────────────────────────────────┐            │
│  │          FastAPI Backend (API Layer)          │            │
│  │  POST /api/analyze    — 触发分析              │            │
│  │  GET  /api/reports     — 查询历史报告          │            │
│  │  GET  /api/reports/:id — 查看单个报告          │            │
│  │  GET  /api/dashboard   — Dashboard 聚合数据    │            │
│  └────────────────────┬────────────────────────┘            │
│                       │                                      │
│  ┌────────────────────▼────────────────────────┐            │
│  │           Core Analysis Engine               │            │
│  │  ┌──────────┐  ┌───────────┐  ┌──────────┐ │            │
│  │  │ Resolver │  │ Prefetch  │  │ Agent    │ │            │
│  │  │(URL/Path)│→ │(GitHub API)│→ │Orchestr. │ │            │
│  │  └──────────┘  └───────────┘  └────┬─────┘ │            │
│  │                                     │       │            │
│  │    ┌────────────┬──────────┬────────┤       │            │
│  │    ▼            ▼          ▼        ▼       │            │
│  │  efficiency  security   cost    error       │            │
│  │  analyst     analyst   analyst  analyst     │            │
│  └─────────────────────────────────────────────┘            │
│                       │                                      │
│  ┌────────────────────▼────────────────────────┐            │
│  │         SQLite (via SQLAlchemy)               │            │
│  │  reports / analyses / repositories            │            │
│  └──────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ci-agent/
├── pyproject.toml
├── .env.example                    # ANTHROPIC_API_KEY, GITHUB_TOKEN
├── src/
│   └── ci_optimizer/
│       ├── __init__.py
│       ├── cli.py                  # CLI 入口 (argparse)
│       ├── resolver.py             # 输入检测: 本地路径 vs GitHub URL
│       ├── github_client.py        # GitHub REST API 客户端 (httpx)
│       ├── prefetch.py             # 预取数据 + 过滤逻辑
│       ├── filters.py              # 过滤条件定义 (时间/workflow/状态/分支)
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── orchestrator.py     # 编排器 Agent
│       │   ├── efficiency.py       # 执行效率专家
│       │   ├── security.py         # 安全最佳实践专家
│       │   ├── cost.py             # 成本优化专家
│       │   └── errors.py           # 错误分析专家
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py              # FastAPI 应用
│       │   ├── routes.py           # API 路由
│       │   └── schemas.py          # Pydantic request/response models
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py           # SQLAlchemy ORM models
│       │   ├── database.py         # DB engine + session
│       │   └── crud.py             # CRUD 操作
│       └── report/
│           ├── __init__.py
│           └── formatter.py        # 报告组装 (Markdown + JSON)
├── web/                            # Next.js 前端
│   ├── package.json
│   ├── next.config.js
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx            # Dashboard 首页
│   │   │   ├── analyze/
│   │   │   │   └── page.tsx        # 分析页 (输入仓库 + 过滤条件)
│   │   │   ├── reports/
│   │   │   │   ├── page.tsx        # 报告列表
│   │   │   │   └── [id]/
│   │   │   │       └── page.tsx    # 报告详情
│   │   │   └── api/                # Next.js API routes (proxy to FastAPI)
│   │   ├── components/
│   │   │   ├── ReportCard.tsx      # 报告卡片 (四维度)
│   │   │   ├── FilterPanel.tsx     # 过滤面板 (时间/workflow/状态/分支)
│   │   │   ├── AnalysisForm.tsx    # 分析表单
│   │   │   ├── DashboardChart.tsx  # 趋势图表
│   │   │   └── FindingTable.tsx    # 发现列表表格
│   │   ├── lib/
│   │   │   └── api.ts              # API 客户端 (fetch wrapper)
│   │   └── types/
│   │       └── index.ts            # TypeScript 类型定义
│   └── tailwind.config.js
└── tests/
    ├── test_resolver.py
    ├── test_github_client.py
    ├── test_prefetch.py
    └── test_api.py
```

---

## Implementation Steps

### Step 1: Project Scaffold + Core Data Models
**Files:** `pyproject.toml`, `__init__.py`, `resolver.py`, `filters.py`, `db/models.py`, `db/database.py`

**Python 依赖:**
```
claude-agent-sdk>=0.1.48
httpx
python-dotenv
pyyaml
fastapi
uvicorn
sqlalchemy[asyncio]
aiosqlite
pydantic
```

**resolver.py:**
- `is_github_url(input: str) -> bool`
- `parse_github_url(url: str) -> tuple[str, str]` — 提取 owner/repo
- `detect_github_remote(local_path: Path) -> tuple[str, str] | None`
- `resolve_input(input: str) -> ResolvedInput` dataclass

**filters.py — 过滤条件:**
```python
@dataclass
class AnalysisFilters:
    time_range: tuple[datetime, datetime] | None  # 时间范围
    workflows: list[str] | None                    # 指定 workflow 文件名
    status: list[str] | None                       # success/failure/cancelled
    branches: list[str] | None                     # 分支过滤
```

**db/models.py — SQLAlchemy models:**
- `Repository` — id, owner, repo, url, last_analyzed_at
- `AnalysisReport` — id, repo_id, created_at, filters_json, status (pending/running/completed/failed), summary_md, full_report_json, duration_ms
- `Finding` — id, report_id, dimension (efficiency/security/cost/error), severity (critical/major/minor/info), title, description, file_path, suggestion

### Step 2: GitHub API Client + Data Prefetch
**Files:** `github_client.py`, `prefetch.py`

**github_client.py** — httpx 异步客户端:
- `list_workflow_runs(owner, repo, filters: AnalysisFilters)` — 根据过滤条件获取运行记录
- `get_run_jobs(owner, repo, run_id)` — 获取 job 详情 (步骤耗时、结论)
- `get_run_logs(owner, repo, run_id)` — 下载失败 job 的日志 (截断到 2000 行)
- `get_workflow_timing(owner, repo, workflow_id)` — 计费数据
- 统一: rate limit 处理、token 认证、错误重试

**prefetch.py** — `prepare_context(resolved, filters) -> AnalysisContext`:
- URL 输入: `git clone --depth=1` 到 tempdir
- 本地输入: 直接读取
- 调用 github_client 预取，应用 filters
- 数据写入临时 JSON 文件 (runs.json, logs.json)
- 返回 `AnalysisContext(local_path, workflows, runs_json_path, logs_json_path, filters)`

### Step 3: Specialist Agent Definitions
**Files:** `agents/efficiency.py`, `agents/security.py`, `agents/cost.py`, `agents/errors.py`

每个文件导出一个 `AgentDefinition`，复用 `learn-ai-agent/05-multi-agent/03_orchestrator.py` 的模式。

所有专家共享:
- **tools:** `["Read", "Glob", "Grep"]`
- **输出格式要求:** JSON 结构 `{findings: [{severity, title, description, file, line, suggestion, impact}]}`

**各专家分析要点见上一版计划（不变）。**

### Step 4: Orchestrator Agent + Analysis Engine
**Files:** `agents/orchestrator.py`, `agents/__init__.py`

**orchestrator.py:**
```python
ORCHESTRATOR_PROMPT = """你是 CI 流水线分析编排器。职责:
1. 调度 4 个专家 Agent 分析 workflow 文件和运行数据
2. 汇总所有专家的发现
3. 生成 Executive Summary (Top 5 跨维度优先建议)
4. 按 severity 排序所有发现

可用专家: efficiency-analyst, security-analyst, cost-analyst, error-analyst
请依次调用所有专家，然后综合分析。
"""

AGENTS = {
    "efficiency-analyst": efficiency_agent,
    "security-analyst": security_agent,
    "cost-analyst": cost_agent,
    "error-analyst": error_agent,
}
```

**核心分析函数** `run_analysis(input_spec, filters) -> AnalysisResult`:
1. `resolve_input(input_spec)`
2. `prepare_context(resolved, filters)`
3. 构造 prompt（注入 context 路径）
4. `query(prompt, options=ClaudeAgentOptions(system_prompt=..., agents=AGENTS, ...))`
5. 解析输出为结构化 `AnalysisResult`

### Step 5: FastAPI Backend
**Files:** `api/app.py`, `api/routes.py`, `api/schemas.py`, `db/crud.py`

**API 路由:**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/analyze` | 触发分析 (body: repo_url/path + filters) |
| GET | `/api/reports` | 查询报告列表 (query: repo, page, limit) |
| GET | `/api/reports/{id}` | 获取单个报告详情 |
| GET | `/api/dashboard` | Dashboard 数据 (仓库数、总分析数、维度分布) |
| GET | `/api/repositories` | 已分析仓库列表 |

**schemas.py — Pydantic models:**
- `AnalyzeRequest`: repo (str), filters (时间/workflow/状态/分支)
- `ReportResponse`: id, repo, created_at, summary, findings[], duration_ms
- `DashboardResponse`: repo_count, analysis_count, severity_distribution, recent_reports

**分析流程:**
1. POST `/api/analyze` 接收请求
2. 创建 report 记录 (status=running)
3. 后台运行 `run_analysis()`
4. 完成后更新 report 记录 (status=completed, 存入 findings)
5. 前端轮询 GET `/api/reports/{id}` 获取结果

### Step 6: CLI 入口
**Files:** `cli.py`

```bash
# 基本用法
ci-agent analyze /path/to/repo
ci-agent analyze https://github.com/owner/repo

# 带过滤
ci-agent analyze https://github.com/owner/repo \
  --since 2024-01-01 --until 2024-03-01 \
  --workflow ci.yml \
  --status failure \
  --branch main

# 启动 Web 服务
ci-agent serve --port 8000
```

### Step 7: Next.js 前端
**Files:** `web/` 目录

**技术栈:** Next.js 14 (App Router) + Tailwind CSS + shadcn/ui

**页面:**

1. **Dashboard (`/`)** — 概览页
   - 已分析仓库数量卡片
   - 最近分析列表
   - 各维度发现数量分布 (柱状图/饼图)
   - CI 健康趋势 (折线图: 过去 N 次分析的发现数量变化)

2. **Analyze (`/analyze`)** — 分析页
   - 输入框: GitHub URL 或仓库名
   - 过滤面板: 时间范围 (date picker)、Workflow 选择、状态、分支
   - "开始分析" 按钮
   - 分析进行中: 进度指示器
   - 分析完成: 跳转到报告详情

3. **Reports (`/reports`)** — 历史列表
   - 报告列表 (表格: 仓库、时间、发现数、耗时)
   - 按仓库/时间/严重度排序和筛选
   - 支持分页

4. **Report Detail (`/reports/[id]`)** — 报告详情
   - Executive Summary 卡片
   - 4 个维度 Tab 切换
   - 每个维度: Finding 表格 (severity badge, 文件位置, 建议)
   - Markdown 原文查看切换

**组件:**
- `FilterPanel` — 过滤面板 (时间 DateRangePicker、Workflow MultiSelect、状态 Checkbox、分支 Input)
- `ReportCard` — 报告摘要卡片 (4 维度 severity 统计)
- `FindingTable` — 发现列表 (severity icon、标题、文件、建议)
- `DashboardChart` — 图表组件 (用 recharts 或 chart.js)
- `AnalysisForm` — 分析输入表单

**前端依赖:** `next`, `react`, `tailwindcss`, `@shadcn/ui`, `recharts`, `date-fns`

### Step 8: Integration + Polish
- 前端 `api.ts` 对接 FastAPI 后端
- 错误处理: 无效仓库、无 token、无 workflow、API 超时
- 加载状态和错误状态 UI
- 响应式布局

---

## Key Reference Files

| Pattern | File | Reuse |
|---------|------|-------|
| Orchestrator + SubAgents | `/Users/zhenyu.jiang/learn-ai-agent/05-multi-agent/03_orchestrator.py` | Agent 调度、AgentDefinition、query() |
| Custom MCP Tools | `/Users/zhenyu.jiang/learn-ai-agent/02-tools/02_custom_mcp_tool.py` | @tool + create_sdk_mcp_server |
| Parallel Pipeline | `/Users/zhenyu.jiang/learn-ai-agent/05-multi-agent/04_parallel_pipeline.py` | asyncio.gather 并行参考 |
| Real workflow | `/Users/zhenyu.jiang/nanoclaw/.github/workflows/ci.yml` | 测试目标 |

---

## Verification

1. **单元测试:**
   - `test_resolver.py`: URL 解析、本地路径检测
   - `test_github_client.py`: Mock API 响应测试
   - `test_prefetch.py`: 过滤逻辑、上下文组装
   - `test_api.py`: FastAPI 路由测试

2. **集成测试:**
   - 用 nanoclaw 仓库 (`/Users/zhenyu.jiang/nanoclaw`) 作为本地输入，验证完整分析流程
   - 验证报告包含所有 4 个维度

3. **端到端测试:**
   - CLI: `ci-agent analyze /Users/zhenyu.jiang/nanoclaw`
   - CLI with filters: `ci-agent analyze /Users/zhenyu.jiang/nanoclaw --since 2024-01-01 --status failure`
   - Web: 启动 `ci-agent serve` + `cd web && npm run dev`，浏览器访问 Dashboard，输入仓库 URL 触发分析，查看报告
   - 验证过滤条件生效（对比有过滤和无过滤的结果）

4. **边界情况:**
   - 无 workflow 文件的仓库 → 友好错误
   - 无 GITHUB_TOKEN → 提示配置
   - 私有仓库 → token 权限不足提示

---

## Project Creation & GitHub

**项目位置:** `/Users/zhenyu.jiang/ci-agent`

**创建步骤:**
1. `mkdir -p /Users/zhenyu.jiang/ci-agent` + `git init`
2. 按 Step 1-8 逐步创建文件
3. 创建 GitHub 仓库: `gh repo create ci-agent --public --source=. --push`
4. 每完成一个 Step 提交一次，保持清晰的 commit 历史
