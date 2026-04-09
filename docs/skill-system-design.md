# Skill System 设计文档

## 概述

将 ci-agent 的分析维度从「Python 代码中的硬编码对象」改为「文件系统中的声明式 Skill 定义」，实现分析能力的动态发现、按需加载和用户可扩展。

### 驱动力

当前 4 个 Specialist Agent（efficiency / security / cost / errors）存在三个问题：

1. **不可扩展** — 新增一个分析维度需要改动 6 处文件（新 `.py`、两个引擎的注册 dict、orchestrator prompt、解析逻辑、前端 Tab）
2. **知识固化** — 分析检查点硬编码在 Python 文件中，非开发者无法更新
3. **引擎不统一** — Anthropic Engine 用 `AgentDefinition`，OpenAI Engine 用 `PROMPT_STRING`，同一个 Specialist 的定义散落在不同位置

### 设计目标

- 短期：开发者可维护 — prompt 与代码解耦，新增维度只需一个 `SKILL.md` 文件
- 长期：用户可扩展 — 最终用户在 `~/.ci-agent/skills/` 下创建自定义 Skill，零代码改动

### 方案选型

采用**混合模式**：Markdown 为主，Python 为可选扩展。

- 阶段 1：只实现 Markdown 驱动，覆盖 90% 场景
- 阶段 2：加入 Python hooks，覆盖高级场景（动态 prompt、数据预处理）

### 关键澄清：Skill ≠ 取消子 Agent

Skill System **不改变运行时的子 Agent 架构**，只改变子 Agent 的定义来源。

```
改前: 子 Agent 定义硬编码在 Python 文件中
  efficiency.py  →  AgentDefinition(prompt=..., tools=[...])
  security.py    →  AgentDefinition(prompt=..., tools=[...])
  cost.py        →  AgentDefinition(prompt=..., tools=[...])
  errors.py      →  AgentDefinition(prompt=..., tools=[...])

改后: 子 Agent 定义从 SKILL.md 文件动态加载
  skills/efficiency/SKILL.md  →  SkillRegistry 解析  →  AgentDefinition(...)
  skills/security/SKILL.md    →  SkillRegistry 解析  →  AgentDefinition(...)
  skills/cost/SKILL.md        →  SkillRegistry 解析  →  AgentDefinition(...)
  skills/errors/SKILL.md      →  SkillRegistry 解析  →  AgentDefinition(...)
```

**运行时行为完全不变**：

- **Anthropic Engine**：Orchestrator 仍通过 `Agent` tool 调度 N 个子 Agent，每个子 Agent 仍拥有独立的 Agentic Loop（自主决定读哪些文件、搜索什么关键字、调用几次工具）
- **OpenAI Engine**：仍并行调用 N 个 specialist chat completion，然后合成报告
- **Orchestrator**：仍综合 N 份子 Agent 报告为统一 JSON

原来的 `.py` 文件中除了 prompt 字符串和一行 `AgentDefinition(...)` 构造外没有其他逻辑，因此迁移到 SKILL.md 是无损的。Skill 是子 Agent 的**声明式定义**，不是子 Agent 的替代品。

---

## 目录结构

```
ci-agent/
├── skills/                          # 内置 Skill（随代码发布）
│   ├── efficiency/
│   │   └── SKILL.md
│   ├── security/
│   │   └── SKILL.md
│   ├── cost/
│   │   └── SKILL.md
│   └── errors/
│       └── SKILL.md
│
~/.ci-agent/skills/                  # 用户自定义 Skill
    └── reliability/
        ├── SKILL.md
        └── hooks.py                 # 可选，阶段 2
```

**发现顺序**：内置目录 → 用户目录。用户 Skill 同名时覆盖内置版本（允许用户 fork 并定制内置 Skill）。

---

## SKILL.md 格式

