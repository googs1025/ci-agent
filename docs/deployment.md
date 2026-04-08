# CI Agent 部署文档

## 架构概览

```
                          ┌──────────────────────────────────────────────┐
                          │              Kubernetes Cluster               │
                          │                                              │
   User ──── Ingress ─────┤  ci-agent.example.com                        │
              (nginx)     │                                              │
                │         │  ┌─────────────────┐  ┌───────────────────┐  │
                │         │  │    Frontend      │  │     Backend       │  │
             /api/* ──────┼──┤  Next.js :3000   │  │  FastAPI :8000    │  │
                │         │  │  (2 replicas)    │  │  (1 replica*)     │  │
              /* ─────────┼──┤  Static + SSR    │  │  Agent Engine     │  │
                          │  │                  │  │  REST API         │  │
                          │  └─────────────────┘  └──────┬────────────┘  │
                          │                              │               │
                          │                     ┌────────▼──────────┐    │
                          │                     │   PVC (1Gi)       │    │
                          │                     │ ├─ data.db        │    │
                          │                     │ └─ config.json    │    │
                          │                     └───────────────────┘    │
                          │                              │               │
                          └──────────────────────────────┼───────────────┘
                                                         │
                                              External APIs
                                        ┌────────────────┼────────────┐
                                        │                │            │
                                   Anthropic API    GitHub API    Git Clone
                                  (Claude Agent)   (Run History)  (Repo Files)
```

*Backend 限制 1 replica，因为使用 SQLite（不支持多写并发）。如需多副本，需替换为 PostgreSQL。

## 组件说明

| 组件 | 镜像 | 端口 | 副本 | 存储 |
|------|------|------|------|------|
| Backend (FastAPI) | `ci-agent-backend` | 8000 | 1 | PVC: SQLite + Config |
| Frontend (Next.js) | `ci-agent-frontend` | 3000 | 2 | 无状态 |
| Ingress (nginx) | - | 80/443 | - | - |

## 前置条件

- Kubernetes 1.24+
- kubectl 配置好 kubeconfig
- 容器镜像仓库（Docker Hub / Harbor / ACR 等）
- Ingress Controller（nginx-ingress 推荐）
- Anthropic API Key

---

## 1. Docker 本地测试

### 构建镜像

```bash
# 构建后端
docker build -f Dockerfile.backend -t ci-agent-backend:latest .

# 构建前端
docker build -f Dockerfile.frontend -t ci-agent-frontend:latest .
```

### Docker Compose 启动

```bash
# 配置 .env
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY 和 GITHUB_TOKEN

# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 访问
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000/docs
```

---

## 2. Kubernetes 部署

### 2.1 推送镜像到仓库

```bash
# 替换 REGISTRY 为你的镜像仓库地址
REGISTRY=your-registry.com/ci-agent

docker build -f Dockerfile.backend -t $REGISTRY/backend:v0.1.0 .
docker build -f Dockerfile.frontend -t $REGISTRY/frontend:v0.1.0 .

docker push $REGISTRY/backend:v0.1.0
docker push $REGISTRY/frontend:v0.1.0
```

### 2.2 修改配置

部署前需修改以下文件：

**`deploy/k8s/secret.yaml`** — 填入真实的 API Key：

```yaml
stringData:
  ANTHROPIC_API_KEY: "sk-ant-your-real-key"
  GITHUB_TOKEN: "ghp_your-real-token"
```

> 生产环境建议使用 External Secrets Operator 或 Sealed Secrets 管理敏感信息。

**`deploy/k8s/configmap.yaml`** — 按需调整模型和 CORS：

```yaml
data:
  CI_AGENT_MODEL: "claude-sonnet-4-20250514"
  CORS_ORIGINS: "https://ci-agent.example.com"
```

**`deploy/k8s/backend.yaml` / `frontend.yaml`** — 替换镜像地址：

```yaml
image: your-registry.com/ci-agent/backend:v0.1.0
image: your-registry.com/ci-agent/frontend:v0.1.0
```

**`deploy/k8s/ingress.yaml`** — 替换域名：

```yaml
rules:
  - host: ci-agent.your-domain.com
```

### 2.3 部署

```bash
# 方式一：使用 kustomize
kubectl apply -k deploy/k8s/

# 方式二：逐个 apply
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/backend.yaml
kubectl apply -f deploy/k8s/frontend.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

### 2.4 验证

```bash
# 查看 Pod 状态
kubectl -n ci-agent get pods

# 查看日志
kubectl -n ci-agent logs -f deployment/ci-agent-backend
kubectl -n ci-agent logs -f deployment/ci-agent-frontend

