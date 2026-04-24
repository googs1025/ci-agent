# ci-agent

AI 驱动的 GitHub CI 流水线分析和优化系统。支持 Anthropic (Claude) 和 OpenAI 双引擎。

**快速上手** → [使用指南 (中文)](docs/guides/zh/usage-guide.md) | [Usage Guide (EN)](docs/guides/en/usage-guide.md) | **完整文档** → [docs/](docs/README.md)

## Features

- **四维度分析**: 执行效率、安全最佳实践、成本优化、错误模式分析
- **单次失败诊断 (Failure Triage)**: 针对具体失败 Run 的 AI 根因分析，9 类错误分类 + 快速修复建议，支持手动触发 + Webhook 自动诊断 + 签名聚类去重
- **双 AI 引擎**: Anthropic (Claude) / OpenAI (任意兼容端点)
- **三种交互方式**: TUI 对话模式 (`ci-agent chat`) + CLI 命令行 + Web UI (Next.js Dashboard)
- **TUI 交互式对话**: 自然语言提问，AI 自动读取仓库文件，支持写入确认流程（diff 预览 + 用户确认）
- **写入操作确认**: AI 提出的文件修改先展示 diff，等用户确认后再执行，安全可控
- **多语言报告**: 中文 / 英文
- **CI 使用率统计**: Job 耗时、排队时间、Runner 分布、计费估算、最慢 Step 排名
- **智能输入**: 支持 GitHub URL / `owner/repo` 简写 / 本地路径
- **灵活过滤**: 时间范围、Workflow、状态、分支
- **LLM 可观测性**: 可选 Langfuse 集成，自动追踪 Token 用量、成本和延迟

## Architecture

```
  ┌─────────────────────────────────────────────────┐
  │                    Clients                       │
  │                                                  │
  │  ┌────────────┐  ┌──────────────┐  ┌─────────┐  │
  │  │  TUI Chat  │  │  Next.js     │  │   CLI   │  │
  │  │ (ci-agent  │  │  Web UI      │  │ analyze │  │
  │  │   chat)    │  │  (:3000)     │  │ command │  │
  │  └─────┬──────┘  └──────┬───────┘  └────┬────┘  │
  └────────┼────────────────┼───────────────┼────────┘
           │  SSE stream    │  REST         │ direct
           ▼                ▼               ▼
  ┌─────────────────────────────────────────────────┐
  │              FastAPI Backend (:8000)             │
  │                                                  │
  │  /api/chat (SSE)    /api/analyze   /api/reports  │
  │  /api/chat/apply    /api/config    /api/skills   │
  │       │                  │                       │
  │  ┌────▼───────┐   ┌──────▼──────────────────┐   │
  │  │ Chat Agent │   │   Analysis Orchestrator  │   │
  │  │  + Tools   │   │  anthropic / openai      │   │
  │  │ (tool_use  │   │  engine                  │   │
  │  │  + write   │   │  (4 specialist agents)   │   │
  │  │  proposal) │   └──────────────────────────┘   │
  │  └────────────┘                                  │
  └─────────────────────────────────────────────────┘
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
         SQLite DB    GitHub API   Anthropic /
                     (Run History) OpenAI API
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (仅 Web UI 需要)
- AI API Key (Anthropic 或 OpenAI 二选一)
- `GITHUB_TOKEN` (可选，用于获取 CI 运行历史)

### Install

```bash
git clone https://github.com/googs1025/ci-agent.git
cd ci-agent

python3 -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
# 编辑 .env 填入 API Key
```

### Configuration

#### Provider 选择

```bash
# 方式一：使用 Anthropic (Claude)
ci-agent config set provider anthropic
ci-agent config set anthropic_api_key sk-ant-...
ci-agent config set model claude-sonnet-4-20250514

# 方式二：使用 OpenAI (或任意兼容端点)
ci-agent config set provider openai
ci-agent config set openai_api_key sk-...
ci-agent config set model gpt-5.4
ci-agent config set base_url http://your-endpoint/v1   # 可选，默认 OpenAI 官方
```

#### 所有配置项

| Key | 环境变量 | 默认值 | 说明 |
|-----|---------|--------|------|
| `provider` | `CI_AGENT_PROVIDER` | `anthropic` | AI 引擎: `anthropic` / `openai` |
| `model` | `CI_AGENT_MODEL` | `claude-sonnet-4-20250514` | 模型名 |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | - | Anthropic API Key |
| `openai_api_key` | `OPENAI_API_KEY` | - | OpenAI API Key |
| `base_url` | `CI_AGENT_BASE_URL` | - | 自定义 API 端点 |
| `github_token` | `GITHUB_TOKEN` | - | GitHub Token |
| `language` | `CI_AGENT_LANGUAGE` | `en` | 报告语言: `en` / `zh` |
| `max_turns` | - | `20` | Agent 最大轮次 |

优先级: CLI 参数 > 环境变量 > `~/.ci-agent/config.json` > 默认值

#### 配置命令

```bash
ci-agent config show          # 查看当前配置（敏感值脱敏）
ci-agent config set key value # 设置配置项
ci-agent config path          # 查看配置文件路径
```

#### Web API 配置

```bash
# 查看
curl http://localhost:8000/api/config

