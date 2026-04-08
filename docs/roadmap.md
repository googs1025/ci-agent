# CI Agent Roadmap

## 核心目标

用户使用后可以快速知道：
- 当前 CI job **为何失败**？是代码问题、flaky test、还是平台问题？
- **谁引入的**？哪个分支、哪个 commit、哪个 PR？
- **何时开始的**？是新回归还是历史遗留？

### SLA 目标

| SLA 指标 | 定义 | 目标 |
|---------|------|------|
| **MTTD** (平均故障发现时间) | 从 CI 失败到用户知道失败原因 | < 3 分钟（当前需 SSH 排查 15-30 分钟） |
| **MTTC** (平均故障分类时间) | 确认是代码/flaky/平台问题 | < 1 分钟（当前靠人工判断 5-15 分钟） |
| **MTTR** (平均故障恢复时间) | 从发现到修复 | 缩短 50%（通过精确定位到 commit） |
| **SSH 排查时间** | 登机器看日志的时间 | 减少 80%（报告中直接给出关键错误） |
| **重复故障率** | 同一问题反复出现 | 下降 60%（通过 flaky 检测和根因去重） |
| **Flaky 检测率** | 发现 flaky test 的覆盖率 | > 90% |

---

## 当前状态 (v0.1)

### 已完成

- [x] CLI + Web UI 双交互方式
- [x] 输入：本地路径 / GitHub URL
- [x] 四维度 Agent 分析：效率、安全、成本、错误
- [x] 过滤：时间范围、workflow、状态、分支
- [x] 所有 run 的 job/step 级耗时采集
- [x] 使用率统计：成功率、runner 分布、计费估算、排队时间、最慢 step
- [x] 用户可配置模型和 API Key
- [x] SQLite 持久化 + FastAPI REST API
- [x] Next.js Dashboard / 报告详情页
- [x] K8s 部署方案
- [x] 测试覆盖：129 tests (单元 + E2E + 集成)

### 当前 Gap

```
目标: 快速定位失败根因           现状: Agent 自由分析，无结构化分类
目标: 定位到 commit/PR          现状: 只有 branch，没有 commit SHA/PR
目标: 区分 flaky vs 真实失败     现状: 有统计，无检测算法
目标: 减少 SSH 排查             现状: 日志未按 step 拆分，未提取关键错误
目标: 主动发现问题              现状: 被动触发，无通知
```

---

## Phase 1: 故障分类 + 数据补全 (1-2 周)

> 核心交付：每个失败 run 自动分类为「代码错误 / flaky test / 平台问题 / 依赖问题 / 配置问题」

### 1.1 补全 Run 元数据

当前 `prefetch.py` 对 run 只采集了 `id`, `name`, `conclusion`, `head_branch`。需要补全：

| 字段 | GitHub API 字段 | 用途 |
|------|----------------|------|
| Commit SHA | `head_sha` | 精确定位代码版本 |
| Commit Message | `head_commit.message` | 展示变更说明 |
| 触发事件 | `event` (push/pull_request/schedule) | 区分触发来源 |
| PR 信息 | `pull_requests[].number`, `pull_requests[].url` | 关联到 PR |
| Run Attempt | `run_attempt` | 识别重试行为 |
| Actor | `triggering_actor.login` | 谁触发的 |

**改动文件**: `prefetch.py` (数据采集), `agents/errors.py` (prompt 更新)

### 1.2 故障自动分类

在 `prefetch.py` 中新增 `_classify_failures()` 函数，对每个失败 run 进行规则分类：

```
故障分类逻辑:

├── 同一 job 在相同 commit 上有成功也有失败？
│   └── Yes → Flaky Test
│
├── 日志包含 timeout/deadline/killed/OOM？
│   └── Yes → 平台/资源问题
│
├── 日志包含 npm ERR/pip install failed/resolution failed？
│   └── Yes → 依赖问题
│
├── 日志包含 secret not found/permission denied/auth？
│   └── Yes → 配置问题
│
├── 日志包含 FAIL/Error/AssertionError/exit code 1？
│   └── Yes → 代码错误
│
└── 无法判断 → Unknown (交给 Agent 分析)
```

**输出格式** — 新增 `failure_classifications.json`：

```json
{
  "run_id": 12345,
  "commit": "abc1234",
  "classification": "flaky_test",
  "confidence": 0.85,
  "evidence": "Job 'test-unit' failed on this run but passed on re-run with same commit",
  "failed_step": "Run tests",
  "error_snippet": "AssertionError: expected 3 but got 2"
}
```

**改动文件**: `prefetch.py`, 新增 `classifier.py`

### 1.3 更新 Error Analyst Prompt

给 error analyst 提供分类结果，让它在此基础上深入分析，而不是从头猜：