```markdown
---
name: security-analyst
description: Analyzes CI pipeline security vulnerabilities and best practices
dimension: security
enabled: true
priority: 100
tools:
  - Read
  - Glob
  - Grep
requires_data:
  - workflows
---

You are a CI pipeline security specialist...

## Analysis Dimensions

1. **Permissions**: ...
2. **Action Version Pinning**: ...

## Instructions

1. Read each workflow YAML file
2. ...

## Output Format

(如果省略，系统自动追加全局 FINDING_JSON_FORMAT)
```

### 字段说明

| 字段 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | 是 | — | Skill 唯一标识，也是 Agent 名称 |
| `description` | 是 | — | 一句话描述，用于 Orchestrator prompt 和 CLI 展示 |
| `dimension` | 是 | — | 报告中的维度 key（如 `security`、`cost`） |
| `enabled` | 否 | `true` | 设为 `false` 可禁用 |
| `priority` | 否 | `100` | 数字越大优先级越高，同名时高优先级覆盖低优先级 |
| `tools` | 否 | `["Read", "Glob", "Grep"]` | Anthropic Engine 给 Agent 的工具列表 |
| `requires_data` | 否 | `["workflows"]` | 声明需要的预取数据类型 |

### requires_data 可选值

| 值 | 数据来源 | 说明 |
|---|---------|------|
| `workflows` | 本地 `.github/workflows/*.yml` | 始终可用，无需 API 调用 |
| `runs` | GitHub API `list_workflow_runs` | CI 运行历史 |
| `jobs` | GitHub API `get_run_jobs` | Job 详情（耗时、Runner、Step） |
| `logs` | GitHub API `get_run_logs` | 失败 run 的日志 |
| `usage_stats` | 本地计算（隐式依赖 runs + jobs，系统自动补全） | 使用率统计 |

---

## 架构设计

### 整体流程

```
┌─────────── 用户入口 ────────────────────────────────┐
│  CLI: ci-agent analyze owner/repo --skills sec,cost  │
│  API: POST /api/analyze { skills: ["security"] }     │
└──────────────────────┬──────────────────────────────┘
                       ▼
              ┌─────────────────┐
              │  SkillRegistry  │
              │                 │
              │  1. 扫描 skills/  (内置)
              │  2. 扫描 ~/.ci-agent/skills/  (用户)
              │  3. 解析 SKILL.md → Skill 对象
              │  4. 合并去重（用户覆盖内置）
              │  5. 按 --skills 过滤
              └────────┬────────┘
                       │
          get_active_skills()
                       │
          ┌────────────┼────────────────┐
          ▼            ▼                ▼
  collect_required   build_orchestrator  to_agent_defs /
  _data(skills)      _prompt(skills)    to_specialist_prompts
          │            │                │
          ▼            │                │
  prepare_context      │                │
  (按需 prefetch)      │                │
          │            │                │
          └────────────┼────────────────┘
                       ▼
              ┌─────────────────┐
              │   Orchestrator  │
              │  (动态 N 个维度) │
              └────────┬────────┘
                       │
         ┌─────────────┼──────────────┐
         ▼             ▼              ▼
    config.provider="anthropic"  config.provider="openai"
         │             │              │
         ▼             │              ▼
  AgentDefinition      │      _call_specialist(
    per skill          │        prompt=skill.prompt,
    tools=skill.tools  │        context=按requires_data组装)
    Agent自主读文件     │      one-shot streaming
         │             │              │
         └─────────────┼──────────────┘
                       ▼
              _parse_result()
              (已是动态遍历 dimensions)
                       │
                       ▼
              DB Store + Report
```

### 双引擎适配

两个引擎消费 Skill 的方式不同，这是当前的既有差异，Skill 系统保持兼容：

```
SKILL.md 字段         Anthropic Engine        OpenAI Engine
─────────────────────────────────────────────────────────────
prompt                → AgentDefinition.prompt  → system message
description           → AgentDefinition.desc    → (Orchestrator 合成用)
tools                 → AgentDefinition.tools   → 忽略（无 tool use）
requires_data         → 按需 prefetch            → 决定注入哪些数据到 context
```