# 更新
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai", "model": "gpt-5.4", "language": "zh"}'

# 单次分析使用不同配置
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo": "owner/repo", "agent_config": {"provider": "openai", "model": "gpt-4o", "language": "zh"}}'
```

### TUI 对话模式（推荐）

```bash
# 方式一：自动启动 Server + TUI（一键）
ci-agent chat

# 方式二：手动分别启动
ci-agent serve          # 终端 1：启动后端 Server
ci-agent chat           # 终端 2：启动 TUI

# 指定仓库路径
ci-agent chat --repo /path/to/repo
```

TUI 支持自然语言提问，AI 会自动读取仓库 workflow 文件并回答，也可以提出修改建议（先展示 diff 供你确认再写入）。

TUI 内置斜杠命令：
```
/help           查看帮助
/clear          清空对话历史
/model <name>   切换模型
/repo <path>    切换仓库
/quit           退出
```

### CLI 一次性分析

```bash
# 三种输入方式
ci-agent analyze owner/repo                              # GitHub 简写
ci-agent analyze https://github.com/owner/repo           # GitHub URL
ci-agent analyze /path/to/local/repo                     # 本地路径

# 带过滤条件
ci-agent analyze owner/repo \
  --since 2024-01-01 --status failure --branch main

# 指定 provider / 语言 / 输出格式
ci-agent analyze owner/repo \
  --provider openai --model gpt-5.4 --lang zh \
  --format json -o report.json
```

### Web UI

```bash
# 启动后端
ci-agent serve --port 8000

# 启动前端（另一个终端）
cd web && npm install && npm run dev
```

打开 http://localhost:3000

### Docker

```bash
cp .env.example .env
# 编辑 .env

docker compose up -d
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

详细部署文档见 [部署指南 (中文)](docs/guides/zh/deployment.md) | [Deployment Guide (EN)](docs/guides/en/deployment.md)

## Tech Stack

| 层 | 技术 |
|---|------|
| TUI | prompt_toolkit (REPL + 历史补全), Rich (渲染 + diff 展示) |
| Chat API | FastAPI SSE streaming, multi-turn agentic loop, write proposal 确认流 |
| AI (Anthropic) | Anthropic SDK, multi-turn tool use (read/write/git/CI tools) |
| AI (OpenAI) | OpenAI Python SDK, streaming, 并行 specialist |
| Backend | Python 3.10+, FastAPI, SQLAlchemy, SQLite |
| Frontend | Next.js 14, Tailwind CSS, TypeScript |
| Infra | Docker, Kubernetes, GitHub API |

## Documentation

> 完整文档索引见 [docs/README.md](docs/README.md)

### 用户指南

| 指南 | 中文 | English |
|------|------|---------|
| 使用指南 | [zh](docs/guides/zh/usage-guide.md) | [en](docs/guides/en/usage-guide.md) |
| 部署指南（Docker / K8s） | [zh](docs/guides/zh/deployment.md) | [en](docs/guides/en/deployment.md) |
| Langfuse 可观测性配置 | [zh](docs/guides/zh/langfuse-setup.md) | [en](docs/guides/en/langfuse-setup.md) |

### 架构设计
- [系统架构](docs/design/architecture.md) — 整体架构与模块设计
- [Skill 系统设计](docs/design/skill-system.md) — 声明式技能定义与扩展机制
- [Webhook 设计](docs/design/webhook.md) — 实时 CI 用量追踪方案（草案）
- [Failure Triage 设计](docs/design/failure-triage.md) — 单次失败 AI 诊断：skill 契约、DB 模型、成本控制、前端 UX

### 运维部署
- [部署指南 (中文)](docs/guides/zh/deployment.md) — Docker / Kubernetes 部署
- [Deployment Guide (EN)](docs/guides/en/deployment.md) — Docker / Kubernetes deployment

### 产品规划
- [Roadmap](docs/roadmap.md) — 产品路线图
