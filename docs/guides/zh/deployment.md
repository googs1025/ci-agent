# CI Agent 部署指南

本文档介绍如何通过 Docker Compose 或 Kubernetes 部署 CI Agent。

---

## 目录

- [Docker Compose 部署](#docker-compose-部署)
- [Kubernetes 部署](#kubernetes-部署)
  - [前置要求](#前置要求)
  - [本地 Minikube 部署](#本地-minikube-部署)
  - [生产集群部署](#生产集群部署)
- [环境变量参考](#环境变量参考)
- [健康检查](#健康检查)
- [升级](#升级)

---

## Docker Compose 部署

适合本地开发或单机部署场景。

### 第一步：配置环境变量

复制示例文件并填写密钥：

```bash
cp .env.example .env
```

编辑 `.env`，至少填写以下必填项：

```bash
# 必填：AI 引擎密钥（二选一）
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...

# 必填：GitHub Token（用于拉取 CI 数据）
GITHUB_TOKEN=ghp_...

# 可选：API 认证（留空则不启用）
CI_AGENT_API_KEY=

# 可选：Langfuse 追踪
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_HOST=https://us.cloud.langfuse.com
```

### 第二步：构建并启动

```bash
docker compose up -d --build
```

首次构建需要 3–5 分钟。启动后访问：

- **前端 UI**：http://localhost:3000
- **后端 API**：http://localhost:8000
- **健康检查**：http://localhost:8000/health

### 第三步：查看日志

```bash
# 查看所有容器日志
docker compose logs -f

# 只看后端
docker compose logs -f backend

# 只看前端
docker compose logs -f frontend
```

### 停止与清理

```bash
# 停止（保留数据卷）
docker compose down

# 停止并删除数据卷（数据库将被清空）
docker compose down -v
```

### 附加 Langfuse（可选）

如需本地自托管 Langfuse，创建 `docker-compose.langfuse.yaml`（参考 [Langfuse 配置指南](./langfuse-setup.md)），然后：

```bash
# 先启动 Langfuse
docker compose -f docker-compose.langfuse.yaml up -d

# 再启动 CI Agent
docker compose up -d --build
```

---

## Kubernetes 部署

所有 K8s 清单文件位于 `deploy/k8s/`，使用 Kustomize 管理。

### 前置要求

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| kubectl | ≥ 1.25 | K8s 命令行工具 |
| kustomize | ≥ 5.0（或 kubectl ≥ 1.27） | 清单管理 |
| 镜像仓库 | — | 生产环境需要推送镜像 |

### 本地 Minikube 部署

适合本地测试，镜像直接加载到 Minikube，不需要镜像仓库。

#### 1. 启动 Minikube 并启用 Ingress

```bash
minikube start --memory=4096 --cpus=2
minikube addons enable ingress
```

#### 2. 构建镜像并加载到 Minikube

```bash
# 将 Docker 环境指向 Minikube 的 Docker daemon
eval $(minikube docker-env)

# 构建镜像
docker build -t ci-agent-backend:v0.1.0 -f Dockerfile.backend .
docker build -t ci-agent-frontend:v0.1.0 -f Dockerfile.frontend .
```

#### 3. 配置密钥

编辑 `deploy/k8s/secret.yaml`，填入真实密钥：

```yaml
stringData:
  ANTHROPIC_API_KEY: "sk-ant-your-key"   # 必填
  GITHUB_TOKEN: "ghp_your-token"          # 建议填写
  CI_AGENT_API_KEY: ""                     # 可选
  LANGFUSE_PUBLIC_KEY: ""                  # 可选
  LANGFUSE_SECRET_KEY: ""                  # 可选
```

> **注意**：不要将含真实密钥的 `secret.yaml` 提交到代码仓库。

#### 4. 应用 Minikube Overlay

```bash
kubectl apply -k deploy/k8s/overlays/minikube/
```

Minikube overlay 会自动将 `imagePullPolicy` 设置为 `Never`，使用本地构建的镜像。

#### 5. 等待 Pod 就绪

```bash
kubectl -n ci-agent get pods -w
```

所有 Pod 应在 1–2 分钟内变为 `Running` 状态。

#### 6. 配置本地域名解析

```bash
# 获取 Minikube IP
MINIKUBE_IP=$(minikube ip)

# 添加到 /etc/hosts（需要 sudo）
echo "$MINIKUBE_IP ci-agent.example.com" | sudo tee -a /etc/hosts
```

#### 7. 访问应用

```bash
# 方式 1：通过 Ingress（需要配置 /etc/hosts）
open http://ci-agent.example.com

# 方式 2：通过端口转发（无需配置域名）
kubectl -n ci-agent port-forward svc/ci-agent-frontend 3000:3000 &
kubectl -n ci-agent port-forward svc/ci-agent-backend 8000:8000 &
open http://localhost:3000
```

---

### 生产集群部署

#### 1. 构建并推送镜像

```bash
# 设置你的镜像仓库前缀
REGISTRY=your-registry.example.com/your-org

docker build -t $REGISTRY/ci-agent-backend:v0.1.0 -f Dockerfile.backend .
docker build -t $REGISTRY/ci-agent-frontend:v0.1.0 -f Dockerfile.frontend .

docker push $REGISTRY/ci-agent-backend:v0.1.0
docker push $REGISTRY/ci-agent-frontend:v0.1.0
```

#### 2. 更新镜像引用

编辑 `deploy/k8s/backend.yaml` 和 `deploy/k8s/frontend.yaml`，将 `image:` 替换为你的镜像地址：

```yaml
# backend.yaml
image: your-registry.example.com/your-org/ci-agent-backend:v0.1.0

# frontend.yaml
image: your-registry.example.com/your-org/ci-agent-frontend:v0.1.0
```

#### 3. 更新域名

编辑 `deploy/k8s/ingress.yaml`，将 `ci-agent.example.com` 替换为你的真实域名：

```yaml
spec:
  rules:
    - host: your-domain.example.com
```

同时更新 `deploy/k8s/configmap.yaml` 中的 `CORS_ORIGINS`：

```yaml
CORS_ORIGINS: "https://your-domain.example.com"
```

#### 4. 配置密钥

建议使用外部密钥管理工具（如 Vault、External Secrets Operator）而非直接编辑 `secret.yaml`。如果直接编辑，确保不要提交到代码仓库：

```bash
# 通过 kubectl 直接创建 Secret（不写入文件）
kubectl -n ci-agent create secret generic ci-agent-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=GITHUB_TOKEN=ghp_... \
  --from-literal=CI_AGENT_API_KEY= \
  --from-literal=LANGFUSE_PUBLIC_KEY= \
  --from-literal=LANGFUSE_SECRET_KEY=
```

#### 5. 应用基础清单

```bash
kubectl apply -k deploy/k8s/
```

#### 6. 配置 TLS（可选）

取消注释 `deploy/k8s/ingress.yaml` 中的 TLS 配置：

```yaml
tls:
  - hosts:
      - your-domain.example.com
    secretName: ci-agent-tls
```

使用 cert-manager 自动签发证书：

```bash
# 安装 cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# 为 Ingress 添加 annotation
kubectl -n ci-agent annotate ingress ci-agent-ingress \
  cert-manager.io/cluster-issuer=letsencrypt-prod
```

#### 7. 部署 Langfuse（可选）

详见 [Langfuse 配置指南 — K8s 部分](./langfuse-setup.md#kubernetes)。

---

## 环境变量参考

以下变量在 `deploy/k8s/configmap.yaml`（非敏感）和 `deploy/k8s/secret.yaml`（敏感）中配置：

### ConfigMap（非敏感）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CI_AGENT_PROVIDER` | `anthropic` | AI 引擎（`anthropic` / `openai`） |
| `CI_AGENT_MODEL` | `claude-sonnet-4-20250514` | 模型名称 |
| `CI_AGENT_LANGUAGE` | `en` | 输出语言（`en` / `zh`） |
| `CORS_ORIGINS` | — | 允许跨域的前端 URL，**必须更新** |
| `LANGFUSE_HOST` | `http://langfuse:3000` | Langfuse 服务地址（留空禁用） |

### Secret（敏感）

| 变量 | 必填 | 说明 |
|------|------|------|
| `ANTHROPIC_API_KEY` | 是（二选一） | Anthropic API Key |
| `OPENAI_API_KEY` | 是（二选一） | OpenAI API Key |
| `GITHUB_TOKEN` | 建议 | GitHub PAT，用于拉取 CI 数据 |
| `CI_AGENT_API_KEY` | 否 | 留空则不启用 API 认证 |
| `LANGFUSE_PUBLIC_KEY` | 否 | Langfuse Project Public Key |
| `LANGFUSE_SECRET_KEY` | 否 | Langfuse Project Secret Key |

---

## 健康检查

### Docker Compose

```bash
# 检查容器状态
docker compose ps

# 手动调用健康接口
curl http://localhost:8000/health
```

### Kubernetes

```bash
# 查看所有 Pod 状态
kubectl -n ci-agent get pods

# 查看 Pod 详情（含事件）
kubectl -n ci-agent describe pod <pod-name>

# 查看后端日志
kubectl -n ci-agent logs -l app.kubernetes.io/name=ci-agent-backend -f

# 查看前端日志
kubectl -n ci-agent logs -l app.kubernetes.io/name=ci-agent-frontend -f
```

---

## 升级

### Docker Compose

```bash
git pull
docker compose up -d --build
```

### Kubernetes

```bash
git pull

# 重新构建并推送新镜像（生产环境更新标签）
docker build -t $REGISTRY/ci-agent-backend:v0.2.0 -f Dockerfile.backend .
docker push $REGISTRY/ci-agent-backend:v0.2.0

# 更新 backend.yaml 中的镜像标签，然后
kubectl apply -k deploy/k8s/

# 或直接滚动更新
kubectl -n ci-agent set image deployment/ci-agent-backend \
  ci-agent-backend=$REGISTRY/ci-agent-backend:v0.2.0
```