`requires_data` 对 OpenAI Engine 是改进：当前 `_build_context_text()` 全量塞入所有数据，改造后按 Skill 声明按需组装，减少 token 消耗。

```python
# OpenAI Engine: 按 requires_data 组装 context
def _build_context_for_skill(ctx: AnalysisContext, requires: list[str]) -> str:
    parts = []
    if "workflows" in requires:
        for wf in ctx.workflow_files:
            parts.append(f"--- {wf.name} ---\n{wf.read_text()}")
    if "jobs" in requires and ctx.jobs_json_path:
        jobs_text = ctx.jobs_json_path.read_text()
        if len(jobs_text) > 30000:
            jobs_text = jobs_text[:30000] + "\n... (truncated)"
        parts.append(f"--- Jobs Data ---\n{jobs_text}")
    if "logs" in requires and ctx.logs_json_path:
        logs_text = ctx.logs_json_path.read_text()
        if len(logs_text) > 20000:
            logs_text = logs_text[:20000] + "\n... (truncated)"
        parts.append(f"--- Failure Logs ---\n{logs_text}")
    if "usage_stats" in requires and ctx.usage_stats_json_path:
        parts.append(f"--- Usage Statistics ---\n{ctx.usage_stats_json_path.read_text()}")
    return "\n\n".join(parts)
```

---

## 核心组件：SkillRegistry

### Skill 数据模型

```python
@dataclass
class Skill:
    name: str                          # "security-analyst"
    description: str                   # 一句话描述
    dimension: str                     # "security"
    prompt: str                        # SKILL.md body 部分
    tools: list[str]                   # ["Read", "Glob", "Grep"]
    requires_data: list[str]           # ["workflows", "jobs", "logs"]
    enabled: bool = True
    priority: int = 100
    source: str = "builtin"            # "builtin" | "user"
    source_path: Path | None = None    # SKILL.md 文件路径

    def to_agent_definition(self, model: str | None = None) -> AgentDefinition:
        """转换为 Claude Agent SDK 的 AgentDefinition."""
        kwargs = dict(
            description=self.description,
            prompt=self.prompt,
            tools=self.tools,
        )
        if model:
            kwargs["model"] = model
        return AgentDefinition(**kwargs)
```

### SkillRegistry 核心逻辑

