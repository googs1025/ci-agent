# GitHub Webhook 实时 CI 用量追踪 -- 技术设计文档

> 状态: 草案 | 作者: ci-agent 团队 | 日期: 2026-04-08

---

## 1. 架构概览

### 1.1 系统架构图

```
                         GitHub (Repo / Org)
                          |             |
              Webhook 推送 |             | REST API 拉取
          (workflow_run,   |             | (按需分析)
           workflow_job)   |             |
                           v             v
                  +------------------+------------------+
                  |           FastAPI 后端               |
                  |                                      |
                  |  POST /webhook/github   POST /api/analyze
                  |       |                      |      |
                  |  签名验证 + 去重          解析 + AI 分析
                  |       |                      |      |
                  |       v                      v      |
                  |  +----------+      +--------------+ |
                  |  | Webhook  |      | Analysis     | |
                  |  | 事件表   |      | Report 表    | |
                  |  +----------+      +--------------+ |
                  |       |                      |      |
                  |       v                      v      |
                  |  +---------------------------------+|
                  |  |        SQLite / PostgreSQL       ||
                  |  +---------------------------------+|
                  +-------------------------------------+
                                   |
                                   v
                  +-------------------------------------+
                  |        Next.js 前端 Dashboard        |
                  |                                      |
                  |  [用量概览]  [趋势图表]  [分析报告]  |
                  +-------------------------------------+
```

### 1.2 双数据通道

| 通道 | 触发方式 | 数据流向 | 用途 |
|------|---------|---------|------|
| **实时 Webhook** | GitHub 主动推送 | GitHub -> `/webhook/github` -> DB | 持续采集 CI 运行事件, 用于用量统计和趋势分析 |
| **按需分析** | 用户手动触发 | 用户 -> `/api/analyze` -> GitHub REST API -> AI -> DB | 深度分析 CI 配置问题, 生成优化建议 |

两个通道共享 `repositories` 表, Webhook 通道通过 `repo_id` 外键关联到已有仓库记录. 若 Webhook 事件来自尚未记录的仓库, 自动创建记录.

---

## 2. GitHub Webhook 事件订阅

### 2.1 需要订阅的事件

#### `workflow_run` 事件

追踪整个 Workflow 的生命周期.

| Action | 触发时机 | 关键字段 |
|--------|---------|---------|
| `requested` | Workflow 被触发 | `id`, `name`, `head_branch`, `event`, `run_attempt` |
| `in_progress` | Workflow 开始执行 | `id`, `status`, `run_started_at` |
| `completed` | Workflow 执行完毕 | `id`, `status`, `conclusion`, `run_started_at`, `updated_at` |

核心 payload 字段:

```json
{
  "action": "completed",
  "workflow_run": {
    "id": 123456789,
    "name": "CI",
    "head_branch": "main",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "run_attempt": 1,
    "run_started_at": "2026-04-08T10:00:00Z",
    "updated_at": "2026-04-08T10:05:30Z",
    "repository": { "id": 1, "full_name": "owner/repo" }
  }
}
```

#### `workflow_job` 事件

追踪单个 Job 的生命周期, 包括排队时间和 Runner 信息.

| Action | 触发时机 | 关键字段 |
|--------|---------|---------|
| `queued` | Job 进入排队 | `id`, `run_id`, `name`, `created_at`, `labels` |
| `in_progress` | Job 被 Runner 拾取 | `id`, `started_at`, `runner_name`, `labels` |
| `completed` | Job 执行完毕 | `id`, `conclusion`, `completed_at`, `steps[]` |

核心 payload 字段:

```json
{
  "action": "completed",
  "workflow_job": {
    "id": 987654321,
    "run_id": 123456789,
    "name": "build",
    "status": "completed",
    "conclusion": "success",
    "created_at": "2026-04-08T10:00:00Z",
    "started_at": "2026-04-08T10:00:12Z",
    "completed_at": "2026-04-08T10:03:45Z",
    "labels": ["ubuntu-latest"],
    "runner_name": "GitHub Actions 2",
    "steps": [
      {
        "name": "Checkout",
        "number": 1,
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-04-08T10:00:15Z",
        "completed_at": "2026-04-08T10:00:18Z"
      }
    ]
  }
}
```