# 测试 API
kubectl -n ci-agent port-forward svc/ci-agent-backend 8000:8000
curl http://localhost:8000/api/config
curl http://localhost:8000/api/dashboard
```

---

## 3. 配置管理

### 环境变量

| 变量 | 所属组件 | 说明 | 必填 |
|------|---------|------|------|
| `ANTHROPIC_API_KEY` | Backend | Claude API Key | Yes |
| `GITHUB_TOKEN` | Backend | GitHub Token（获取 CI 运行历史） | Recommended |
| `CI_AGENT_MODEL` | Backend | 使用的模型 | No (default: claude-sonnet-4-20250514) |
| `CORS_ORIGINS` | Backend | 允许的前端域名（逗号分隔） | No (default: http://localhost:3000) |
| `NEXT_PUBLIC_API_URL` | Frontend | 后端 API 地址 | No (K8s 内部: http://ci-agent-backend:8000) |

### 运行时配置

部署后可通过 API 动态修改配置（无需重启）：

```bash
# 切换模型
curl -X PUT https://ci-agent.example.com/api/config \
  -H "Content-Type: application/json" \
  -d '{"model": "claude-opus-4-20250514"}'

# 查看当前配置
curl https://ci-agent.example.com/api/config
```

---

## 4. 存储与持久化

### SQLite (当前方案)

- 数据存储在 PVC 的 `data.db` 文件中
- **限制**：Backend 只能 1 个副本（SQLite 不支持并发写入）
- 适合：小团队 / 个人使用 / 概念验证

### 升级到 PostgreSQL (生产推荐)

如需多副本 Backend 或更高可靠性，替换为 PostgreSQL：

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Backend x3  │────▶│  PostgreSQL  │◀────│  Backend x3  │
│  (replicas)  │     │  (StatefulSet│     │  (replicas)  │
└──────────────┘     │   or RDS)    │     └──────────────┘
                     └──────────────┘
```

需修改：
1. `db/database.py`: 将连接字符串改为 `postgresql+asyncpg://...`
2. `pyproject.toml`: 添加 `asyncpg` 依赖
3. `backend.yaml`: replicas 可设为 2+，strategy 改为 RollingUpdate
4. 添加 PostgreSQL StatefulSet 或使用云托管 RDS

---

## 5. 扩展与高可用

### 当前架构限制

```
Frontend (x2) ─── Backend (x1) ─── SQLite (file)
     ✓ 可扩展        ✗ 单点         ✗ 单文件
```

### 生产架构建议

```
                    ┌─────────────┐
                    │   Ingress   │
                    │  (nginx/ALB)│
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │Frontend  │ │Frontend  │ │Frontend  │
        │ (x2-3)  │ │ (x2-3)  │ │ (x2-3)  │
        └──────────┘ └──────────┘ └──────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Backend  │ │ Backend  │ │ Backend  │
        │  (x2-3)  │ │  (x2-3)  │ │  (x2-3)  │
        └──────────┘ └──────────┘ └──────────┘
                           │
                    ┌──────▼──────┐
                    │ PostgreSQL  │
                    │ (HA / RDS)  │
                    └─────────────┘
```

### HPA (可选)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ci-agent-frontend-hpa
  namespace: ci-agent
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ci-agent-frontend
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## 6. 安全建议

1. **Secrets 管理**：生产环境不要直接在 YAML 中明文存放 API Key，使用：
   - [External Secrets Operator](https://external-secrets.io/)
   - [Sealed Secrets](https://sealed-secrets.netlify.app/)
   - 云厂商 KMS (AWS Secrets Manager / GCP Secret Manager)

2. **网络策略**：限制 Backend 的出站流量仅允许 Anthropic API 和 GitHub API

3. **TLS**：通过 cert-manager 自动签发证书

4. **RBAC**：为 ci-agent namespace 创建独立 ServiceAccount

5. **镜像安全**：使用私有镜像仓库 + 镜像扫描

---

## 7. 快速命令参考

```bash
# 部署
kubectl apply -k deploy/k8s/

# 查看状态
kubectl -n ci-agent get all

# 查看后端日志
kubectl -n ci-agent logs -f deploy/ci-agent-backend

# 更新镜像
kubectl -n ci-agent set image deploy/ci-agent-backend backend=$REGISTRY/backend:v0.2.0
kubectl -n ci-agent set image deploy/ci-agent-frontend frontend=$REGISTRY/frontend:v0.2.0

# 更新配置
kubectl -n ci-agent edit configmap ci-agent-config
kubectl -n ci-agent rollout restart deploy/ci-agent-backend

# 更新 Secret
kubectl -n ci-agent edit secret ci-agent-secrets
kubectl -n ci-agent rollout restart deploy/ci-agent-backend

# 卸载
kubectl delete -k deploy/k8s/
```