```python
class SkillRegistry:
    BUILTIN_DIR = Path(__file__).parent.parent.parent.parent / "skills"
    USER_DIR = Path.home() / ".ci-agent" / "skills"

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def load(self) -> "SkillRegistry":
        """扫描内置 + 用户目录，用户同名覆盖内置."""
        self._load_dir(self.BUILTIN_DIR, source="builtin")
        self._load_dir(self.USER_DIR, source="user")
        return self

    def _load_dir(self, base: Path, source: str):
        if not base.exists():
            return
        for skill_dir in sorted(base.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                skill = self._parse_skill_md(skill_file, source)
                errors = self._validate_skill(skill)
                if errors:
                    logger.warning(f"Skipped skill {skill_file}: {errors}")
                    continue
                if skill.name not in self._skills or source == "user":
                    self._skills[skill.name] = skill
            except Exception as e:
                logger.warning(f"Failed to parse {skill_file}: {e}")

    def _parse_skill_md(self, path: Path, source: str) -> Skill:
        """解析 SKILL.md: YAML frontmatter + body."""
        text = path.read_text()
        _, fm_raw, body = text.split("---", 2)
        meta = yaml.safe_load(fm_raw)

        prompt = body.strip()
        if "## Output Format" not in prompt:
            prompt += "\n\n" + FINDING_JSON_FORMAT

        return Skill(
            name=meta["name"],
            description=meta["description"],
            dimension=meta["dimension"],
            prompt=prompt,
            tools=meta.get("tools", ["Read", "Glob", "Grep"]),
            requires_data=meta.get("requires_data", ["workflows"]),
            enabled=meta.get("enabled", True),
            priority=meta.get("priority", 100),
            source=source,
            source_path=path,
        )

    def _validate_skill(self, skill: Skill) -> list[str]:
        """校验 Skill 定义，返回错误列表."""
        errors = []
        if not skill.name:
            errors.append("missing 'name'")
        if not skill.dimension:
            errors.append("missing 'dimension'")
        if not skill.prompt.strip():
            errors.append("empty prompt body")
        valid_data = {"workflows", "runs", "jobs", "logs", "usage_stats"}
        invalid = set(skill.requires_data) - valid_data
        if invalid:
            errors.append(f"unknown requires_data: {invalid}")
        return errors

    def get_active_skills(
        self, selected: list[str] | None = None
    ) -> list[Skill]:
        """返回激活的 Skill 列表.

        selected: CLI --skills 指定的维度名列表，None 表示全部.
        """
        skills = [s for s in self._skills.values() if s.enabled]
        if selected:
            skills = [s for s in skills if s.dimension in selected]
        return sorted(skills, key=lambda s: s.priority, reverse=True)

    def collect_required_data(self, skills: list[Skill]) -> set[str]:
        """合并所有活跃 Skill 的 requires_data."""
        result = set()
        for s in skills:
            result.update(s.requires_data)
        return result

    def build_orchestrator_prompt(self, skills: list[Skill]) -> str:
        """动态生成 Orchestrator prompt，包含所有活跃维度."""
        dim_list = "\n".join(
            f"{i+1}. **{s.dimension}**: {s.description}"
            for i, s in enumerate(skills)
        )
        agent_list = "\n".join(
            f"   - **{s.name}**: {s.description}"
            for s in skills
        )
        dim_schema = "\n".join(
            f'    "{s.dimension}": {{ "findings": [...] }},'
            for s in skills
        )

        return f"""You are a CI pipeline analysis orchestrator. Your role is to \
coordinate {len(skills)} specialist agents to produce a comprehensive analysis report.

## Dimensions
{dim_list}

## Your Workflow

1. Call ALL {len(skills)} specialist agents to analyze the CI pipeline:
{agent_list}

2. After receiving all specialist reports, synthesize them into a unified analysis.

3. Produce your final output as a JSON object with this structure:

```json
{{
  "executive_summary": "Top 5 most impactful recommendations across all dimensions, ordered by priority",
  "dimensions": {{
{dim_schema}
  }},
  "stats": {{
    "total_findings": 0,
    "critical": 0,
    "major": 0,
    "minor": 0,
    "info": 0
  }}
}}
```

## Important

- Call all {len(skills)} specialists. Do not skip any dimension.
- Each specialist will return findings in JSON format. Include them as-is in the dimensions section.
- The executive_summary should identify cross-cutting themes and prioritize the TOP 5 actions by impact.
- Add a "dimension" field to each finding if not already present.
"""
```

---

## 引擎层改造

### anthropic_engine.py

```python
# 改前 — 硬编码
from ci_optimizer.agents.efficiency import efficiency_agent
from ci_optimizer.agents.security import security_agent
from ci_optimizer.agents.cost import cost_agent
from ci_optimizer.agents.errors import error_agent

AGENTS = {
    "efficiency-analyst": efficiency_agent,
    "security-analyst": security_agent,
    "cost-analyst": cost_agent,
    "error-analyst": error_agent,
}

ORCHESTRATOR_PROMPT = """硬编码文本..."""

# 改后 — 从 registry 动态获取
async def run_analysis_anthropic(
    ctx: AnalysisContext, config: AgentConfig, skills: list[Skill]
) -> AnalysisResult:
    agents = {s.name: s.to_agent_definition(config.model) for s in skills}
    orchestrator_prompt = registry.build_orchestrator_prompt(skills)
    # ... 其余逻辑不变
```

