# Failure Triage — Per-Run AI Diagnosis Design

> Issue: [#35](https://github.com/googs1025/ci-agent/issues/35)
> Depends on (v1+): [#36](https://github.com/googs1025/ci-agent/issues/36) — CI run metadata persistence
> Related: [#32](https://github.com/googs1025/ci-agent/issues/32) failure detail page, [#33](https://github.com/googs1025/ci-agent/issues/33) category classification, [#34](https://github.com/googs1025/ci-agent/issues/34) reliability dashboard

## 1. Problem

The existing `error-analyst` skill analyzes CI failures at the **repository-aggregate** level. Users still have no way to ask: **"Why did run #1234567 fail?"**

This design adds per-run AI diagnosis: given a `(repo, run_id)`, fetch the failed job's logs, extract the key error excerpt, run a focused LLM skill, and return a structured diagnosis card with category, root cause, failing step, and a quick fix.

## 2. Non-Goals

- **Not replacing `error-analyst`** — that skill still handles aggregate analysis.
- **Not a chat interface** — output is a structured JSON card, not a conversation.
- **Not automatic PR-creation** — v0-v2 output suggestions only; auto-remediation is v3+.

## 3. Architecture Overview

```
                     ┌──────── GitHub Actions run fails ────────┐
                     │                                           │
                     ▼                                           │
          Webhook (workflow_run.completed)            Frontend failure detail page (#32)
                     │                                           │
                     │ (v1+ auto)                                │ (v2 manual click)
                     ▼                                           ▼
            ┌────────────────────────────────────────────────────────┐
            │            POST /api/ci-runs/diagnose                  │
            │            body: {repo, run_id, tier?}                 │
            └──────────────────────┬─────────────────────────────────┘
                                   │
                                   ▼
                   ┌───────────────────────────────┐
                   │  1. Cache lookup              │
                   │     v0: in-memory (5min TTL)  │
                   │     v1: DB (per run_attempt)  │
                   └──────────┬────────────────────┘
                              │ miss
                              ▼
                   ┌───────────────────────────────┐
                   │  2. GitHubClient fetch        │
                   │     get_run → get_jobs →      │
                   │     get_logs for failing job  │
                   └──────────┬────────────────────┘
                              │
                              ▼
                   ┌───────────────────────────────┐
                   │  3. log_extractor             │
                   │     anchor-based excerpt +    │
                   │     signature hash            │
                   └──────────┬────────────────────┘
                              │
                              ▼
                   ┌───────────────────────────────┐
                   │  4. failure-triage skill      │
                   │     Haiku (default) or        │
                   │     Sonnet (tier=deep)        │
                   │     + Langfuse @observe       │
                   └──────────┬────────────────────┘
                              │
                              ▼
                   ┌───────────────────────────────┐
                   │  5. JSON validator + cache    │
                   │     store + return response   │
                   └───────────────────────────────┘
```

## 4. Roadmap

| Phase | Scope | PR Size | Depends On |
|-------|-------|---------|------------|
| **v0** | skill + log extractor + API + in-memory cache (no DB, no frontend) | ~700 LOC | none |
| **v1** | DB persistence (`failure_diagnoses`), signature clustering, webhook auto, cost budget | ~400 LOC | #36 |
| **v2** | Frontend Diagnose card + button, integration with #32 failure detail page | ~500 LOC | v1 |
| v3+ | Auto-remediation PR suggestions, embedding-based clustering | — | v2 |

## 5. v0 — Walking Skeleton

### 5.1 Skill Contract

`skills/failure-triage/SKILL.md` — must output strict JSON only.

```yaml
---
name: failure-triage
description: Diagnose a single failed CI run. Input: error excerpt. Output: structured diagnosis.
dimension: errors
tools: [Read]          # not used, but required field
requires_data: []      # operates on passed-in excerpt, no prefetch
---
```

**Output JSON schema (strict)**:

```json
{
  "category": "flaky_test|timeout|dependency|network|resource_limit|config|build|infra|unknown",
  "confidence": "high|medium|low",
  "root_cause": "One-sentence explanation (≤200 chars)",
  "quick_fix": "Actionable one-liner fix, or null if no fix",
  "failing_step": "Name of the failing step (echoed from input)"
}
```

**Few-shot strategy**: 3 examples covering flaky test, timeout, dependency failure.

### 5.2 Log Extractor (`src/ci_optimizer/data/log_extractor.py`)

```python
ERROR_ANCHORS = (
    "##[error]", "Error:", "ERROR:", "error:",
    "Exception", "Traceback", "FAILED",
    "fatal:", "✗", "FAIL "
)

def extract_error_excerpt(
    log_text: str,
    max_lines: int = 200,
) -> tuple[str, str | None]:
    """
    Locate the LAST error anchor; return (excerpt, first_error_line).
    Fallback: tail(max_lines) with first_error_line=None.
    """

def compute_signature(
    failing_step: str | None,
    first_error_line: str | None,
) -> str:
    """12-char MD5 hash of normalized (step + first_error_line)."""
```

**Normalization** (for stable signatures across runs):
- timestamps → `<TS>`
- hex IDs → `<HEX>`
- path segments → `<PATH>`
- bare integers → `<N>`
- truncate to 200 chars

### 5.3 Agent Runner (`src/ci_optimizer/agents/failure_triage.py`)

Single-skill LLM call (no orchestrator, no parallel specialists — this is deliberately lean).

```python
@langfuse_observe(name="failure-triage")
async def diagnose(
    excerpt: str,
    failing_step: str | None,
    workflow: str,
    model: str,
    config: AgentConfig,
) -> dict:
    """
    Returns: {category, confidence, root_cause, quick_fix, failing_step, cost_usd, model}
    Raises: on empty excerpt or model API error
    """
```

**Provider routing**:
- `model.startswith("claude")` → Anthropic SDK direct call (no Agent SDK; keeps it simple)
- else → OpenAI SDK

**Strict JSON parse**:
- Extract first `{...}` block via regex
- Validate `category` against 9-enum; fallback to `unknown`
- Validate `confidence` against 3-enum; fallback to `low`

### 5.4 API Endpoint (`src/ci_optimizer/api/diagnose.py`)

```
POST /api/ci-runs/diagnose
  body: {repo: "owner/name", run_id: int, tier: "default"|"deep"}
  → DiagnoseResponse (sync, typically <10s)
```

**In-memory cache** (v0 only):
```python
_cache: dict[tuple[str, int, str], tuple[DiagnoseResponse, float]] = {}
TTL_SEC = 300  # 5 min
```

Key = `(repo, run_id, tier)`. v1 replaces this with DB lookup by `(repo_id, run_id, run_attempt, tier)`.

### 5.5 Config

```python
# AgentConfig additions
diagnose_default_model: str = "claude-haiku-4-5-20251001"
diagnose_deep_model: str = "claude-sonnet-4-6"
```

Env overrides: `DIAGNOSE_DEFAULT_MODEL`, `DIAGNOSE_DEEP_MODEL`.

### 5.6 Tests

| File | What it covers |
|------|---------------|
| `tests/test_log_extractor.py` | anchor detection, fallback, signature stability across timestamps/IDs |
| `tests/test_diagnose_api.py` | endpoint happy path (GitHub mocked, LLM mocked), cache hit, missing run, no failed jobs |

## 6. v1 — Persistence & Scale

### 6.1 New Table (`failure_diagnoses`)

```sql
CREATE TABLE failure_diagnoses (
    id              INTEGER PRIMARY KEY,
    ci_run_id       INTEGER REFERENCES ci_runs(id) ON DELETE CASCADE,
    tier            TEXT NOT NULL,            -- default | deep
    category        TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    root_cause      TEXT NOT NULL,
    quick_fix       TEXT,
    failing_step    TEXT,
    error_excerpt   TEXT NOT NULL,
    error_signature TEXT NOT NULL,
    model           TEXT NOT NULL,
    cost_usd        REAL,
    created_at      TIMESTAMP NOT NULL,
    UNIQUE(ci_run_id, tier)
);
CREATE INDEX ix_diag_signature_created ON failure_diagnoses(error_signature, created_at);
```

### 6.2 Webhook Auto-Diagnosis

```
POST /api/webhooks/github (existing)
  ├─ existing: trigger full AnalysisReport
  └─ NEW: if workflow_run.conclusion == "failure" and DIAGNOSE_AUTO_ON_WEBHOOK:
          enqueue BackgroundTask → diagnose(run_id, tier="default")
```

### 6.3 Cost Controls

| Control | Default | Purpose |
|---------|---------|---------|
| `DIAGNOSE_AUTO_ON_WEBHOOK` | `true` | Master switch for auto mode |
| `DIAGNOSE_SAMPLE_RATE` | `1.0` | 0.0–1.0 random sampling before dispatch |
| `DIAGNOSE_BUDGET_USD_DAY` | `1.0` | Daily ceiling; auto pauses until UTC midnight when exceeded |
| Signature dedup | 24h | Same error_signature within 24h reuses cached diagnosis |

### 6.4 Clustering API

```
GET /api/diagnoses/by-signature/{sig}?days=30
  → {signature, count, runs: [{run_id, workflow, branch, failed_at}]}
```

## 7. v2 — Frontend Integration

### 7.1 Failure Detail Page (from #32)

Layout:

```
┌─── Run #1234567 — workflow "ci" — branch main ───┐
│                                                   │
│ ┌─ Diagnosis Card (failure-triage) ────────────┐ │
│ │ [category badge]  confidence: high            │ │
│ │                                                │ │
│ │ Root cause:                                    │ │
│ │   Test sensitive to upstream 502 responses     │ │
│ │                                                │ │
│ │ Failing step: pytest unit                      │ │
│ │                                                │ │
│ │ Quick fix:                                     │ │
│ │   @pytest.mark.flaky(reruns=2, reruns_delay=1)│ │
│ │   [Copy]                                       │ │
│ │                                                │ │
│ │ Similar errors: 12 times in last 30 days →     │ │
│ │                                                │ │
│ │ Model: claude-haiku-4-5  cost: $0.002         │ │
│ │                                    [Deep Analysis]
│ └───────────────────────────────────────────────┘ │
│                                                   │
│ ┌─ Step Timeline ──────────────────────────────┐ │
│ │  ✓ checkout          00:02                    │ │
│ │  ✓ setup-python      00:15                    │ │
│ │  ✗ pytest unit       02:34  ← failed         │ │
│ │    └─ log excerpt...                          │ │
│ └───────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────┘
```

### 7.2 Components

```
web/src/components/
├── FailureDiagnosisCard.tsx      # main card
├── CategoryBadge.tsx             # color-coded (9 categories)
├── SimilarErrorsLink.tsx         # "12 times in 30d" → modal
└── DiagnoseButton.tsx            # triggers POST if no cached diagnosis
```

### 7.3 i18n Keys

```ts
diagnose: {
  title:        { en: 'AI Diagnosis', zh: 'AI 诊断' },
  rootCause:    { en: 'Root cause',   zh: '根本原因' },
  quickFix:     { en: 'Quick fix',    zh: '快速修复' },
  failingStep:  { en: 'Failing step', zh: '失败步骤' },
  similar:      { en: '{count} times in {days}d', zh: '近 {days} 天 {count} 次' },
  deepAnalysis: { en: 'Deep Analysis', zh: '深度分析' },
  category: {
    flaky_test:     { en: 'Flaky Test',     zh: '不稳定测试' },
    timeout:        { en: 'Timeout',        zh: '超时' },
    dependency:     { en: 'Dependency',     zh: '依赖问题' },
    network:        { en: 'Network',        zh: '网络问题' },
    resource_limit: { en: 'Resource Limit', zh: '资源限制' },
    config:         { en: 'Configuration',  zh: '配置问题' },
    build:          { en: 'Build Failure',  zh: '构建失败' },
    infra:          { en: 'Infrastructure', zh: '基础设施' },
    unknown:        { en: 'Unknown',        zh: '未知' },
  },
},
```

## 8. Model Strategy & Cost

| Tier | Model | When | Est. cost/call |
|------|-------|------|----------------|
| default | `claude-haiku-4-5-20251001` | First pass (manual + webhook) | ~$0.001–0.003 |
| deep | `claude-sonnet-4-6` | User clicks "Deep Analysis" | ~$0.015–0.03 |

**Input budget**: ≤4K tokens (excerpt capped at ~200 lines ≈ 2–3K tokens + prompt overhead).

**Why not GPT-4?** Anthropic Haiku is priced for high-volume short-context tasks like this (classification + short generation). If user is OpenAI-only, we fall back to `gpt-4o-mini` for default and `gpt-4o` for deep.

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| LLM returns malformed JSON | Strict parser extracts first `{...}`; fall back to `category="unknown"` with `error_excerpt` only |
| GitHub log >10 MB | `get_run_logs` already caps at `max_lines=2000`; extractor re-caps at 200 |
| Webhook spam drains budget | v1 sample rate + daily budget + signature dedup |
| Same run re-diagnosed (different tier) | Cache key includes `tier` — deep analysis doesn't evict default |
| User has no ANTHROPIC_API_KEY | Provider auto-detection via `AgentConfig.provider`; fallback to OpenAI models |

## 10. Observability

Every diagnose call is wrapped in `@langfuse_observe(name="failure-triage")`. Langfuse dashboard shows:
- Tokens + cost per diagnosis
- Category distribution (via custom metadata)
- p50/p99 latency
- Error rate (malformed JSON, API errors)

## 11. Security

- `repo` in request body is validated as `owner/name` (regex `^[\w.-]+/[\w.-]+$`)
- No log content is logged to stdout (only diagnosis metadata)
- `GITHUB_TOKEN` scopes: `actions:read` only
- Existing `CI_AGENT_API_KEY` auth middleware protects the endpoint