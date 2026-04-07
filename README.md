# ci-agent

AI-powered GitHub CI pipeline analyzer and optimizer, built with Python Claude Agent SDK.

## Features

- **Multi-dimensional analysis**: Execution efficiency, security best practices, cost optimization, error pattern analysis
- **Dual interface**: CLI tool + Web UI (Next.js dashboard)
- **Smart filtering**: Filter by time range, workflow, status, branch
- **GitHub integration**: Analyze local repos or remote GitHub URLs
- **Historical tracking**: SQLite-backed report history with Dashboard overview

## Architecture

```
Orchestrator Agent
├── Efficiency Analyst  (parallelization, caching, matrix)
├── Security Analyst    (permissions, pinning, secrets)
├── Cost Analyst        (billing, runners, redundancy)
└── Error Analyst       (failure patterns, root causes)
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for Web UI)
- `ANTHROPIC_API_KEY` — Claude API key
- `GITHUB_TOKEN` — GitHub personal access token (for API data)

### Install

```bash
# Clone
git clone https://github.com/googs1025/ci-agent.git
cd ci-agent

# Python backend
pip install -e .

# Copy env
cp .env.example .env
# Edit .env with your API keys
```

### Configuration

配置模型和 API Key 有三种方式，优先级从高到低：

**1. 命令行参数（单次生效）**

```bash
ci-agent analyze --model claude-opus-4-20250514 --api-key sk-ant-... https://github.com/owner/repo
```

**2. 环境变量**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...
export CI_AGENT_MODEL=claude-opus-4-20250514
```

**3. 持久化配置文件（~/.ci-agent/config.json）**

```bash
# 设置模型
ci-agent config set model claude-opus-4-20250514

# 设置 API Key
ci-agent config set anthropic_api_key sk-ant-...
ci-agent config set github_token ghp_...

# 设置备选模型
ci-agent config set fallback_model claude-sonnet-4-20250514

# 设置最大轮次
ci-agent config set max_turns 30

# 查看当前配置（敏感值会脱敏显示）
ci-agent config show

# 查看配置文件路径
ci-agent config path
```

可配置项：

| Key | Description | Default |
|-----|-------------|---------|
| `model` | Agent 使用的模型 | `claude-sonnet-4-20250514` |
| `fallback_model` | 备选模型 | - |
| `anthropic_api_key` | Anthropic API Key | - |
| `github_token` | GitHub Token (用于获取 CI 运行历史) | - |
| `max_turns` | Agent 最大对话轮次 | `20` |

Web API 也支持配置：

```bash
# 查看配置
curl http://localhost:8000/api/config

# 更新配置
curl -X PUT http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-opus-4-20250514"}'

# 单次分析使用不同模型
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo": "https://github.com/owner/repo", "agent_config": {"model": "claude-opus-4-20250514"}}'
```

### CLI Usage

```bash
# Analyze a local repo
ci-agent analyze /path/to/your/repo

# Analyze a GitHub repo
ci-agent analyze https://github.com/owner/repo

# With filters
ci-agent analyze https://github.com/owner/repo \
  --since 2024-01-01 \
  --status failure \
  --branch main \
  --format json -o report.json

# Use a specific model for this run
ci-agent analyze --model claude-opus-4-20250514 https://github.com/owner/repo
```

### Web UI

```bash
# Start API server
ci-agent serve --port 8000

# In another terminal, start frontend
cd web
npm install
npm run dev
```

Open http://localhost:3000

## Tech Stack

- **Backend**: Python, Claude Agent SDK, FastAPI, SQLAlchemy, SQLite
- **Frontend**: Next.js 14, Tailwind CSS, TypeScript
- **AI**: Claude (via Agent SDK) with orchestrator + specialist agent pattern