### openai_engine.py

```python
# 改前 — 硬编码
SPECIALISTS = {
    "efficiency": EFFICIENCY_PROMPT,
    "security": SECURITY_PROMPT,
    "cost": COST_PROMPT,
    "error": ERRORS_PROMPT,
}

# 改后 — 从 skills 动态获取
async def run_analysis_openai(
    ctx: AnalysisContext, config: AgentConfig, skills: list[Skill]
) -> AnalysisResult:
    # 每个 skill 按 requires_data 组装独立 context
    tasks = [
        _run_specialist(
            client, model, s.dimension, s.prompt,
            _build_context_for_skill(ctx, s.requires_data), language
        )
        for s in skills
    ]
    results = await asyncio.gather(*tasks)
    # ... 合成逻辑不变
```

### orchestrator.py

```python
# run_analysis 新增 registry 初始化
async def run_analysis(
    ctx: AnalysisContext,
    config: AgentConfig | None = None,
    selected_skills: list[str] | None = None,
) -> AnalysisResult:
    if config is None:
        config = AgentConfig.load()

    registry = SkillRegistry().load()
    skills = registry.get_active_skills(selected=selected_skills)

    if not skills:
        raise RuntimeError("No active skills found. Check skills/ directory.")

    if config.provider == "openai":
        from ci_optimizer.agents.openai_engine import run_analysis_openai
        return await run_analysis_openai(ctx, config, skills)
    else:
        from ci_optimizer.agents.anthropic_engine import run_analysis_anthropic
        return await run_analysis_anthropic(ctx, config, skills)
```

---

## Prefetch 按需加载

改造 `prepare_context` 支持 `required_data` 参数：

```python
async def prepare_context(
    resolved: ResolvedInput,
    filters: AnalysisFilters | None = None,
    required_data: set[str] | None = None,
) -> AnalysisContext:
    """Pre-fetch data needed for analysis.

    required_data: 需要的数据类型集合。
      None = 全量获取（向后兼容）。
      可选值: {"workflows", "runs", "jobs", "logs", "usage_stats"}
    """
    ctx = AnalysisContext(...)

    # workflows 始终收集（本地文件，无 API 调用）
    workflows_dir = resolved.local_path / ".github" / "workflows"
    if workflows_dir.exists():
        ctx.workflow_files = sorted(...)

    # 以下按需获取
    # 隐式依赖: usage_stats 需要 runs + jobs 数据来计算，系统自动补全
    need_all = required_data is None
    need_usage = need_all or "usage_stats" in required_data
    need_runs = need_all or "runs" in required_data or "jobs" in required_data or need_usage
    need_jobs = need_all or "jobs" in required_data or need_usage
    need_logs = need_all or "logs" in required_data

    if ctx.owner and ctx.repo:
        client = GitHubClient()
        try:
            if need_runs:
                runs = await client.list_workflow_runs(...)
                ctx.runs_json_path = _write_temp_json(runs, "runs")

            if need_jobs:
                # fetch jobs...
                ctx.jobs_json_path = _write_temp_json(all_jobs, "jobs")

            if need_usage and runs and all_jobs:
                usage_stats = _compute_usage_stats(runs, all_jobs)
                ctx.usage_stats_json_path = _write_temp_json(usage_stats, "usage")

            if need_logs:
                # fetch failure logs...
                ctx.logs_json_path = _write_temp_json(logs, "logs")
        finally:
            await client.close()

    return ctx
```

---

## CLI 集成

### 新增 --skills 参数

```bash
# 运行所有 Skill（默认）
ci-agent analyze owner/repo

# 只运行指定维度
ci-agent analyze owner/repo --skills security,cost
```

### 新增 skills 子命令