### 2.2 为什么需要两个事件

- `workflow_run` 提供 Workflow 粒度的全局视图 (触发类型、分支、总耗时), 但不包含 Job 级别的排队时间和 Runner 信息.
- `workflow_job` 提供 Job 粒度的执行细节 (排队等待、Runner 标签、Step 明细), 但不包含 Workflow 触发上下文.
- 两者通过 `run_id` 关联, 组合后才能构建完整的 CI 执行画像.

---

## 3. 新增数据模型

以下三张表新增至 `ci_optimizer/db/models.py`, 与现有 `Base` 共享同一个 metadata.

### 3.1 表结构

#### WorkflowRunEvent

```python
class WorkflowRunEvent(Base):
    __tablename__ = "workflow_run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(index=True, unique=True)   # GitHub run ID
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    workflow_name: Mapped[str]
    status: Mapped[str]              # requested / in_progress / completed
    conclusion: Mapped[str | None]   # success / failure / cancelled / skipped
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    head_branch: Mapped[str | None]
    trigger_event: Mapped[str | None]  # push / pull_request / schedule / ...
    run_attempt: Mapped[int] = mapped_column(default=1)
    delivery_id: Mapped[str | None] = mapped_column(unique=True)  # 幂等去重
    received_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    repository: Mapped["Repository"] = relationship()
    jobs: Mapped[list["JobEvent"]] = relationship(back_populates="workflow_run")
```

#### JobEvent

```python
class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(index=True, unique=True)   # GitHub job ID
    run_id: Mapped[int] = mapped_column(index=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    job_name: Mapped[str]
    status: Mapped[str]
    conclusion: Mapped[str | None]
    runner_labels: Mapped[str | None]  # JSON 数组, 如 '["ubuntu-latest"]'
    created_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    queue_duration_ms: Mapped[int | None]      # 计算字段: started_at - created_at
    execution_duration_ms: Mapped[int | None]  # 计算字段: completed_at - started_at
    delivery_id: Mapped[str | None] = mapped_column(unique=True)
    received_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc)
    )

    repository: Mapped["Repository"] = relationship()
    workflow_run: Mapped["WorkflowRunEvent"] = relationship(
        back_populates="jobs", foreign_keys=[run_id],
        primaryjoin="JobEvent.run_id == WorkflowRunEvent.run_id",
    )
    steps: Mapped[list["StepEvent"]] = relationship(back_populates="job")
```

#### StepEvent

```python
class StepEvent(Base):
    __tablename__ = "step_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[str] = mapped_column(index=True)  # "{job_id}_{step_number}"
    job_id: Mapped[int] = mapped_column(ForeignKey("job_events.job_id"), index=True)
    step_name: Mapped[str]
    status: Mapped[str]
    conclusion: Mapped[str | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    step_number: Mapped[int]

    job: Mapped["JobEvent"] = relationship(back_populates="steps")
```

### 3.2 ER 关系

```
repositories 1---* workflow_run_events 1---* job_events 1---* step_events
     |
     +---* analysis_reports 1---* findings  (现有表, 不变)
```

### 3.3 索引策略

| 表 | 索引 | 用途 |
|----|------|------|
| `workflow_run_events` | `run_id` (unique) | 按 GitHub run ID 查询/去重 |
| `workflow_run_events` | `repo_id` | 按仓库筛选 |
| `job_events` | `job_id` (unique) | 按 GitHub job ID 查询/去重 |
| `job_events` | `run_id` | 关联 workflow_run |
| `job_events` | `repo_id` | 按仓库筛选 |
| `step_events` | `job_id` | 关联 job |

---

## 4. API 设计

### 4.1 Webhook 接收端点

```
POST /webhook/github
```

此端点不挂载在 `/api` 前缀下, 与现有 API 路由分离.

**请求头:**

| Header | 说明 |
|--------|------|
| `X-Hub-Signature-256` | HMAC SHA-256 签名 |
| `X-GitHub-Event` | 事件类型 (`workflow_run` / `workflow_job`) |
| `X-GitHub-Delivery` | 唯一投递 ID, 用于幂等处理 |

