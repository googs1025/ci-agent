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
              /* ─────────┼──┤  SSR + rewrites  │  │  Agent Engine     │  │
                          │  │                  │  │  REST API         │  │
                          │  └─────────────────┘  └──────┬────────────┘  │
                          │                              │               │
                          │                     ┌────────▼──────────┐    │
                          │                     │   PVC (1Gi)       │    │
                          │                     │ ├─ data.db        │    │
                          │                     │ └─ config.json    │    │
                          │                     └───────────────────┘    │
                          └──────────────────────────────────────────────┘
                                                         │
                                              External APIs
                                        ┌────────────────┼────────────┐
                                        │                │            │
                                   Anthropic API    GitHub API    Git Clone
```

*Backend 限制 1 replica，SQLite 不支持多写并发。如需多副本，替换为 PostgreSQL。

---

## 方案一：Docker Compose（本地/单机）

最简单的部署方式，适合本地体验和单机生产。

### 步骤

```bash
# 1. 克隆项目
git clone https://github.com/googs1025/ci-agent.git
cd ci-agent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入：
#   ANTHROPIC_API_KEY=sk-ant-...   (或 OPENAI_API_KEY)
#   GITHUB_TOKEN=ghp_...

# 3. 构建并启动（首次约 3-5 分钟）
docker compose up -d --build

# 4. 查看启动状态（等待 backend healthy）
docker compose ps

# 5. 查看日志
docker compose logs -f backend
```

**访问地址：**
- Web UI：http://localhost:3000
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

### 常用命令

```bash
# 停止
docker compose down

# 停止并删除数据（慎用）
docker compose down -v

# 更新代码后重新构建
docker compose up -d --build

# 查看实时日志
docker compose logs -f

# 进入 backend 容器调试
docker compose exec backend bash
```

### 数据持久化

分析数据存储在 Docker volume `ci-agent-data` 中：
```bash
# 查看 volume 位置
docker volume inspect ci-agent_ci-agent-data

# 备份数据库
docker compose exec backend sqlite3 /data/.ci-agent/data.db .dump > backup.sql
```

---

## 方案二：Kubernetes（生产）

### 前置条件

- Kubernetes 1.24+
- `kubectl` 已配置 kubeconfig
- 容器镜像仓库（Docker Hub / Harbor / ACR 等）
- Ingress Controller（推荐 nginx-ingress）

### 步骤一：构建并推送镜像

```bash
# 替换为你的镜像仓库地址
REGISTRY=your-registry.com/ci-agent
VERSION=v0.1.0

docker build -f Dockerfile.backend -t $REGISTRY/backend:$VERSION .

# ⚠️ frontend 必须在构建时传入 NEXT_PUBLIC_API_URL
# Next.js 的 /api/* rewrite 目标地址在 build 时 bake 进镜像，运行时不可更改
docker build -f Dockerfile.frontend \
  --build-arg NEXT_PUBLIC_API_URL=http://ci-agent-backend:8000 \
  -t $REGISTRY/frontend:$VERSION .

docker push $REGISTRY/backend:$VERSION
docker push $REGISTRY/frontend:$VERSION
```

### 步骤二：修改配置文件

**`deploy/k8s/secret.yaml`** — 填入真实密钥：

```yaml
stringData:
  ANTHROPIC_API_KEY: "sk-ant-your-real-key"   # 必填
  GITHUB_TOKEN: "ghp_your-real-token"          # 推荐
```

> 生产环境建议改用 [External Secrets Operator](https://external-secrets.io/) 或 [Sealed Secrets](https://sealed-secrets.netlify.app/)。

**`deploy/k8s/configmap.yaml`** — 修改域名和模型：

```yaml
data:
  CI_AGENT_MODEL: "claude-sonnet-4-20250514"
  CI_AGENT_PROVIDER: "anthropic"
  CI_AGENT_LANGUAGE: "en"
  CORS_ORIGINS: "https://ci-agent.your-domain.com"   # 必填，改为你的域名
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

### 步骤三：部署

```bash
# 方式一：kustomize（推荐）
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

### 步骤四：验证

```bash
# 查看 Pod 状态（等待 Running）
kubectl -n ci-agent get pods -w

# 查看后端日志（应看到 "Skill registry loaded"）
kubectl -n ci-agent logs -f deployment/ci-agent-backend

# 测试 Backend API
kubectl -n ci-agent port-forward svc/ci-agent-backend 8000:8000
curl http://localhost:8000/health        # → {"status":"ok"}
curl http://localhost:8000/api/skills    # → 4 built-in skills
```

### 步骤五：访问前端

**方式一：通过 Ingress（正式域名，推荐生产）**

确保域名已解析到 Ingress Controller 的外部 IP，直接浏览器访问：
```
https://ci-agent.your-domain.com
```

**方式二：port-forward（测试 / 本地环境）**

```bash
kubectl -n ci-agent port-forward svc/ci-agent-frontend 3001:3000
```
浏览器打开 → http://localhost:3001

> `/api/*` 请求会自动由 Next.js rewrite 代理到 backend，无需额外配置。

---

## 方案三：Minikube（本地 K8s 测试）

适合在本地验证 K8s 部署行为，无需外部镜像仓库。

### 前置条件

```bash
# 安装 minikube
brew install minikube

# 启动集群
minikube start

# 启用 nginx ingress
minikube addons enable ingress
```

### 构建镜像到 minikube 内部

```bash
# 切换到 minikube 的 Docker 环境（关键步骤）
eval $(minikube docker-env)

# 构建镜像（直接进入 minikube，不需要推送）
docker build -f Dockerfile.backend -t ci-agent-backend:v0.1.0 .

docker build -f Dockerfile.frontend \
  --build-arg NEXT_PUBLIC_API_URL=http://ci-agent-backend:8000 \
  -t ci-agent-frontend:v0.1.0 .
```

### 部署

```bash
# 部署基础资源
kubectl apply -k deploy/k8s/

# 改为使用本地镜像（不从仓库拉取）
kubectl -n ci-agent patch deployment ci-agent-backend \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"backend","imagePullPolicy":"Never"}]}}}}'
kubectl -n ci-agent patch deployment ci-agent-frontend \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"frontend","imagePullPolicy":"Never"}]}}}}'

# 注入 API Key
kubectl -n ci-agent create secret generic ci-agent-secrets \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-your-key" \
  --from-literal=GITHUB_TOKEN="ghp_your-token" \
  --dry-run=client -o yaml | kubectl apply -f -

# 更新 provider 配置并重启
kubectl -n ci-agent patch configmap ci-agent-config \
  -p '{"data":{"CI_AGENT_PROVIDER":"anthropic","CORS_ORIGINS":"http://localhost:3001"}}'
kubectl -n ci-agent rollout restart deployment/ci-agent-backend
```

### 访问前端

**macOS / Docker driver 限制**：minikube IP 在容器网络内，浏览器无法直接访问，使用 port-forward：

```bash
kubectl -n ci-agent port-forward svc/ci-agent-frontend 3001:3000
```

浏览器打开 → **http://localhost:3001**

### 验证

```bash
# 查看所有 Pod
kubectl -n ci-agent get pods

# 预期输出：
# ci-agent-backend-xxx   1/1   Running
# ci-agent-frontend-xxx  1/1   Running  (2 replicas)

# 测试 backend
kubectl -n ci-agent port-forward svc/ci-agent-backend 8001:8000 &
curl http://localhost:8001/health       # → {"status":"ok"}
curl http://localhost:8001/api/skills   # → 4 skills

# 测试 frontend proxy（port-forward 状态下）
curl http://localhost:3001/api/skills   # → 4 skills（经 Next.js rewrite 代理）
```

### 清理

```bash
kubectl delete -k deploy/k8s/

# 恢复本地 Docker 环境
eval $(minikube docker-env -u)
```

---

### 更新镜像版本

```bash
REGISTRY=your-registry.com/ci-agent

# 重新构建推送
docker build -f Dockerfile.backend -t $REGISTRY/backend:v0.2.0 . && docker push $REGISTRY/backend:v0.2.0
docker build -f Dockerfile.frontend -t $REGISTRY/frontend:v0.2.0 . && docker push $REGISTRY/frontend:v0.2.0

# 滚动更新（frontend 支持滚动，backend 会 Recreate）
kubectl -n ci-agent set image deploy/ci-agent-backend backend=$REGISTRY/backend:v0.2.0
kubectl -n ci-agent set image deploy/ci-agent-frontend frontend=$REGISTRY/frontend:v0.2.0

# 等待更新完成
kubectl -n ci-agent rollout status deploy/ci-agent-backend
kubectl -n ci-agent rollout status deploy/ci-agent-frontend
```

### 常用运维命令

```bash
# 查看所有资源
kubectl -n ci-agent get all

# 重启 backend（配置变更后）
kubectl -n ci-agent rollout restart deploy/ci-agent-backend

# 更新 ConfigMap 后重启
kubectl -n ci-agent edit configmap ci-agent-config
kubectl -n ci-agent rollout restart deploy/ci-agent-backend

# 更新 Secret 后重启
kubectl -n ci-agent edit secret ci-agent-secrets
kubectl -n ci-agent rollout restart deploy/ci-agent-backend

# 查看事件（排查 Pod 异常）
kubectl -n ci-agent describe pod <pod-name>
kubectl -n ci-agent get events --sort-by=.lastTimestamp

# 卸载
kubectl delete -k deploy/k8s/
```

---

## 环境变量参考

| 变量 | 组件 | 必填 | 说明 |
|------|------|------|------|
| `ANTHROPIC_API_KEY` | Backend | Yes* | Claude API Key |
| `OPENAI_API_KEY` | Backend | Yes* | OpenAI API Key |
| `CI_AGENT_PROVIDER` | Backend | No | `anthropic` (默认) / `openai` |
| `CI_AGENT_MODEL` | Backend | No | 模型名，默认 `claude-sonnet-4-20250514` |
| `CI_AGENT_BASE_URL` | Backend | No | OpenAI 兼容端点，默认官方 |
| `CI_AGENT_LANGUAGE` | Backend | No | `en` (默认) / `zh` |
| `GITHUB_TOKEN` | Backend | Recommended | 获取 CI 运行历史和 Action SHA |
| `CORS_ORIGINS` | Backend | No | 允许的前端域名，默认 `http://localhost:3000` |
| `CI_AGENT_LOG_LEVEL` | Backend | No | 日志级别，默认 `INFO` |
| `NEXT_PUBLIC_API_URL` | Frontend | No | Backend 地址（SSR 用），K8s 内默认 `http://ci-agent-backend:8000` |

*`ANTHROPIC_API_KEY` 和 `OPENAI_API_KEY` 至少填一个。

---

## 存储与持久化

### SQLite（默认）

- 数据存储在 PVC 或 volume 的 `/data/.ci-agent/data.db`
- **限制**：Backend 只能 1 个副本
- 适合：个人/小团队使用

### 升级到 PostgreSQL（生产多副本）

```bash
# 1. 修改 backend 依赖
pip install asyncpg

# 2. 修改 db/database.py 连接字符串
DATABASE_URL = "postgresql+asyncpg://user:pass@host/ci_agent"

# 3. backend.yaml replicas 可调为 2+，strategy 改为 RollingUpdate
# 4. 添加 PostgreSQL StatefulSet 或使用云托管 RDS/CloudSQL
```

---

## 高可用与扩展

| 组件 | 当前 | 高可用方案 |
|------|------|----------|
| Frontend | 2 replicas | HPA（CPU > 70% 自动扩容）|
| Backend | 1 replica（SQLite 限制）| 换 PostgreSQL 后可扩容 |
| 数据库 | SQLite PVC | PostgreSQL HA / 云托管 RDS |

**Frontend HPA 配置：**

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

## 安全建议

1. **Secrets 管理**：生产环境不要在 YAML 中明文存放密钥，改用：
   - [External Secrets Operator](https://external-secrets.io/)
   - [Sealed Secrets](https://sealed-secrets.netlify.app/)
   - 云厂商 KMS（AWS Secrets Manager / GCP Secret Manager / Azure Key Vault）

2. **TLS**：通过 cert-manager 自动签发证书，uncomment `ingress.yaml` 中的 `tls` 段

3. **网络策略**：限制 Backend 出站仅允许 Anthropic API、OpenAI API 和 GitHub API

4. **镜像安全**：使用私有镜像仓库 + Trivy / Grype 镜像扫描

---

## 故障排查

### Backend Pod 无法启动

```bash
kubectl -n ci-agent describe pod <backend-pod>
kubectl -n ci-agent logs <backend-pod> --previous
```

常见原因：
- Secret 中 `ANTHROPIC_API_KEY` 未填入真实值
- PVC 无法绑定（StorageClass 不存在）
- 镜像拉取失败（imagePullPolicy / 私有仓库认证）

### 分析失败（前端报错）

```bash
# 查看 backend 实时日志
kubectl -n ci-agent logs -f deployment/ci-agent-backend

# 或 Docker Compose
docker compose logs -f backend
```

常见原因：
- `GITHUB_TOKEN` 未配置，无法拉取 CI 历史
- 网络出口限制，无法访问 GitHub / Anthropic API
- 分析超时（默认 Ingress 超时 300s，AI 分析可能超过）

### Ingress 502 / 504

```bash
# 确认 backend Service 正常
kubectl -n ci-agent get svc ci-agent-backend
kubectl -n ci-agent port-forward svc/ci-agent-backend 8000:8000
curl http://localhost:8000/health
```

检查 `ingress.yaml` 中的 `proxy-read-timeout` 是否足够（默认已设 300s）。