```bash
# 列出所有已发现的 Skill
$ ci-agent skills list
  DIMENSION     NAME                 SOURCE   ENABLED  PRIORITY
  efficiency    efficiency-analyst   builtin  true     100
  security      security-analyst     builtin  true     100
  cost          cost-analyst         builtin  true     100
  errors        error-analyst        builtin  true     100
  reliability   reliability-analyst  user     true     90

# 查看某个 Skill 详情
$ ci-agent skills show security-analyst
  Name:          security-analyst
  Description:   Analyzes CI pipeline security vulnerabilities and best practices
  Dimension:     security
  Source:        builtin (skills/security/SKILL.md)
  Tools:         Read, Glob, Grep
  Requires Data: workflows
  Enabled:       true
  Priority:      100
```

### API 集成

`AnalyzeRequest` 新增 `skills` 字段：

```python
# schemas.py
class AnalyzeRequest(BaseModel):
    repo: str
    skills: list[str] | None = None  # 维度名列表，None = 全部
    # ... 其余字段不变
```

---

## 前端适配

### ReportTabs 动态化

```typescript
// 改前: 硬编码 4 个 Tab
const TABS = ["efficiency", "security", "cost", "error"]

// 改后: 从报告数据动态获取
const dimensions = Object.keys(report.dimensions)
// → ["efficiency", "security", "cost", "error", "reliability"]
```

### Analyze 页面

Skills 过滤面板（可选增强）：

```
┌─────────────────────────────────┐
│  Analysis Dimensions            │
│  ☑ Efficiency  ☑ Security      │
│  ☑ Cost        ☑ Errors        │
│  ☑ Reliability (user)          │
└─────────────────────────────────┘
```

---

## 内置 Skill 迁移

将现有 4 个 Python 文件迁移为 SKILL.md：

| 原文件 | 迁移到 | requires_data |
|--------|--------|--------------|
| `agents/efficiency.py` | `skills/efficiency/SKILL.md` | `workflows, jobs, usage_stats` |
| `agents/security.py` | `skills/security/SKILL.md` | `workflows` |
| `agents/cost.py` | `skills/cost/SKILL.md` | `workflows, jobs, usage_stats` |
| `agents/errors.py` | `skills/errors/SKILL.md` | `workflows, jobs, logs, usage_stats` |

迁移后原 Python 文件删除。`agents/prompts.py` 保留 `FINDING_JSON_FORMAT` 和 `LANGUAGE_INSTRUCTIONS`（全局共享）。

---

## 用户自定义示例

### 新增分析维度

```bash
mkdir -p ~/.ci-agent/skills/reliability
```

`~/.ci-agent/skills/reliability/SKILL.md`:

```markdown
---
name: reliability-analyst
description: Analyzes CI pipeline reliability, flaky tests, and retry patterns
dimension: reliability
priority: 90
requires_data:
  - workflows
  - jobs
  - usage_stats
---

You are a CI pipeline reliability specialist. Analyze workflow
reliability patterns and identify flaky behavior.

## Analysis Dimensions

1. **Flaky Tests**: Jobs that intermittently fail on the same commit.
   Look at per_job success rates — jobs with 60-95% success rate are likely flaky.

2. **Retry Patterns**: Are retry-on-error or re-run behaviors used?
   Could continue-on-error + retry action improve reliability?

3. **Timeout Configuration**: Are timeout-minutes set appropriately?
   Check slowest_steps data for jobs that might hang.

4. **Concurrency Guards**: Is concurrency used to prevent conflicting runs?
   Are deployments serialized properly?

## Instructions

1. Read each workflow YAML file
2. Read usage statistics for per-job success rates and slowest steps
3. Identify jobs with success rate between 60-95% as flaky candidates
4. For each finding, provide exact code and suggested fix
5. Output findings as JSON
```

### 覆盖内置 Skill

```bash
mkdir -p ~/.ci-agent/skills/security
```