```
你会收到一份预分类的故障列表，每个失败已标记为:
- code_bug: 代码错误
- flaky_test: 不稳定测试
- platform_issue: 平台/资源问题
- dependency_issue: 依赖问题
- config_issue: 配置问题
- unknown: 待确认

你的任务是验证分类是否正确，深入分析根因，并给出具体修复建议。
```

**改动文件**: `agents/errors.py`

---

## Phase 2: 日志智能解析 + Flaky 检测 (1-2 周)

> 核心交付：按 step 展示错误详情，自动识别 flaky test

### 2.1 按 Step 拆分日志

当前取的是整个 run 的日志（2000 行），混在一起。改为用 per-job log API：

```
GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs
```

对每个失败 job 的日志按 step 拆分，提取每个 step 的：
- Exit code
- 最后 50 行 stderr
- 匹配到的错误模式 (stack trace / error message / timeout)

**输出** — 结构化错误摘要：

```json
{
  "job": "test-unit",
  "step": "Run tests",
  "exit_code": 1,
  "error_type": "test_failure",
  "error_summary": "3 tests failed in auth_test.go",
  "key_lines": [
    "FAIL: TestLoginWithExpiredToken (0.02s)",
    "expected: 401, got: 500",
    "auth_test.go:42"
  ]
}
```

**改动文件**: `github_client.py` (新增 `get_job_logs`), `prefetch.py`, 新增 `log_parser.py`

### 2.2 Flaky Test 检测算法

```
对每个 job name:
  取最近 N 次 run (N=20)
  按 commit SHA 分组:
    如果同一个 commit 下有 success 也有 failure → 标记为 flaky

  flakiness_score = flaky_count / total_count

  if flakiness_score > 0.1:
    标记该 job 为 flaky
    找出最近的 flaky 实例
```

**输出** — `flaky_report.json`：

```json
{
  "flaky_jobs": [
    {
      "job_name": "test-e2e",
      "flakiness_score": 0.25,
      "flaky_instances": [
        {"run_id": 123, "commit": "abc", "result": "failure"},
        {"run_id": 124, "commit": "abc", "result": "success"}
      ],
      "recommendation": "该测试在相同代码上随机失败，建议检查测试中的竞态条件或外部依赖"
    }
  ]
}
```

**改动文件**: 新增 `flaky_detector.py`, `prefetch.py`

### 2.3 错误模式库

预定义常见 CI 错误模式，用于快速分类：

```python
ERROR_PATTERNS = {
    "test_failure": [r"FAIL:", r"FAILED", r"AssertionError", r"expected .+ got"],
    "build_error": [r"BUILD FAILED", r"compilation error", r"syntax error"],
    "timeout": [r"timeout", r"deadline exceeded", r"killed", r"SIGTERM"],
    "oom": [r"out of memory", r"OOM", r"Cannot allocate memory"],
    "network": [r"connection refused", r"ETIMEDOUT", r"DNS resolution failed"],
    "dependency": [r"npm ERR!", r"pip install.*failed", r"Could not resolve"],
    "permission": [r"permission denied", r"403 Forbidden", r"secret.*not found"],
    "docker": [r"manifest unknown", r"pull access denied", r"image not found"],
    "rate_limit": [r"rate limit", r"API rate limit exceeded", r"429"],
}
```

**改动文件**: 新增 `error_patterns.py`

---

## Phase 3: 回归定位 + 失败时间线 (2-3 周)

> 核心交付：告诉用户「从哪个 commit 开始坏的」，展示失败趋势

### 3.1 Commit 回归定位

```
对于一个持续失败的 job:
  1. 找到最后一个成功 run 的 commit SHA (last_green)
  2. 找到第一个失败 run 的 commit SHA (first_red)
  3. 调用 GitHub Compare API: GET /repos/{owner}/{repo}/compare/{last_green}...{first_red}
  4. 列出中间的 commits 和 PR
  5. 输出: "回归由 PR #42 (commit abc123 by @user) 引入"
```

**新增 API 调用**：
- `GET /repos/{owner}/{repo}/compare/{base}...{head}` — 获取两个 commit 之间的变更
- `GET /repos/{owner}/{repo}/pulls/{number}` — 获取 PR 详情

**输出**：

```json
{
  "regression": {
    "job": "test-unit",
    "last_green_commit": "def456",
    "last_green_run": 120,
    "first_red_commit": "abc123",
    "first_red_run": 121,
    "suspected_commits": [
      {"sha": "abc123", "message": "feat: add auth middleware", "author": "user1", "pr": 42}
    ],
    "changed_files": ["src/auth.go", "src/auth_test.go"]
  }
}
```

**改动文件**: `github_client.py`, 新增 `regression_finder.py`, `agents/errors.py`

### 3.2 失败时间线

在报告中新增时间维度分析：

