# Langfuse LLM 可观测性配置指南

CI Agent 集成了 [Langfuse](https://langfuse.com)，提供完整的 LLM 调用可观测性，包括 Token 用量、成本追踪、延迟分析和请求/响应内容查看。

## 概览

Langfuse 追踪为**可选功能**，**不影响现有行为**。未配置时自动静默禁用，对性能零影响。

支持两种部署模式：

| 模式 | 优点 | 缺点 |
|------|------|------|
| **Langfuse Cloud** | 无需自行部署，有免费套餐 | 数据存储在 Langfuse 服务器 |
| **自托管** | 数据完全私有，无外部依赖 | 需要 PostgreSQL + Langfuse 容器 |

---

## 方案 1：Langfuse Cloud（推荐快速上手）

### 第一步：创建账号

1. 访问 [https://cloud.langfuse.com](https://cloud.langfuse.com)
2. 注册并创建一个新 **Project**

### 第二步：获取 API Keys

1. 进入项目，点击 **Settings** → **API Keys**
2. 复制 **Public Key** 和 **Secret Key**

### 第三步：配置环境变量

在 `.env` 文件中添加：

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
LANGFUSE_HOST=https://us.cloud.langfuse.com   # 美国区域
# LANGFUSE_HOST=https://cloud.langfuse.com    # 欧洲区域
```

### 第四步：重启 CI Agent

```bash
# 本地开发
uv run uvicorn ci_optimizer.api.app:app --port 8000

# Docker Compose
docker compose restart backend
```

日志中应出现：

```
Langfuse tracing enabled (host=https://us.cloud.langfuse.com)
```

---

## 方案 2：自托管（推荐生产环境）

### Docker Compose

创建 `docker-compose.langfuse.yaml`：

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

Langfuse K8s 清单文件位于 `deploy/k8s/langfuse.yaml`，部署步骤如下：

1. **编辑密钥** — 修改 `deploy/k8s/langfuse.yaml` 中的以下字段：
   ```yaml
   stringData:
     POSTGRES_PASSWORD: "your-strong-password"    # 必须修改
     NEXTAUTH_SECRET: "your-random-secret"         # 必须修改
     SALT: "your-random-salt"                       # 必须修改
   ```

2. **应用清单**：
   ```bash
   kubectl apply -k deploy/k8s/
   ```

3. **访问 Langfuse UI**：
   ```bash
   kubectl -n ci-agent port-forward svc/langfuse 3002:3000
   # 打开 http://localhost:3002
   ```

4. **在 Langfuse UI 中注册账号并创建项目**

5. **从项目设置中复制 API Keys**

6. **配置 CI Agent 使用自托管 Langfuse**：

   本地开发（`.env`）：
   ```bash
   LANGFUSE_PUBLIC_KEY=pk-lf-your-key
   LANGFUSE_SECRET_KEY=sk-lf-your-key
   LANGFUSE_HOST=http://localhost:3002
   ```

   K8s（已在 `configmap.yaml` 中预配置）：
   ```yaml
   LANGFUSE_HOST: "http://langfuse:3000"   # 集群内 Service URL
   ```

   在 `secret.yaml` 中更新 API Keys：
   ```yaml
   LANGFUSE_PUBLIC_KEY: "pk-lf-your-key"
   LANGFUSE_SECRET_KEY: "sk-lf-your-key"
   ```

---

## 追踪内容

配置完成后，以下 LLM 调用将被自动追踪：

### OpenAI 引擎
| 调用 | 捕获数据 |
|------|---------|
| 专家调用（并行） | 每个技能的 Prompt、响应、Token 数、成本、延迟 |
| 综合调用 | 合并后的 Prompt、最终报告、Token 数、成本 |

### Anthropic 引擎（Claude Agent SDK）
| 调用 | 捕获数据 |
|------|---------|
| 多 Agent 编排 | 总成本、总耗时、Session ID |

### 追踪结构

```
ci-analysis（根追踪）
├── anthropic-analysis          # 使用 Anthropic provider 时
│   └── Claude Agent SDK 调用  # 通过装饰器自动追踪
└── openai-analysis             # 使用 OpenAI provider 时
    ├── specialist: efficiency   # 并行
    ├── specialist: security     # 并行
    ├── specialist: cost         # 并行
    ├── specialist: errors       # 并行
    └── synthesis                # 最终合并
```

---

## 使用 Langfuse Dashboard

### Traces 视图

在左侧边栏点击 **Traces** 查看所有分析运行：

- **Name**：`ci-analysis` — 每次分析对应一个 Trace
- **Latency**：从开始到结束的总耗时
- **Cost**：所有 LLM 调用的总 USD 成本
- **Tokens**：输入/输出 Token 明细

点击 Trace 可查看完整的调用树和嵌套 Span。

### Generations 视图

在左侧边栏点击 **Generations** 查看单个 LLM 调用：

- 完整的 **Prompt** 内容（system + user 消息）
- 完整的 **响应** 内容
- **模型** 名称及参数（temperature 等）
- **Token 用量**（输入/输出/总计）
- 每次调用的 **成本**

### Dashboard

**Dashboard** 标签页展示聚合指标：

- 随时间变化的总成本
- Token 用量趋势
- 延迟百分位（p50、p90、p99）
- 模型使用分布
- 错误率

---

## 禁用追踪

如需禁用 Langfuse 追踪，删除或取消设置以下环境变量即可：

```bash
# 从 .env 中删除
# LANGFUSE_PUBLIC_KEY=
# LANGFUSE_SECRET_KEY=
# LANGFUSE_HOST=
```

对于 K8s，在 Secret 中设置空值：

```yaml
LANGFUSE_PUBLIC_KEY: ""
LANGFUSE_SECRET_KEY: ""
```

无需修改代码。追踪模块会检测缺失的 Key 并自动禁用。

---

## 故障排查

### 日志中出现 "Langfuse not configured"
- 确认 `LANGFUSE_PUBLIC_KEY` 和 `LANGFUSE_SECRET_KEY` 均已设置
- 确认 `.env` 文件位于项目根目录

### Dashboard 中不出现 Trace
- 等待 10–30 秒 — 事件是异步批量发送的
- 检查后端日志中是否有 `Langfuse tracing enabled` 消息
- 确认 `LANGFUSE_HOST` 指向正确的 URL

### 自托管："Connection refused"
- 确保 PostgreSQL 在 Langfuse 启动前已运行并处于健康状态
- 检查 `DATABASE_URL` 格式：`postgresql://user:pass@host:5432/dbname`
- 对于 K8s：确认 `langfuse-postgres` Service 正在运行

### 自托管：Langfuse UI 无法加载
- 在 Langfuse 容器环境中设置 `HOSTNAME=0.0.0.0`
- 使用 `langfuse/langfuse:2` 镜像（v3 需要 ClickHouse）