创建 `~/.ci-agent/skills/security/SKILL.md`，`name: security-analyst` 与内置同名，`source=user` 自动覆盖内置版本。可在内置 prompt 基础上追加公司内部合规规则。

---

## 错误处理

### Skill 加载阶段

| 场景 | 处理 |
|------|------|
| SKILL.md 解析失败（YAML 格式错误 / 缺少必需字段） | 跳过该 Skill，`logger.warning`，不影响其他 Skill |
| 用户 skills 目录不存在 | 静默跳过（正常情况） |
| 零个 Skill 被加载 | 抛出 `RuntimeError("No active skills found")` |
| `requires_data` 包含未知值 | 校验失败，跳过该 Skill |

### 运行阶段

| 场景 | 处理 |
|------|------|
| 单个 Specialist 分析失败 | 与当前行为一致：其他 Specialist 不受影响，报告展示部分结果 |
| Orchestrator 合成失败（OpenAI Engine） | 触发 `_fallback_combine`，直接拼接各 Specialist 结果 |

---

## 文件变更清单

### 新增

| 文件 | 说明 |
|------|------|
| `src/ci_optimizer/agents/skill_registry.py` | SkillRegistry + Skill 数据类 |
| `skills/efficiency/SKILL.md` | 迁移自 `efficiency.py` |
| `skills/security/SKILL.md` | 迁移自 `security.py` |
| `skills/cost/SKILL.md` | 迁移自 `cost.py` |
| `skills/errors/SKILL.md` | 迁移自 `errors.py` |

### 修改

| 文件 | 改动 |
|------|------|
| `agents/anthropic_engine.py` | AGENTS 从 registry 获取，删除硬编码 import |
| `agents/openai_engine.py` | SPECIALISTS 从 registry 获取，新增 `_build_context_for_skill` |
| `agents/orchestrator.py` | `run_analysis` 初始化 registry，新增 `selected_skills` 参数 |
| `agents/prompts.py` | 保留 `FINDING_JSON_FORMAT` + `LANGUAGE_INSTRUCTIONS`，删除 `ORCHESTRATOR_PROMPT` |
| `prefetch.py` | `prepare_context` 新增 `required_data` 参数，按需获取数据 |
| `cli.py` | 新增 `--skills` 参数 + `skills list/show` 子命令 |
| `api/routes.py` | 分析时通过 registry 加载 skill |
| `api/schemas.py` | `AnalyzeRequest` 新增 `skills` 字段 |
| `web/src/app/reports/[id]/ReportTabs.tsx` | Tab 从 dimensions key 动态生成 |

### 删除

| 文件 | 原因 |
|------|------|
| `agents/efficiency.py` | 迁移到 `skills/efficiency/SKILL.md` |
| `agents/security.py` | 迁移到 `skills/security/SKILL.md` |
| `agents/cost.py` | 迁移到 `skills/cost/SKILL.md` |
| `agents/errors.py` | 迁移到 `skills/errors/SKILL.md` |

---

## 阶段规划

### 阶段 1（本次实现）

- SkillRegistry 核心（发现、解析、合并、校验）
- 4 个内置 Skill 迁移为 SKILL.md
- 两个引擎适配（从 registry 获取 Skill）
- Orchestrator prompt 动态生成
- Prefetch 按需加载
- CLI: `--skills` 过滤 + `skills list/show` 子命令
- API: `AnalyzeRequest.skills` 字段
- 前端 Tab 动态化
- 用户 `~/.ci-agent/skills/` 目录支持

### 阶段 2（未来）

- `hooks.py` — Python 数据预处理 / 动态 prompt 生成
- `ci-agent skills install <url>` — 社区 Skill 安装
- Skill 间依赖声明（`depends_on`）
- OpenAI Engine function calling 模式
- Skill 执行结果缓存

### 不引入的新依赖

YAML 解析使用项目已有的 `pyyaml`（`pyproject.toml` 第 10 行），无需新增任何 Python 包。