**处理流程:**

```python
@webhook_router.post("/webhook/github", status_code=202)
async def receive_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # 1. 读取原始 body
    body = await request.body()

    # 2. 验证 HMAC 签名
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, signature, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 3. 检查 delivery ID 防重放
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if await is_duplicate(db, delivery_id):
        return {"status": "duplicate", "delivery_id": delivery_id}

    # 4. 按事件类型分发处理
    event_type = request.headers.get("X-GitHub-Event")
    payload = await request.json()

    if event_type == "workflow_run":
        await handle_workflow_run(db, payload, delivery_id)
    elif event_type == "workflow_job":
        await handle_workflow_job(db, payload, delivery_id)

    return {"status": "accepted", "delivery_id": delivery_id}
```

**签名验证函数:**

```python
import hashlib
import hmac

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

### 4.2 用量查询 API

所有查询 API 挂载在 `/api/usage` 下, 支持如下公共查询参数:

| 参数 | 类型 | 说明 |
|------|------|------|
| `repo` | `str` (可选) | 仓库全名, 如 `owner/repo` |
| `since` | `datetime` (可选) | 起始时间 |
| `until` | `datetime` (可选) | 结束时间 |

#### GET `/api/usage/summary`

返回聚合统计.

```json
{
  "total_runs": 1234,
  "total_jobs": 5678,
  "total_execution_minutes": 45230,
  "estimated_billing_minutes": 52100,
  "success_rate": 0.87,
  "avg_duration_seconds": 245,
  "avg_queue_seconds": 12
}
```

#### GET `/api/usage/trends`

返回时间序列数据, 额外参数: `interval` (`day` | `week`, 默认 `day`).

```json
{
  "interval": "day",
  "data": [
    {
      "date": "2026-04-01",
      "run_count": 42,
      "avg_duration_seconds": 230,
      "failure_rate": 0.12,
      "total_minutes": 1050
    }
  ]
}
```

#### GET `/api/usage/runners`

返回 Runner 类型分布.

```json
{
  "distribution": [
    { "labels": "ubuntu-latest",  "job_count": 3500, "total_minutes": 28000 },
    { "labels": "macos-latest",   "job_count": 800,  "total_minutes": 12000 },
    { "labels": "windows-latest", "job_count": 400,  "total_minutes": 8000 }
  ]
}
```

#### GET `/api/usage/queue-times`

返回排队等待分析.

```json
{
  "avg_queue_ms": 12300,
  "p50_queue_ms": 8000,
  "p90_queue_ms": 35000,
  "p99_queue_ms": 120000,
  "by_runner": [
    { "labels": "ubuntu-latest", "avg_queue_ms": 8500 },
    { "labels": "macos-latest",  "avg_queue_ms": 45000 }
  ]
}
```

---

## 5. 可计算指标

以下指标均可从 Webhook 采集的数据中衍生计算:

| 指标 | 计算方法 | 价值 |
|------|---------|------|
| **平均 Job 执行时间** | `AVG(execution_duration_ms) GROUP BY workflow_name, job_name` | 识别耗时 Job, 指导优化 |
| **排队等待时间** | `started_at - created_at` (JobEvent) | 发现 Runner 容量瓶颈 |
| **成功/失败率趋势** | `COUNT(conclusion='failure') / COUNT(*) GROUP BY date` | 监控 CI 健康度 |
| **Runner 类型分布** | `COUNT(*) GROUP BY runner_labels` | 成本分析 (macOS 10x 计费) |
| **预估计费分钟数** | `duration * multiplier` (Linux=1x, macOS=10x, Windows=2x) | 成本预测 |
| **峰值并发** | 统计任意时间窗口内同时 `in_progress` 的 Job 数 | 容量规划 |
| **Flaky Job 检测** | 同一 Job 在近 N 次运行中交替 pass/fail | 提升 CI 可靠性 |
| **最慢 Step 排行** | `AVG(completed_at - started_at) GROUP BY step_name ORDER BY DESC` | 精准定位瓶颈 |

### 5.1 计费倍率参考

```python
RUNNER_MULTIPLIERS = {
    "ubuntu":  1,
    "linux":   1,
    "macos":   10,
    "windows": 2,
}

