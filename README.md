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
git clone https://github.com/YOUR_USERNAME/ci-agent.git
cd ci-agent

# Python backend
pip install -e .

# Copy env
cp .env.example .env
# Edit .env with your API keys
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
