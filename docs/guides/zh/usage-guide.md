# CI Optimizer 使用指南

CI Optimizer 是一个 AI 驱动的 GitHub CI 流水线分析工具，自动检测效率瓶颈、安全漏洞、成本浪费和错误模式，并提供可操作的修复建议。

---

## 目录

- [快速开始](#快速开始)
- [如何获取 GitHub Token](#如何获取-github-token)
- [1. Dashboard — 总览面板](#1-dashboard--总览面板)
- [2. Analyze — 启动分析](#2-analyze--启动分析)
- [3. Reports — 报告列表](#3-reports--报告列表)
- [4. Report Detail — 报告详情](#4-report-detail--报告详情)
- [5. Diagnose — 单次失败诊断](#5-diagnose--单次失败诊断)
- [6. Skills — 技能管理](#6-skills--技能管理)
- [7. CLI 命令参考](#7-cli-命令参考)
- [8. 配置](#8-配置)

---

## 快速开始

```bash
# 1. 安装依赖
pip install -e .
cd web && npm install

# 2. 配置 API Key（至少一个）
export OPENAI_API_KEY=sk-...           # OpenAI 兼容
# 或
export ANTHROPIC_API_KEY=sk-ant-...    # Anthropic Claude

# 3. 配置 GitHub Token（用于拉取 CI 数据，获取方式见下方说明）
export GITHUB_TOKEN=ghp_...

# 4. 启动后端
ci-agent serve

# 5. 启动前端
cd web && npm run dev

# 6. 打开浏览器
open http://localhost:3000
```

---

## 如何获取 GitHub Token

CI Optimizer 需要 GitHub Personal Access Token 来访问仓库的 CI 运行历史（workflow runs、jobs、logs 等）。如果不配置，将无法拉取 CI 数据进行分析。

### 什么是 GitHub Token？

GitHub Token（个人访问令牌）是 GitHub 提供的一种身份认证方式，相当于你的"API 密码"，让第三方工具可以代替你访问 GitHub API。它比直接使用用户名密码更安全，因为你可以限制它的权限范围和有效期。

### 创建步骤（推荐：Fine-grained Token）

GitHub 提供两种 Token：**Fine-grained Token**（细粒度令牌，推荐）和 **Classic Token**。推荐使用 Fine-grained Token，因为它可以精确控制权限范围。

#### 方式一：Fine-grained Token（推荐）

1. 登录 GitHub，点击右上角头像 → **Settings**
2. 左侧边栏滚动到底部，点击 **Developer settings**
3. 点击 **Personal access tokens** → **Fine-grained tokens**
4. 点击 **Generate new token**
5. 填写以下信息：
   - **Token name**：填一个容易辨认的名字，如 `ci-agent`
   - **Expiration**：选择有效期（建议 90 天，到期后重新生成即可）
   - **Repository access**：选择 **All repositories**（分析所有仓库）或 **Only select repositories**（仅分析指定仓库）
   - **Permissions** → **Repository permissions**：
     - `Actions`: **Read-only**（必需，读取 workflow 运行记录）
     - `Contents`: **Read-only**（必需，读取 workflow 文件内容）
     - `Metadata`: **Read-only**（默认已选）
6. 点击 **Generate token**
7. **立即复制 Token**（页面关闭后无法再次查看）

#### 方式二：Classic Token

1. 登录 GitHub，点击右上角头像 → **Settings**
2. 左侧边栏滚动到底部，点击 **Developer settings**
3. 点击 **Personal access tokens** → **Tokens (classic)**
4. 点击 **Generate new token (classic)**
5. 填写以下信息：
   - **Note**：填写用途说明，如 `ci-agent`
   - **Expiration**：选择有效期
   - **勾选权限**：
     - `repo`（完整仓库访问，包含私有仓库）
     - 如果只分析公开仓库，勾选 `public_repo` 即可
6. 点击 **Generate token**
7. **立即复制 Token**

### 配置 Token

获取 Token 后，选择以下任一方式配置：

```bash
# 方式 1：环境变量（推荐，适合本地开发）
export GITHUB_TOKEN=github_pat_xxx

# 方式 2：写入 .env 文件（适合 Docker 部署）
echo "GITHUB_TOKEN=github_pat_xxx" >> .env

# 方式 3：通过 CLI 配置（持久化到 ~/.ci-agent/config.json）
ci-agent config set github_token github_pat_xxx

# 方式 4：通过 Web UI 配置
# 打开 http://localhost:3000/config，在 GitHub Token 输入框中填入
```

### 验证 Token 是否有效

```bash
# 使用 curl 测试（替换为你的 Token）
curl -H "Authorization: Bearer github_pat_xxx" https://api.github.com/user
# 如果返回你的用户信息，说明 Token 配置正确
```

### 安全提示

- **不要将 Token 提交到代码仓库**（`.env` 已在 `.gitignore` 中）
- **设置合理的有效期**，到期后重新生成
- **使用最小权限原则**，只授予必要的读取权限
- 如果 Token 泄露，立即到 GitHub Settings 中 **Revoke** 作废

---

## 1. Dashboard — 总览面板

![Dashboard](../../screenshots/01-dashboard.png)

Dashboard 提供 CI 分析的全局视图：

| 区域 | 说明 |
|------|------|
| **统计卡片** | 已分析仓库数、总分析次数、总发现数（含 critical 计数） |
| **严重性分布** | critical / major / minor / info 的柱状分布，点击可跳转报告列表 |
| **维度分布** | 按分析维度（效率/安全/成本/错误）展示发现数量 |
| **近期报告** | 最近 5 次分析结果，点击仓库名直接进入报告详情 |

---

## 2. Analyze — 启动分析

![Analyze](../../screenshots/02-analyze.png)

### 使用步骤

1. **输入仓库地址** — 支持以下格式：
   - GitHub URL：`https://github.com/owner/repo`
   - 简写：`owner/repo`
   - 本地路径：`/absolute/path/to/repo`

2. **选择分析技能** — 勾选需要运行的分析维度：
   - **Cost**：成本优化（runner 选择、计费优化）
   - **Efficiency**：执行效率（并行化、缓存、条件执行）
   - **Errors**：错误分析（失败模式、重试策略）
   - **Security**：安全检测（权限、Action 固定、注入风险）

3. **过滤条件**（可选）— 限定分析范围：
   - 时间范围（Date range）
   - 运行状态（Success / Failure / Cancelled）
   - 指定工作流名称
   - 指定分支

4. **点击 Start Analysis** — 开始分析

### 分析进度

提交后页面会显示实时进度提示：

| 耗时 | 阶段 | 说明 |
|------|------|------|
| 0 ~ 15s | Cloning repository | 从 GitHub 拉取源码 |
| 15 ~ 45s | Prefetching CI data | 加载工作流运行历史、Job 数据、日志 |
| 45s+ | Analyzing with AI | AI Agent 执行分析并生成报告 |

分析完成后自动跳转到报告详情页。

---

## 3. Reports — 报告列表

![Reports List](../../screenshots/03-reports-list.png)

展示所有历史分析报告，包含：
- 仓库名（可点击进入详情）
- 分析时间
- 状态（completed / failed / running / pending）
- 发现数量
- 分析耗时

支持分页浏览。

---

## 4. Report Detail — 报告详情

![Report Detail](../../screenshots/04-report-detail.png)

报告详情采用**双栏布局**：

### 左侧边栏

- **严重性筛选** — 点击 critical / major / minor / info 芯片快速过滤所有维度的 findings
- **维度导航** — 点击切换当前显示的分析维度，每个维度显示 finding 数量
- 筛选可与搜索叠加使用

### 右侧主区域

- **Executive Summary** — AI 生成的 Top 5 优先建议
- **搜索框** — 实时搜索 finding 标题 / 描述 / 文件路径
- **Findings 表格** — 按严重性排序，支持点击表头切换排序方式

### Finding 展开详情

![Finding Expanded](../../screenshots/05-finding-expanded.png)

点击任意 finding 行展开详细信息：

| 区域 | 说明 |
|------|------|
| **Skill / File** | 来源技能名称 + 文件位置 |
| **Description** | 问题描述 |
| **Suggestion** | 修复建议 |
| **Code Changes** | **统一 Diff 视图** — 红色行为删除内容，绿色行为新增内容，显示 −N +N 统计 |
| **Copy 按钮** | 一键复制建议代码，2 秒后自动重置 |
| **Impact** | 影响评估 |

> Security 维度的 Action 固定建议会提供**真实的 commit SHA**（非占位符），可直接复制使用。

---

## 5. Diagnose — 单次失败诊断

针对单个失败的 CI run 做 AI 根因分析。与 Analyze 的区别：

| | Analyze | Diagnose |
|---|---|---|
| 粒度 | 整个仓库历史 | 单次 failed run |
| 输出 | 多维度 Findings 报告 | 结构化诊断卡片 |
| 用途 | 定期体检、发现长期问题 | 排查「这次 CI 为啥挂了」 |

### 使用步骤

1. 打开 **Diagnose** 页面
2. **两种输入方式任选其一**：
   - 输入 `owner/repo` → 点「Find Failures」→ 看到按 workflow 分组的最近 20 次失败 → 点任意行的「Diagnose」
   - 粘贴完整的 GitHub Actions run URL（如 `https://github.com/owner/repo/actions/runs/12345`）→ 自动提取 repo + run_id + attempt，直接跳过 picker 开始诊断
3. 等待 5–15 秒，诊断卡片出现

### 诊断卡片内容

- **分类徽章**：9 类中的一类（flaky_test / timeout / dependency / network / resource_limit / config / build / infra / unknown），颜色编码
- **置信度**：high / medium / low
- **Root Cause**：一句话定位根因
- **Failing Step + Workflow**：哪个步骤失败
- **Quick Fix**：一键可复制的修复建议
- **Error Excerpt**：可折叠的日志片段（自动定位到错误锚点周围 200 行）
- **Similar Errors**：近 30 天内相同签名的错误有多少次（点击展开所有相关 run）
- **Model + Cost + Signature**：元信息
- **Re-run with Deep Analysis**：用更强的模型（`DIAGNOSE_DEEP_MODEL`）再分析一次

### 自动诊断（可选）

当仓库配置了 webhook 并收到 `workflow_run` 失败事件时，后端自动触发诊断。受以下控制：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DIAGNOSE_AUTO_ON_WEBHOOK` | `true` | 总开关 |
| `DIAGNOSE_SAMPLE_RATE` | `1.0` | 采样率 0.0–1.0 |
| `DIAGNOSE_BUDGET_USD_DAY` | `1.0` | 日预算上限（超限后自动暂停，手动调用不受影响） |
| `DIAGNOSE_SIGNATURE_TTL_HOURS` | `24` | 相同错误签名去重时间窗 |

### 三层缓存策略

1. **精确缓存**：同一 `(repo, run_id, run_attempt, tier)` 永久命中（run 是不可变的）
2. **签名缓存**：同样的错误在 24 小时内跨仓库复用诊断（不再调 LLM）
3. **新鲜调用**：前两层 miss 时才真正调模型

刷新页面 / 分享 URL 也能恢复到同样的视图（状态完全反映在 URL query 中）。

### API 用法（跳过前端）

```bash
# 单次诊断
curl -X POST http://localhost:8000/api/ci-runs/diagnose \
  -H 'Content-Type: application/json' \
  -d '{"repo":"owner/name","run_id":12345,"tier":"default"}'

# 查询相同错误签名的所有 run
curl "http://localhost:8000/api/diagnoses/by-signature/<12char-sig>?days=30"

# 列出仓库最近失败的 run（供 picker 使用）
curl "http://localhost:8000/api/repos/owner/name/failed-runs?limit=20"
```

详细设计见 [Failure Triage 设计文档](../../design/failure-triage.md)。

---

## 6. Skills — 技能管理

![Skills Page](../../screenshots/06-skills.png)

Skills 页面展示所有已加载的分析技能（内置 + 用户安装），每个卡片显示：
- 维度（颜色编码）
- 来源（builtin / user）
- 技能名、描述
- 优先级、数据源依赖数

### 安装新技能

点击右上角 **+ Install Skill** 打开安装弹窗：

![Install Modal](../../screenshots/07-install-modal.png)

支持四种来源：

| 来源 | 输入格式 | 说明 |
|------|---------|------|
| **GitHub repository** | `gh:owner/repo` 或完整 URL | 自动 clone（depth=1）+ 解析 SKILL.md |
| **Claude Code skill** | 技能名称 | 从 `~/.claude/skills/<name>/` 导入 |
| **OpenCode skill** | 技能名称 | 从 `~/.config/opencode/skills/<name>/` 导入 |
| **Local directory** | 绝对路径 | 从任意本地目录导入 |

**必填字段**：
- **Dimension** — ci-agent 特有字段，外部技能格式没有，需要手动指定
- **Data Requirements** — 勾选技能需要的预获取数据（默认 workflows）

安装后自动 reload registry，新技能立刻可用。

### 查看技能详情

![Skill Detail](../../screenshots/08-skill-detail.png)

点击卡片打开右侧抽屉，显示完整信息：
- 元数据（维度、来源、优先级、启用状态）
- 工具列表（Read / Glob / Grep 等）
- 数据依赖（workflows / jobs / action_shas 等）
- 完整 prompt 文本（可滚动查看）
- user 来源的技能显示 **Uninstall** 按钮

---

## 7. CLI 命令参考

### 分析

```bash
# 分析 GitHub 仓库
ci-agent analyze owner/repo

# 指定技能
ci-agent analyze owner/repo --skills security,efficiency

# 指定时间范围
ci-agent analyze owner/repo --since 2026-01-01 --until 2026-04-01

# 输出 JSON 格式
ci-agent analyze owner/repo --format json -o report.json
```

### 技能管理

```bash
# 列出所有技能
ci-agent skills list

# 查看技能详情
ci-agent skills show security-analyst

# 校验 SKILL.md
ci-agent skills validate ./my-skill-dir

# 从 Claude Code 导入技能
ci-agent skills import --from claude-code k8s-analyzer --dimension security

# 从 OpenCode 导入技能
ci-agent skills import --from opencode my-skill --dimension efficiency

# 从本地目录导入
ci-agent skills import --from path ./skill-dir --dimension cost

# 从 GitHub 安装
ci-agent skills install gh:someone/ci-agent-skill-k8s --dimension security

# 卸载用户技能
ci-agent skills uninstall my-skill

# 热重载（通知运行中的 API 服务）
ci-agent skills reload
```

### 服务器

```bash
# 启动 API 服务
ci-agent serve
ci-agent serve --port 9000
```

### 配置

```bash
# 查看当前配置
ci-agent config show

# 设置模型
ci-agent config set model claude-sonnet-4-20250514

# 设置 provider
ci-agent config set provider openai

# 设置语言
ci-agent config set language zh
```

---

## 8. 配置

### 环境变量（`.env`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CI_AGENT_PROVIDER` | AI 引擎 (`anthropic` / `openai`) | `anthropic` |
| `CI_AGENT_MODEL` | 模型名称 | `claude-sonnet-4-20250514` |
| `CI_AGENT_BASE_URL` | OpenAI 兼容端点 | — |
| `CI_AGENT_LANGUAGE` | 输出语言 (`en` / `zh`) | `en` |
| `OPENAI_API_KEY` | OpenAI API Key | — |
| `ANTHROPIC_API_KEY` | Anthropic API Key | — |
| `GITHUB_TOKEN` | GitHub Personal Access Token | — |

### 自定义技能

创建 `~/.ci-agent/skills/<name>/SKILL.md`：

```markdown
---
name: my-custom-skill
description: My custom analysis skill
dimension: security          # 必填：efficiency / security / cost / errors / 自定义
tools:
  - Read
  - Glob
  - Grep
requires_data:
  - workflows                # 可选：workflows / runs / jobs / logs / usage_stats / action_shas
enabled: true
priority: 100
---

Your analysis prompt here...
```

User skills 会覆盖同名的 builtin skills。修改后运行 `ci-agent skills reload` 或在 Web UI 点击 Reload 按钮即可生效。

---

## 架构概览

```
┌──────────────────────────────────────────────────────┐
│                   Web UI (Next.js)                   │
│  Dashboard  │  Analyze  │  Reports  │  Skills        │
└─────────────────────┬────────────────────────────────┘
                      │ REST API
┌─────────────────────▼────────────────────────────────┐
│                FastAPI Backend                        │
│                                                      │
│  ┌─────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Prefetch│──│ Orchestrator │──│ SkillRegistry  │  │
│  │ (GitHub)│  │              │  │ (SKILL.md scan)│  │
│  └────┬────┘  └──┬───────┬───┘  └────────────────┘  │
│       │          │       │                           │
│       │    ┌─────▼─┐  ┌──▼──────┐                   │
│       │    │Anthropic│  │ OpenAI  │                   │
│       │    │ Engine │  │ Engine  │                   │
│       │    └────────┘  └─────────┘                   │
│       │                                              │
│  ┌────▼──────────────────────────────────────────┐   │
│  │  SQLite DB (reports, findings, repositories)  │   │
│  └───────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```
