# CI Agent Deployment Guide

This document explains how to deploy CI Agent using Docker Compose or Kubernetes.

---

## Table of Contents

- [Docker Compose Deployment](#docker-compose-deployment)
- [Kubernetes Deployment](#kubernetes-deployment)
  - [Prerequisites](#prerequisites)
  - [Local Minikube Deployment](#local-minikube-deployment)
  - [Production Cluster Deployment](#production-cluster-deployment)
- [Environment Variable Reference](#environment-variable-reference)
- [Health Checks](#health-checks)
- [Upgrading](#upgrading)

---

## Docker Compose Deployment

Suitable for local development or single-machine deployments.

### Step 1: Configure Environment Variables

Copy the example file and fill in your secrets:

```bash
cp .env.example .env
```

Edit `.env` and fill in at least the required fields:

```bash
# Required: AI engine key (choose one)
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...

# Required: GitHub Token (for fetching CI data)
GITHUB_TOKEN=ghp_...

# Optional: API authentication (leave blank to disable)
CI_AGENT_API_KEY=

# Optional: Langfuse tracing
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_HOST=https://us.cloud.langfuse.com
```

### Step 2: Build and Start

```bash
docker compose up -d --build
```

The first build takes 3–5 minutes. Once started, access:

- **Frontend UI**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **Health check**: http://localhost:8000/health

### Step 3: View Logs

```bash
# All containers
docker compose logs -f

# Backend only
docker compose logs -f backend

# Frontend only
docker compose logs -f frontend
```

### Stop and Clean Up

```bash
# Stop (keep data volumes)
docker compose down

# Stop and remove data volumes (database will be wiped)
docker compose down -v
```

### Add Langfuse (Optional)

To run a self-hosted Langfuse alongside CI Agent, create `docker-compose.langfuse.yaml` (see the [Langfuse Setup Guide](./langfuse-setup.md)), then:

```bash
# Start Langfuse first
docker compose -f docker-compose.langfuse.yaml up -d

# Then start CI Agent
docker compose up -d --build
```

---

## Kubernetes Deployment

All K8s manifests are in `deploy/k8s/` and managed with Kustomize.

### Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| kubectl | ≥ 1.25 | Kubernetes CLI |
| kustomize | ≥ 5.0 (or kubectl ≥ 1.27) | Manifest management |
| Image registry | — | Required for production |

### Local Minikube Deployment

For local testing — images are loaded directly into Minikube, no registry needed.

#### 1. Start Minikube and Enable Ingress

```bash
minikube start --memory=4096 --cpus=2
minikube addons enable ingress
```

#### 2. Build Images Inside Minikube

```bash
# Point Docker CLI to Minikube's Docker daemon
eval $(minikube docker-env)

# Build images
docker build -t ci-agent-backend:v0.1.0 -f Dockerfile.backend .
docker build -t ci-agent-frontend:v0.1.0 -f Dockerfile.frontend .
```

#### 3. Configure Secrets

Edit `deploy/k8s/secret.yaml` with real values:

```yaml
stringData:
  ANTHROPIC_API_KEY: "sk-ant-your-key"   # Required
  GITHUB_TOKEN: "ghp_your-token"          # Recommended
  CI_AGENT_API_KEY: ""                     # Optional
  LANGFUSE_PUBLIC_KEY: ""                  # Optional
  LANGFUSE_SECRET_KEY: ""                  # Optional
```

> **Warning**: Never commit `secret.yaml` with real credentials to your repository.

#### 4. Apply the Minikube Overlay

```bash
kubectl apply -k deploy/k8s/overlays/minikube/
```

The Minikube overlay automatically sets `imagePullPolicy: Never` so local images are used.

#### 5. Wait for Pods to Be Ready

```bash
kubectl -n ci-agent get pods -w
```

All pods should reach `Running` status within 1–2 minutes.

#### 6. Configure Local DNS

```bash
# Get the Minikube IP
MINIKUBE_IP=$(minikube ip)

# Add to /etc/hosts (requires sudo)
echo "$MINIKUBE_IP ci-agent.example.com" | sudo tee -a /etc/hosts
```

#### 7. Access the Application

```bash
# Option 1: Via Ingress (requires /etc/hosts entry above)
open http://ci-agent.example.com

# Option 2: Via port-forward (no DNS config needed)
kubectl -n ci-agent port-forward svc/ci-agent-frontend 3000:3000 &
kubectl -n ci-agent port-forward svc/ci-agent-backend 8000:8000 &
open http://localhost:3000
```

---

### Production Cluster Deployment

#### 1. Build and Push Images

```bash
# Set your registry prefix
REGISTRY=your-registry.example.com/your-org

docker build -t $REGISTRY/ci-agent-backend:v0.1.0 -f Dockerfile.backend .
docker build -t $REGISTRY/ci-agent-frontend:v0.1.0 -f Dockerfile.frontend .

docker push $REGISTRY/ci-agent-backend:v0.1.0
docker push $REGISTRY/ci-agent-frontend:v0.1.0
```

#### 2. Update Image References

Edit `deploy/k8s/backend.yaml` and `deploy/k8s/frontend.yaml` to use your registry:

```yaml
# backend.yaml
image: your-registry.example.com/your-org/ci-agent-backend:v0.1.0

# frontend.yaml
image: your-registry.example.com/your-org/ci-agent-frontend:v0.1.0
```

#### 3. Update Domain Name

Edit `deploy/k8s/ingress.yaml` and replace `ci-agent.example.com` with your real domain:

```yaml
spec:
  rules:
    - host: your-domain.example.com
```

Also update `CORS_ORIGINS` in `deploy/k8s/configmap.yaml`:

```yaml
CORS_ORIGINS: "https://your-domain.example.com"
```

#### 4. Configure Secrets

We recommend using an external secret manager (Vault, External Secrets Operator) rather than editing `secret.yaml` directly. To create the secret imperatively without writing it to a file:

```bash
kubectl -n ci-agent create secret generic ci-agent-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=GITHUB_TOKEN=ghp_... \
  --from-literal=CI_AGENT_API_KEY= \
  --from-literal=LANGFUSE_PUBLIC_KEY= \
  --from-literal=LANGFUSE_SECRET_KEY=
```

#### 5. Apply the Base Manifests

```bash
kubectl apply -k deploy/k8s/
```

#### 6. Configure TLS (Optional)

Uncomment the TLS section in `deploy/k8s/ingress.yaml`:

```yaml
tls:
  - hosts:
      - your-domain.example.com
    secretName: ci-agent-tls
```

Auto-provision certificates with cert-manager:

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Annotate the Ingress
kubectl -n ci-agent annotate ingress ci-agent-ingress \
  cert-manager.io/cluster-issuer=letsencrypt-prod
```

#### 7. Deploy Langfuse (Optional)

See the [Langfuse Setup Guide — Kubernetes section](./langfuse-setup.md#kubernetes).

---

## Environment Variable Reference

Non-sensitive config goes in `deploy/k8s/configmap.yaml`; secrets go in `deploy/k8s/secret.yaml`.

### ConfigMap (Non-Sensitive)

| Variable | Default | Description |
|----------|---------|-------------|
| `CI_AGENT_PROVIDER` | `anthropic` | AI engine (`anthropic` / `openai`) |
| `CI_AGENT_MODEL` | `claude-sonnet-4-20250514` | Model name |
| `CI_AGENT_LANGUAGE` | `en` | Output language (`en` / `zh`) |
| `CORS_ORIGINS` | — | Allowed frontend origin URL — **must be updated** |
| `LANGFUSE_HOST` | `http://langfuse:3000` | Langfuse service URL (leave blank to disable) |
| `DIAGNOSE_DEFAULT_MODEL` | `claude-haiku-4-5-20251001` | Default model for single-run diagnosis (override for OpenAI users) |
| `DIAGNOSE_DEEP_MODEL` | `claude-sonnet-4-20250514` | Model used for Deep Analysis |
| `DIAGNOSE_AUTO_ON_WEBHOOK` | `true` | Auto-diagnose on webhook failures |
| `DIAGNOSE_SAMPLE_RATE` | `1.0` | Auto-diagnose sample rate 0.0–1.0 |
| `DIAGNOSE_BUDGET_USD_DAY` | `1.0` | Daily USD ceiling for auto-diagnose |
| `DIAGNOSE_SIGNATURE_TTL_HOURS` | `24` | Signature dedup window |

### Secret (Sensitive)

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes (one of two) | Anthropic API Key |
| `OPENAI_API_KEY` | Yes (one of two) | OpenAI API Key |
| `GITHUB_TOKEN` | Recommended | GitHub PAT for fetching CI data |
| `CI_AGENT_API_KEY` | No | Leave blank to disable API auth |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse Project Public Key |
| `LANGFUSE_SECRET_KEY` | No | Langfuse Project Secret Key |

---

## Health Checks

### Docker Compose

```bash
# Check container status
docker compose ps

# Call the health endpoint manually
curl http://localhost:8000/health
```

### Kubernetes

```bash
# Check all pod statuses
kubectl -n ci-agent get pods

# Describe a pod (includes events)
kubectl -n ci-agent describe pod <pod-name>

# Stream backend logs
kubectl -n ci-agent logs -l app.kubernetes.io/name=ci-agent-backend -f

# Stream frontend logs
kubectl -n ci-agent logs -l app.kubernetes.io/name=ci-agent-frontend -f
```

---

## Upgrading

### Docker Compose

```bash
git pull
docker compose up -d --build
```

### Kubernetes

```bash
git pull

# Build and push a new image (update the tag for production)
docker build -t $REGISTRY/ci-agent-backend:v0.2.0 -f Dockerfile.backend .
docker push $REGISTRY/ci-agent-backend:v0.2.0

# Update the image tag in backend.yaml, then
kubectl apply -k deploy/k8s/

# Or rolling-update directly
kubectl -n ci-agent set image deployment/ci-agent-backend \
  ci-agent-backend=$REGISTRY/ci-agent-backend:v0.2.0
```