def estimate_billing_minutes(duration_minutes: float, labels: list[str]) -> float:
    for label in labels:
        label_lower = label.lower()
        for runner_type, multiplier in RUNNER_MULTIPLIERS.items():
            if runner_type in label_lower:
                return duration_minutes * multiplier
    return duration_minutes  # 默认 1x
```

---

## 6. Webhook 安全机制

### 6.1 HMAC SHA-256 签名验证

每个 Webhook 请求都携带 `X-Hub-Signature-256` 头, 值为 `sha256=<hex_digest>`. 服务端使用预共享的 Webhook Secret 重新计算签名并比对.

**要点:**
- 使用 `hmac.compare_digest()` 进行常量时间比较, 防止时序攻击.
- Webhook Secret 通过环境变量 `WEBHOOK_SECRET` 配置, 禁止硬编码.

### 6.2 重放攻击防护

GitHub 不提供 Webhook 时间戳头, 但可通过以下方式缓解:

- 使用 `X-GitHub-Delivery` ID 做幂等校验 -- 若该 ID 已在数据库中存在, 直接返回 202 不重复处理.
- `delivery_id` 在 `WorkflowRunEvent` 和 `JobEvent` 表中设为 UNIQUE 约束.

### 6.3 幂等事件处理

```python
async def is_duplicate(db: AsyncSession, delivery_id: str) -> bool:
    """检查 delivery_id 是否已处理过."""
    run_exists = await db.scalar(
        select(func.count()).where(
            WorkflowRunEvent.delivery_id == delivery_id
        )
    )
    job_exists = await db.scalar(
        select(func.count()).where(
            JobEvent.delivery_id == delivery_id
        )
    )
    return (run_exists or 0) > 0 or (job_exists or 0) > 0
```

对于同一 `run_id` / `job_id` 的多次状态更新 (如 `queued` -> `in_progress` -> `completed`), 使用 **UPSERT** 策略: 按 `run_id` 或 `job_id` 查找已有记录, 存在则更新字段, 不存在则插入.

---

## 7. 实施阶段

### Phase 1: Webhook 接收 + 存储 (1-2 周)

- [ ] 新增三张数据表, 执行 `alembic` 迁移 (或依赖 `create_all`)
- [ ] 实现 `POST /webhook/github` 端点
- [ ] 实现 HMAC 签名验证
- [ ] 实现 `workflow_run` 和 `workflow_job` 事件处理器
- [ ] 实现 delivery ID 幂等去重
- [ ] 编写单元测试 (mock webhook payload)

**交付物:** Webhook 能接收事件并存入数据库, 可通过 GitHub 的 "Recent Deliveries" 页面确认 202 响应.

### Phase 2: 用量 API + 聚合查询 (1-2 周)

- [ ] 实现 `/api/usage/summary` 端点
- [ ] 实现 `/api/usage/trends` 端点 (支持按天/周聚合)
- [ ] 实现 `/api/usage/runners` 端点
- [ ] 实现 `/api/usage/queue-times` 端点 (含百分位数计算)
- [ ] 添加查询参数过滤 (repo, since, until)
- [ ] 编写集成测试

**交付物:** 可通过 API 查询 CI 用量统计和趋势数据.

### Phase 3: Dashboard 集成 (1-2 周)

- [ ] 新增 "CI 用量" 页面 (Next.js)
- [ ] 用量概览卡片 (总运行数、总分钟数、成功率)
- [ ] 趋势折线图 (每日运行数、平均耗时、失败率)
- [ ] Runner 分布饼图
- [ ] 排队时间分布直方图
- [ ] 最慢 Step 排行表

**交付物:** 前端 Dashboard 展示实时 CI 用量数据.

### Phase 4: 告警 (可选, 1 周)

- [ ] 失败率飙升告警 (如最近 1 小时失败率 > 30%)
- [ ] 排队时间异常告警 (如 P90 > 5 分钟)
- [ ] 支持 Slack / 邮件 / Webhook 通知通道

---

## 8. 局限性与权衡

| 问题 | 影响 | 缓解方案 |
|------|------|---------|
| **Webhook 投递不保证** | 少量事件可能丢失, 统计数据存在微小误差 | GitHub 会自动重试失败投递; 可定期用 REST API 做对账补漏 |
| **无历史回填** | 只能采集配置 Webhook 之后的数据 | Phase 2 可加一个 "历史导入" 脚本, 用 REST API 拉取最近 N 天的 workflow runs |
| **SQLite 并发写入** | 高频 Webhook 事件可能导致写锁竞争 | 开发/小团队场景可用 WAL 模式缓解; 生产环境建议迁移 PostgreSQL |
| **事件顺序不保证** | `completed` 可能先于 `in_progress` 到达 | UPSERT 策略兼容乱序: 以最新状态覆盖, 各时间戳字段独立更新 |
| **大型 Org 事件量** | 活跃 Org 每天可能产生数万事件 | 考虑异步队列 (如 Redis + Celery) 解耦接收与处理 |

### 8.1 SQLite vs PostgreSQL

当前项目使用 SQLite (`~/.ci-agent/data.db`). 对于 Webhook 场景的建议:

| 场景 | 推荐 |
|------|------|
| 个人项目 / 小团队 (< 50 次/天) | SQLite + WAL 模式足够 |
| 中型团队 (50-500 次/天) | SQLite 可用但需监控锁等待 |
| 大型 Org / 生产部署 (> 500 次/天) | 迁移 PostgreSQL |

SQLAlchemy 的抽象层使得切换数据库引擎只需修改 `database.py` 中的连接字符串:

```python
# SQLite (当前)
engine = create_async_engine("sqlite+aiosqlite:///~/.ci-agent/data.db")

