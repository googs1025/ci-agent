# Langfuse LLM Observability Setup Guide

CI Agent integrates with [Langfuse](https://langfuse.com) to provide full observability for LLM calls, including token usage, cost tracking, latency, and prompt/response inspection.

## Overview

Langfuse tracing is **optional** and **non-invasive**. When not configured, it is silently disabled with zero performance impact.

You can choose between two deployment modes:

| Mode | Pros | Cons |
|------|------|------|
| **Langfuse Cloud** | No deployment needed, free tier available | Data stored on Langfuse servers |
| **Self-hosted** | Full data privacy, no external dependencies | Requires PostgreSQL + Langfuse container |

---

## Option 1: Langfuse Cloud (Recommended for Getting Started)

### Step 1: Create an Account

1. Go to [https://cloud.langfuse.com](https://cloud.langfuse.com)
2. Sign up and create a new **Project**

### Step 2: Get API Keys

1. In your project, go to **Settings** -> **API Keys**
2. Copy the **Public Key** and **Secret Key**

### Step 3: Configure Environment Variables

Add to your `.env` file:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_HOST=https://us.cloud.langfuse.com   # US region
# LANGFUSE_HOST=https://cloud.langfuse.com    # EU region
```

### Step 4: Restart CI Agent

```bash
# Local development
uv run uvicorn ci_optimizer.api.app:app --port 8000

# Docker Compose
docker compose restart backend
```

You should see in the logs:

```
Langfuse tracing enabled (host=https://us.cloud.langfuse.com)
```

---

## Option 2: Self-hosted (Recommended for Production)

### Docker Compose

Create a `docker-compose.langfuse.yaml`:

```yaml
services:
  langfuse:
    image: langfuse/langfuse:2
    ports:
      - "3002:3000"
    environment:
      - DATABASE_URL=postgresql://langfuse:changeme@langfuse-db:5432/langfuse
      - NEXTAUTH_SECRET=your-random-secret-string
      - NEXTAUTH_URL=http://localhost:3002
      - SALT=your-random-salt-string
      - HOSTNAME=0.0.0.0
      - TELEMETRY_ENABLED=false
    depends_on:
      langfuse-db:
        condition: service_healthy

  langfuse-db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=langfuse
      - POSTGRES_PASSWORD=changeme
      - POSTGRES_DB=langfuse
    volumes:
      - langfuse-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  langfuse-data:
```

```bash
docker compose -f docker-compose.langfuse.yaml up -d
```

### Kubernetes

Langfuse K8s manifests are included in `deploy/k8s/langfuse.yaml`. To deploy:

1. **Edit secrets** in `deploy/k8s/langfuse.yaml`:
   ```yaml
   stringData:
     POSTGRES_PASSWORD: "your-strong-password"    # Change this
     NEXTAUTH_SECRET: "your-random-secret"         # Change this
     SALT: "your-random-salt"                       # Change this
   ```

2. **Apply manifests**:
   ```bash
   kubectl apply -k deploy/k8s/
   ```

3. **Access Langfuse UI**:
   ```bash
   kubectl -n ci-agent port-forward svc/langfuse 3002:3000
   # Open http://localhost:3002
   ```

4. **Register and create a project** in the Langfuse UI

5. **Copy API keys** from the project settings

6. **Configure CI Agent** to use self-hosted Langfuse:

   For local development (`.env`):
   ```bash
   LANGFUSE_PUBLIC_KEY=pk-lf-your-key
   LANGFUSE_SECRET_KEY=sk-lf-your-key
   LANGFUSE_HOST=http://localhost:3002
   ```

   For K8s (already configured in `configmap.yaml`):
   ```yaml
   LANGFUSE_HOST: "http://langfuse:3000"   # In-cluster service URL
   ```

   Update the API keys in `secret.yaml`:
   ```yaml
   LANGFUSE_PUBLIC_KEY: "pk-lf-your-key"
   LANGFUSE_SECRET_KEY: "sk-lf-your-key"
   ```

---

## What Gets Traced

Once configured, the following LLM calls are automatically traced:

### OpenAI Engine
| Call | Data Captured |
|------|---------------|
| Specialist calls (parallel) | Prompt, response, tokens, cost, latency per skill |
| Synthesis call | Combined prompt, final report, tokens, cost |

### Anthropic Engine (Claude Agent SDK)
| Call | Data Captured |
|------|---------------|
| Multi-agent orchestration | Total cost, duration, session ID |

### Trace Structure

```
ci-analysis (root trace)
├── anthropic-analysis          # If using Anthropic provider
│   └── Claude Agent SDK calls  # Auto-traced via decorator
└── openai-analysis             # If using OpenAI provider
    ├── specialist: efficiency   # Parallel
    ├── specialist: security     # Parallel
    ├── specialist: cost         # Parallel
    ├── specialist: errors       # Parallel
    └── synthesis                # Final merge
```

---

## Using the Langfuse Dashboard

### Traces View

Navigate to **Traces** in the left sidebar to see all analysis runs:

- **Name**: `ci-analysis` — each analysis creates one trace
- **Latency**: Total time from start to finish
- **Cost**: Total USD cost of all LLM calls
- **Tokens**: Input/output token breakdown

Click a trace to see the full call tree with nested spans.

### Generations View

Navigate to **Generations** to see individual LLM calls:

- Full **prompt** content (system + user messages)
- Full **response** content
- **Model** name and parameters (temperature, etc.)
- **Token usage** (input/output/total)
- **Cost** per call

### Dashboard

The **Dashboard** tab shows aggregate metrics:

- Total cost over time
- Token usage trends
- Latency percentiles (p50, p90, p99)
- Model usage distribution
- Error rates

---

## Disabling Tracing

To disable Langfuse tracing, simply remove or unset the environment variables:

```bash
# Remove from .env
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
# LANGFUSE_HOST=
```

Or for K8s, set empty values in the secret:

```yaml
LANGFUSE_PUBLIC_KEY: ""
LANGFUSE_SECRET_KEY: ""
```

No code changes needed. The tracing module detects missing keys and disables itself.

---

## Troubleshooting

### "Langfuse not configured" in logs
- Check that both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set
- Verify `.env` file is in the project root directory

### Traces not appearing in dashboard
- Wait 10-30 seconds — events are batched and sent asynchronously
- Check backend logs for `Langfuse tracing enabled` message
- Verify `LANGFUSE_HOST` points to the correct URL

### Self-hosted: "Connection refused"
- Ensure PostgreSQL is running and healthy before Langfuse starts
- Check `DATABASE_URL` format: `postgresql://user:pass@host:5432/dbname`
- For K8s: verify `langfuse-postgres` service is running

### Self-hosted: Langfuse UI not loading
- Set `HOSTNAME=0.0.0.0` in the Langfuse container environment
- Use `langfuse/langfuse:2` image (v3 requires ClickHouse)