```
workflow: CI
  ├── 7 天前: 成功率 95%   ████████████████████░
  ├── 3 天前: 成功率 70%   ██████████████░░░░░░░  ← PR #42 合入
  ├── 1 天前: 成功率 40%   ████████░░░░░░░░░░░░░
  └── 今天:   成功率 40%   ████████░░░░░░░░░░░░░

  趋势: 3 天前开始恶化，与 feat/auth 分支合入时间吻合
```

**改动文件**: `prefetch.py` (按天聚合统计), `report/formatter.py`, 前端图表

### 3.3 前端报告增强

报告详情页新增：

```
┌─────────────────────────────────────────────────┐
│  Failure Diagnosis                               │
│                                                  │
│  ❌ test-unit 失败                               │
│  分类: 代码错误 (confidence: 92%)                │
│  引入: PR #42 "feat: add auth" by @user1         │
│  首次失败: 2024-06-01 (commit abc123)            │
│  失败 step: Run tests (exit code 1)              │
│  错误摘要:                                       │
│    FAIL: TestLoginWithExpiredToken               │
│    auth_test.go:42 — expected 401, got 500       │
│                                                  │
│  ⚠️ test-e2e: Flaky (25% flakiness)             │
│  最近 20 次 run 中 5 次随机失败                   │
│  建议: 检查 setup/teardown 中的竞态条件           │
└─────────────────────────────────────────────────┘
```

---

## Phase 4: 实时监控 + 主动告警 (Webhook)

> 核心交付：无需手动触发，CI 失败后自动分析并通知

详见 [Webhook 设计文档](./webhook-design.md)

### 4.1 Webhook 实时数据采集

- 接收 `workflow_run` + `workflow_job` 事件
- 实时写入 DB，计算 SLA 指标

### 4.2 SLA 仪表盘

Dashboard 新增 SLA 页面：

| 指标 | 计算方式 | 展示 |
|------|---------|------|
| MTTD | 失败 run `completed_at` → 用户查看报告的时间差 | 折线图 (过去 30 天) |
| MTTR | 首次失败 run → 下一次成功 run 的时间差 | 折线图 + 分布 |
| MTTC | 从失败到分类完成的时间 | 折线图 |
| 故障分类分布 | 代码/flaky/平台/依赖 各占比 | 饼图 |
| Flaky Job 数量 | flakiness_score > 0.1 的 job 数 | 数字 + 列表 |
| 成功率趋势 | 按天/周的整体成功率 | 面积图 |

### 4.3 主动通知

检测到以下情况时发送通知（Slack / 企业微信 / Webhook）：

| 触发条件 | 通知内容 |
|---------|---------|
| 连续 N 次失败 (N=3) | 「CI 连续 3 次失败，可能是回归」 |
| 成功率骤降 (>20pp) | 「CI 成功率从 95% 降到 60%，检查 test-unit」 |
| 新 flaky test 出现 | 「test-e2e 被检测为 flaky (25%)」 |
| 首次出现的错误类型 | 「新错误: OOM in build job」 |

### 4.4 自动修复建议

对于常见问题自动生成 fix：

| 问题类型 | 自动建议 |
|---------|---------|
| Flaky test | 生成 `@retry(3)` 装饰器或 `flaky` 标记 |
| 依赖问题 | 生成 lock file 更新命令 |
| 超时 | 建议调整 `timeout-minutes` 值 |
| 缓存失效 | 建议更新 cache key |

---

## Phase 5: 高级分析 (长期)

### 5.1 跨仓库分析

- 对一个 Org 下的所有仓库做统一分析
- 识别 Org 级别的共性问题（如同一个 Action 版本导致多仓库失败）

### 5.2 成本优化建议执行

- 不只建议，还能生成优化后的 workflow YAML
- 用户确认后自动提交 PR

### 5.3 CI 基准对比

- 与同类型开源项目对比 CI 表现
- 「你的 Go 项目 CI 耗时 p90 = 12min，同类项目中位数 = 8min」

### 5.4 AI 学习改进

- 收集用户对分析结果的反馈（有用/没用）
- 用于优化 Agent prompt 和分类规则

---

## 里程碑

| 版本 | Phase | 核心能力 | 预计时间 |
|------|-------|---------|---------|
| v0.1 | 当前 | 四维度分析 + 使用率统计 | 已完成 |
| v0.2 | Phase 1 | 故障分类 + 数据补全 | 1-2 周 |
| v0.3 | Phase 2 | 日志智能解析 + Flaky 检测 | 1-2 周 |
| v0.4 | Phase 3 | 回归定位 + 失败时间线 | 2-3 周 |
| v0.5 | Phase 4 | Webhook 实时监控 + 告警 | 2-3 周 |
| v1.0 | Phase 5 | 跨仓库 + 自动修复 + 基准对比 | 长期 |