# PostgreSQL (生产推荐)
engine = create_async_engine("postgresql+asyncpg://user:pass@host/ci_agent")
```

---

## 9. 配置指南

### 9.1 在 GitHub 配置 Webhook

**仓库级别:**

1. 进入仓库 Settings -> Webhooks -> Add webhook
2. 填写:
   - **Payload URL:** `https://your-server.com/webhook/github`
   - **Content type:** `application/json`
   - **Secret:** 填入与服务端一致的 Webhook Secret
3. 在 "Which events would you like to trigger this webhook?" 中选择 "Let me select individual events"
4. 勾选:
   - `Workflow runs`
   - `Workflow jobs`
5. 保存

**组织级别:**

进入 Organization Settings -> Webhooks, 步骤同上. 组织级 Webhook 会接收该组织下所有仓库的事件.

### 9.2 服务端环境变量

```bash
# .env 或系统环境变量
WEBHOOK_SECRET=your-random-secret-string   # 必须, 与 GitHub 端一致
```

生成安全密钥:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 9.3 验证配置

配置完成后, GitHub 会立即发送一个 `ping` 事件. 确认:

1. GitHub Webhook 页面显示最近投递为绿色勾 (HTTP 202)
2. 服务端日志输出收到 `ping` 事件
3. 触发一次 CI 运行, 确认 `workflow_run` 和 `workflow_job` 事件正确入库

```bash
# 查看已入库的事件数
sqlite3 ~/.ci-agent/data.db "SELECT COUNT(*) FROM workflow_run_events;"
sqlite3 ~/.ci-agent/data.db "SELECT COUNT(*) FROM job_events;"
```

---

## 10. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/ci_optimizer/db/models.py` | 修改 | 新增 `WorkflowRunEvent`, `JobEvent`, `StepEvent` 模型 |
| `src/ci_optimizer/api/webhook.py` | 新增 | Webhook 接收端点、签名验证、事件处理 |
| `src/ci_optimizer/api/usage.py` | 新增 | 用量查询 API 路由 |
| `src/ci_optimizer/api/app.py` | 修改 | 注册 webhook_router 和 usage_router |
| `src/ci_optimizer/db/crud.py` | 修改 | 新增 Webhook 事件 CRUD 和聚合查询函数 |
| `src/ci_optimizer/api/schemas.py` | 修改 | 新增 usage 相关响应模型 |
| `tests/test_webhook.py` | 新增 | Webhook 端点单元测试 |
| `tests/test_usage_api.py` | 新增 | 用量 API 集成测试 |
