# Skill System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded specialist agent definitions with a declarative SKILL.md-based skill system that supports dynamic discovery, user customization, and per-skill data requirements.

**Architecture:** A `SkillRegistry` scans `skills/` (builtin) and `~/.ci-agent/skills/` (user) directories for `SKILL.md` files, parses YAML frontmatter + prompt body, and provides `Skill` objects to both engines. Anthropic engine converts skills to `AgentDefinition`; OpenAI engine uses skill prompts as system messages with per-skill context assembly. Orchestrator prompt is dynamically generated from active skills.

**Tech Stack:** Python 3.10+, pyyaml (already in deps), pytest, Claude Agent SDK, OpenAI SDK, Next.js/TypeScript (frontend)

**Spec:** See `docs/skill-system-design.md` for full design details.

---

### Task 1: Skill Data Model + SKILL.md Parser

**Files:**
- Create: `src/ci_optimizer/agents/skill_registry.py`
- Test: `tests/test_skill_registry.py`

- [ ] **Step 1: Write failing tests for Skill dataclass and SKILL.md parsing**

```python
# tests/test_skill_registry.py
"""Tests for the skill registry: parsing, validation, loading."""

import textwrap
from pathlib import Path

import pytest

from ci_optimizer.agents.skill_registry import Skill, SkillRegistry


class TestSkillParsing:
    """Test SKILL.md file parsing."""

    def test_parse_valid_skill(self, tmp_path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: test-analyst
            description: A test specialist
            dimension: testing
            enabled: true
            priority: 100
            tools:
              - Read
              - Glob
            requires_data:
              - workflows
              - jobs
            ---

            You are a test specialist.

            ## Analysis Dimensions

            1. **Tests**: Check test coverage.

            ## Instructions

            Analyze the workflows.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        skills = registry.get_active_skills()

        assert len(skills) == 1
        s = skills[0]
        assert s.name == "test-analyst"
        assert s.description == "A test specialist"
        assert s.dimension == "testing"
        assert s.tools == ["Read", "Glob"]
        assert s.requires_data == ["workflows", "jobs"]
        assert s.enabled is True
        assert s.priority == 100
        assert "You are a test specialist" in s.prompt
        assert s.source == "builtin"

    def test_parse_skill_defaults(self, tmp_path):
        """Missing optional fields get defaults."""
        skill_dir = tmp_path / "minimal"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: minimal-analyst
            description: Minimal skill
            dimension: minimal
            ---

            Analyze things.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        skills = registry.get_active_skills()

        assert len(skills) == 1
        s = skills[0]
        assert s.tools == ["Read", "Glob", "Grep"]
        assert s.requires_data == ["workflows"]
        assert s.enabled is True
        assert s.priority == 100

    def test_auto_append_output_format(self, tmp_path):
        """If prompt has no '## Output Format', FINDING_JSON_FORMAT is appended."""
        skill_dir = tmp_path / "no-format"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: noformat-analyst
            description: No output format
            dimension: noformat
            ---

            Just analyze.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        s = registry.get_active_skills()[0]
        assert "## Output Format" in s.prompt

    def test_skip_prompt_with_output_format(self, tmp_path):
        """If prompt already has '## Output Format', don't double-append."""
        skill_dir = tmp_path / "has-format"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: hasformat-analyst
            description: Has format
            dimension: hasformat
            ---

            Analyze.

            ## Output Format

            Custom format here.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        s = registry.get_active_skills()[0]
        assert s.prompt.count("## Output Format") == 1

    def test_skip_invalid_skill(self, tmp_path):
        """Invalid SKILL.md (missing required field) is skipped."""
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: bad-analyst
            ---

            No dimension field.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        assert len(registry.get_active_skills()) == 0

    def test_skip_invalid_requires_data(self, tmp_path):
        """Unknown requires_data values cause skill to be skipped."""
        skill_dir = tmp_path / "bad-data"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: baddata-analyst
            description: Bad data
            dimension: baddata
            requires_data:
              - nonexistent_source
            ---

            Analyze.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        assert len(registry.get_active_skills()) == 0

    def test_disabled_skill_excluded(self, tmp_path):
        """enabled: false skills are excluded from active list."""
        skill_dir = tmp_path / "disabled"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: disabled-analyst
            description: Disabled
            dimension: disabled
            enabled: false
            ---

            Analyze.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        assert len(registry.get_active_skills()) == 0

    def test_nonexistent_directory_silent(self, tmp_path):
        """Nonexistent directories are silently skipped."""
        registry = SkillRegistry(
            builtin_dir=tmp_path / "noexist1",
            user_dir=tmp_path / "noexist2",
        )
        registry.load()
        assert len(registry.get_active_skills()) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_skill_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ci_optimizer.agents.skill_registry'`

- [ ] **Step 3: Implement Skill dataclass and SkillRegistry**

```python
# src/ci_optimizer/agents/skill_registry.py
"""Skill registry — discovers, parses, validates, and manages SKILL.md definitions."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ci_optimizer.agents.prompts import FINDING_JSON_FORMAT

logger = logging.getLogger(__name__)

VALID_REQUIRES_DATA = {"workflows", "runs", "jobs", "logs", "usage_stats"}

# Default paths
_BUILTIN_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills"
_USER_DIR = Path.home() / ".ci-agent" / "skills"


@dataclass
class Skill:
    """A single analysis skill parsed from SKILL.md."""

    name: str
    description: str
    dimension: str
    prompt: str
    tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    requires_data: list[str] = field(default_factory=lambda: ["workflows"])
    enabled: bool = True
    priority: int = 100
    source: str = "builtin"
    source_path: Path | None = None

    def to_agent_definition(self, model: str | None = None):
        """Convert to Claude Agent SDK AgentDefinition."""
        from claude_agent_sdk import AgentDefinition

        kwargs = dict(
            description=self.description,
            prompt=self.prompt,
            tools=self.tools,
        )
        if model:
            kwargs["model"] = model
        return AgentDefinition(**kwargs)


class SkillRegistry:
    """Discovers and manages skills from builtin and user directories."""

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
    ):
        self._builtin_dir = builtin_dir or _BUILTIN_DIR
        self._user_dir = user_dir or _USER_DIR
        self._skills: dict[str, Skill] = {}

    def load(self) -> "SkillRegistry":
        """Scan builtin + user directories. User skills override builtin by name."""
        self._skills.clear()
        self._load_dir(self._builtin_dir, source="builtin")
        self._load_dir(self._user_dir, source="user")
        return self

    def _load_dir(self, base: Path, source: str):
        if not base.exists():
            return
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                skill = self._parse_skill_md(skill_file, source)
                errors = self._validate_skill(skill)
                if errors:
                    logger.warning("Skipped skill %s: %s", skill_file, errors)
                    continue
                # User skills override builtin with same name
                if skill.name not in self._skills or source == "user":
                    self._skills[skill.name] = skill
            except Exception as e:
                logger.warning("Failed to parse %s: %s", skill_file, e)

    @staticmethod
    def _parse_skill_md(path: Path, source: str) -> Skill:
        """Parse SKILL.md: YAML frontmatter + body."""
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid SKILL.md format: missing frontmatter in {path}")
        meta = yaml.safe_load(parts[1])
        if not isinstance(meta, dict):
            raise ValueError(f"Invalid frontmatter in {path}")

        prompt = parts[2].strip()
        # Auto-append output format if not present
        if "## Output Format" not in prompt:
            prompt += "\n\n" + FINDING_JSON_FORMAT

        return Skill(
            name=meta.get("name", ""),
            description=meta.get("description", ""),
            dimension=meta.get("dimension", ""),
            prompt=prompt,
            tools=meta.get("tools", ["Read", "Glob", "Grep"]),
            requires_data=meta.get("requires_data", ["workflows"]),
            enabled=meta.get("enabled", True),
            priority=meta.get("priority", 100),
            source=source,
            source_path=path,
        )

    @staticmethod
    def _validate_skill(skill: Skill) -> list[str]:
        """Validate skill definition, return list of errors."""
        errors = []
        if not skill.name:
            errors.append("missing 'name'")
        if not skill.dimension:
            errors.append("missing 'dimension'")
        if not skill.prompt.strip():
            errors.append("empty prompt body")
        invalid = set(skill.requires_data) - VALID_REQUIRES_DATA
        if invalid:
            errors.append(f"unknown requires_data: {invalid}")
        return errors

    def get_active_skills(
        self, selected: list[str] | None = None
    ) -> list[Skill]:
        """Return enabled skills, optionally filtered by dimension names."""
        skills = [s for s in self._skills.values() if s.enabled]
        if selected:
            skills = [s for s in skills if s.dimension in selected]
        return sorted(skills, key=lambda s: s.priority, reverse=True)

    def collect_required_data(self, skills: list[Skill]) -> set[str]:
        """Union of all active skills' requires_data."""
        result: set[str] = set()
        for s in skills:
            result.update(s.requires_data)
        return result

    def build_orchestrator_prompt(self, skills: list[Skill]) -> str:
        """Dynamically generate orchestrator prompt from active skills."""
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

        return (
            "You are a CI pipeline analysis orchestrator. Your role is to "
            f"coordinate {len(skills)} specialist agents to produce a "
            "comprehensive analysis report.\n\n"
            f"## Dimensions\n{dim_list}\n\n"
            f"## Your Workflow\n\n"
            f"1. Call ALL {len(skills)} specialist agents to analyze the CI pipeline:\n"
            f"{agent_list}\n\n"
            "2. After receiving all specialist reports, synthesize them into a unified analysis.\n\n"
            "3. Produce your final output as a JSON object with this structure:\n\n"
            "```json\n"
            "{\n"
            '  "executive_summary": "Top 5 most impactful recommendations across all dimensions, ordered by priority",\n'
            '  "dimensions": {\n'
            f"{dim_schema}\n"
            "  },\n"
            '  "stats": {\n'
            '    "total_findings": 0,\n'
            '    "critical": 0,\n'
            '    "major": 0,\n'
            '    "minor": 0,\n'
            '    "info": 0\n'
            "  }\n"
            "}\n"
            "```\n\n"
            "## Important\n\n"
            f"- Call all {len(skills)} specialists. Do not skip any dimension.\n"
            "- Each specialist will return findings in JSON format. Include them as-is in the dimensions section.\n"
            "- The executive_summary should identify cross-cutting themes and prioritize the TOP 5 actions by impact.\n"
            '- Add a "dimension" field to each finding if not already present.\n'
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_skill_registry.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ci_optimizer/agents/skill_registry.py tests/test_skill_registry.py
git commit -m "feat: add Skill dataclass and SkillRegistry with SKILL.md parser"
```

---

### Task 2: User Override + Skill Selection + collect_required_data

**Files:**
- Modify: `tests/test_skill_registry.py`
- (No new source files — extending SkillRegistry from Task 1)

- [ ] **Step 1: Write failing tests for override, selection, and data collection**

```python
# Append to tests/test_skill_registry.py

class TestSkillOverride:
    """Test user skill overrides builtin."""

    def test_user_overrides_builtin(self, tmp_path):
        builtin_dir = tmp_path / "builtin"
        user_dir = tmp_path / "user"

        # Builtin skill
        bd = builtin_dir / "security"
        bd.mkdir(parents=True)
        (bd / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: security-analyst
            description: Builtin security
            dimension: security
            ---

            Builtin prompt.
        """))

        # User skill with same name
        ud = user_dir / "security"
        ud.mkdir(parents=True)
        (ud / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: security-analyst
            description: Custom security with compliance
            dimension: security
            priority: 200
            ---

            Custom prompt with compliance rules.
        """))

        registry = SkillRegistry(builtin_dir=builtin_dir, user_dir=user_dir)
        registry.load()
        skills = registry.get_active_skills()

        assert len(skills) == 1
        assert skills[0].description == "Custom security with compliance"
        assert skills[0].source == "user"
        assert skills[0].priority == 200

    def test_user_adds_new_dimension(self, tmp_path):
        builtin_dir = tmp_path / "builtin"
        user_dir = tmp_path / "user"

        bd = builtin_dir / "security"
        bd.mkdir(parents=True)
        (bd / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: security-analyst
            description: Security
            dimension: security
            ---

            Security prompt.
        """))

        ud = user_dir / "reliability"
        ud.mkdir(parents=True)
        (ud / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: reliability-analyst
            description: Reliability
            dimension: reliability
            requires_data:
              - workflows
              - jobs
            ---

            Reliability prompt.
        """))

        registry = SkillRegistry(builtin_dir=builtin_dir, user_dir=user_dir)
        registry.load()
        skills = registry.get_active_skills()

        assert len(skills) == 2
        dims = {s.dimension for s in skills}
        assert dims == {"security", "reliability"}


class TestSkillSelection:
    """Test --skills filtering."""

    def _make_skills(self, tmp_path, names):
        for name in names:
            d = tmp_path / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(textwrap.dedent(f"""\
                ---
                name: {name}-analyst
                description: {name} analysis
                dimension: {name}
                ---

                Analyze {name}.
            """))

    def test_select_subset(self, tmp_path):
        self._make_skills(tmp_path, ["efficiency", "security", "cost", "errors"])
        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()

        skills = registry.get_active_skills(selected=["security", "cost"])
        dims = [s.dimension for s in skills]
        assert set(dims) == {"security", "cost"}

    def test_select_all_when_none(self, tmp_path):
        self._make_skills(tmp_path, ["efficiency", "security"])
        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()

        skills = registry.get_active_skills(selected=None)
        assert len(skills) == 2


class TestCollectRequiredData:
    """Test requires_data aggregation."""

    def test_collect_union(self, tmp_path):
        d1 = tmp_path / "s1"
        d1.mkdir()
        (d1 / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: s1
            description: S1
            dimension: d1
            requires_data:
              - workflows
            ---

            Prompt 1.
        """))

        d2 = tmp_path / "s2"
        d2.mkdir()
        (d2 / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: s2
            description: S2
            dimension: d2
            requires_data:
              - workflows
              - jobs
              - logs
            ---

            Prompt 2.
        """))

        registry = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        registry.load()
        skills = registry.get_active_skills()
        required = registry.collect_required_data(skills)

        assert required == {"workflows", "jobs", "logs"}
```

- [ ] **Step 2: Run tests to verify they pass (these test existing code from Task 1)**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_skill_registry.py -v`
Expected: All 13 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_skill_registry.py
git commit -m "test: add override, selection, and data collection tests for SkillRegistry"
```

---

### Task 3: Migrate 4 Builtin Skills to SKILL.md

**Files:**
- Create: `skills/efficiency/SKILL.md`
- Create: `skills/security/SKILL.md`
- Create: `skills/cost/SKILL.md`
- Create: `skills/errors/SKILL.md`
- Test: `tests/test_skill_registry.py` (add builtin loading test)

- [ ] **Step 1: Create `skills/efficiency/SKILL.md`**

Copy the prompt from `src/ci_optimizer/agents/efficiency.py` lines 7-27 into SKILL.md format:

```markdown
---
name: efficiency-analyst
description: CI pipeline efficiency specialist. Analyzes parallelization, caching, conditional execution, and matrix optimization opportunities.
dimension: efficiency
tools:
  - Read
  - Glob
  - Grep
requires_data:
  - workflows
  - jobs
  - usage_stats
---

You are a CI pipeline efficiency specialist. Your job is to analyze GitHub Actions workflow files and identify opportunities to reduce execution time.

## Analysis Dimensions

1. **Parallelization**: Are there jobs with unnecessary `needs:` dependencies that could run concurrently? Are independent steps serialized when they could be parallel jobs?

2. **Caching**: Is dependency caching used (actions/cache, setup-node with cache, setup-python with cache, etc.)? Are cache keys optimal (using hash of lock files)? Are build artifacts cached between jobs?

3. **Conditional Execution**: Are path filters used in `on.push.paths` / `on.pull_request.paths`? Could jobs be skipped with `if:` conditions (e.g., skip docs-only changes)? Is `concurrency` used to cancel redundant runs?

4. **Matrix Strategy**: Could duplicated jobs be consolidated into a matrix build? Are matrix combinations optimized (exclude unnecessary combos)?

5. **Step Optimization**: Are there redundant checkout/setup steps? Could steps be combined? Are timeouts set to avoid hanging jobs?

## Instructions

1. Read each workflow YAML file using the Read tool
2. For each finding, quote the EXACT current code and provide replacement code
3. Analyze against the dimensions above
4. Output your findings as a JSON object
```

- [ ] **Step 2: Create `skills/security/SKILL.md`**

Copy prompt from `src/ci_optimizer/agents/security.py` lines 7-29:

```markdown
---
name: security-analyst
description: CI pipeline security specialist. Analyzes permissions, action pinning, secrets management, supply chain security, and injection risks.
dimension: security
tools:
  - Read
  - Glob
  - Grep
requires_data:
  - workflows
---

You are a CI pipeline security specialist. Your job is to analyze GitHub Actions workflow files for security vulnerabilities and best practice violations.

## Analysis Dimensions

1. **Permissions**: Is `permissions:` set at the workflow level? Are permissions minimized (read-only where possible)? Does any job use `permissions: write-all` unnecessarily?

2. **Action Version Pinning**: Are third-party actions pinned to full SHA commits (not tags)? Are official actions (actions/*) at least pinned to major versions? Are there any unpinned actions using `@master` or `@main`?

3. **Secrets Management**: Are secrets properly referenced via `${{ secrets.* }}`? Are there any hardcoded credentials or tokens? Are secrets exposed in logs via `echo` or env dumps? Is `GITHUB_TOKEN` scoped appropriately?

4. **Supply Chain Security**: Are dependency lock files used in install steps? Is `--frozen-lockfile` / `--ci` used? Are there `npm install` without lock files? Are container images pinned by digest?

5. **Injection Risks**: Are there expressions in `run:` steps that could be injected via PR titles/branch names (e.g., `${{ github.event.pull_request.title }}` in a shell command)? Are `pull_request_target` triggers used safely?

6. **Runner Security**: Are self-hosted runners used for public repos (security risk)? Are artifacts cleaned up? Are caches isolated between PRs?

## Instructions

1. Read each workflow YAML file using the Read tool
2. For each finding, quote the EXACT vulnerable code and provide the secure replacement
3. Analyze against the dimensions above
4. Output your findings as a JSON object
```

- [ ] **Step 3: Create `skills/cost/SKILL.md`**

Copy prompt from `src/ci_optimizer/agents/cost.py` lines 7-40:

```markdown
---
name: cost-analyst
description: CI pipeline cost optimization specialist. Analyzes trigger optimization, runner selection, job consolidation, and resource usage to reduce GitHub Actions billing.
dimension: cost
tools:
  - Read
  - Glob
  - Grep
requires_data:
  - workflows
  - jobs
  - usage_stats
---

You are a CI pipeline cost optimization specialist. Your job is to analyze GitHub Actions workflow files and run history to identify ways to reduce GitHub Actions billing.

## Key Facts
- GitHub Actions bills per minute, rounded up per job
- Linux runners: 1x multiplier, macOS: 10x, Windows: 2x
- Larger runners cost more (e.g., ubuntu-latest-16-core)
- Public repos get free Actions minutes; private repos are billed

## Analysis Dimensions

1. **Trigger Optimization**: Are workflows triggered on every push when they could use `pull_request` only? Are there workflows running on branches that don't need CI? Could `paths-ignore` skip unnecessary runs?

2. **Runner Selection**: Are macOS/Windows runners used when Linux would suffice? Are large runners used for lightweight tasks? Could self-hosted runners be more economical for heavy workloads?

3. **Job Consolidation**: Are there redundant jobs doing similar work? Could multiple small jobs be combined into one (reduce startup overhead)? Are there jobs that always run but rarely find issues?

4. **Resource Usage**: Are docker builds using multi-stage builds and caching? Are there large artifact uploads that could be reduced? Are logs/artifacts retained longer than needed?

5. **Run History Analysis**: (If run data is available) What is the average run duration? Which jobs/workflows consume the most minutes? Are there frequently cancelled runs (wasted minutes)?

## Instructions

1. Read each workflow YAML file
2. Read the usage statistics JSON file — it contains pre-computed data:
   - `billing_estimate`: total billed minutes and breakdown by OS
   - `runner_distribution`: count of jobs per runner OS
   - `per_workflow`: per-workflow run count, success rate, avg duration
   - `per_job`: per-job run count, success rate, avg duration, avg queue wait
   - `timing`: avg/max job duration and queue wait times
3. Read the jobs data JSON file for detailed per-run job timing and runner labels
4. For each finding, quote the EXACT current code and provide cost-optimized replacement
5. Analyze against the dimensions above
6. Output findings as JSON
```

- [ ] **Step 4: Create `skills/errors/SKILL.md`**

Copy prompt from `src/ci_optimizer/agents/errors.py` lines 7-44:

```markdown
---
name: error-analyst
description: CI pipeline error analysis specialist. Analyzes failure patterns, root causes, flaky tests, and suggests reliability improvements based on run history and logs.
dimension: errors
tools:
  - Read
  - Glob
  - Grep
requires_data:
  - workflows
  - jobs
  - logs
  - usage_stats
---

You are a CI pipeline error analysis specialist. Your job is to analyze CI run history and failure logs to identify common failure patterns and suggest fixes.

## Analysis Dimensions

1. **Failure Frequency**: Which workflows/jobs fail most often? What is the failure rate over the analyzed period? Are failures increasing or decreasing?

2. **Failure Patterns**: Common categories to look for:
   - Flaky tests (intermittent failures on the same code)
   - Dependency resolution failures (npm/pip install errors)
   - Timeout issues (jobs exceeding time limits)
   - Resource limits (out of memory, disk space)
   - Network issues (API rate limits, download failures)
   - Configuration drift (env vars missing, version mismatches)

3. **Root Cause Analysis**: For the top 3-5 most frequent failures:
   - What is the probable root cause?
   - Is it a code issue, infrastructure issue, or configuration issue?
   - What specific step/job fails?

4. **Recommendations**:
   - Retry strategies for transient failures
   - Timeout adjustments
   - Dependency pinning to avoid resolution failures
   - Test stabilization suggestions

## Instructions

1. Read the workflow YAML files to understand the pipeline structure
2. Read the usage statistics JSON file — it contains pre-computed data:
   - `conclusion_counts`: how many runs ended in success/failure/cancelled
   - `per_workflow`: per-workflow success rate and avg duration
   - `per_job`: per-job success rate, avg duration, avg queue wait
   - `slowest_steps`: top 10 slowest steps with job name and duration
3. Read the jobs data JSON file for per-run job details with step-level timing
4. Read the failure logs JSON file (contains error logs from failed runs)
5. For each finding, quote the EXACT problematic code and provide the fix
6. Analyze patterns and output findings
```

- [ ] **Step 5: Write test to verify builtin skills load from `skills/` directory**

```python
# Append to tests/test_skill_registry.py

class TestBuiltinSkills:
    """Test that real builtin SKILL.md files load correctly."""

    def test_load_builtin_skills(self):
        """Verify all 4 builtin skills load from the project skills/ directory."""
        from ci_optimizer.agents.skill_registry import _BUILTIN_DIR

        registry = SkillRegistry(
            builtin_dir=_BUILTIN_DIR,
            user_dir=Path("/nonexistent"),
        )
        registry.load()
        skills = registry.get_active_skills()

        dims = {s.dimension for s in skills}
        assert dims == {"efficiency", "security", "cost", "errors"}

        names = {s.name for s in skills}
        assert names == {"efficiency-analyst", "security-analyst", "cost-analyst", "error-analyst"}

        for s in skills:
            assert s.source == "builtin"
            assert len(s.prompt) > 100  # non-trivial prompt
            assert s.tools == ["Read", "Glob", "Grep"]
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_skill_registry.py::TestBuiltinSkills -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add skills/
git commit -m "feat: migrate 4 builtin specialist agents to SKILL.md format"
```

---

### Task 4: Wire SkillRegistry into Orchestrator

**Files:**
- Modify: `src/ci_optimizer/agents/orchestrator.py:86-103`
- Modify: `src/ci_optimizer/agents/anthropic_engine.py`
- Modify: `src/ci_optimizer/agents/openai_engine.py`
- Modify: `src/ci_optimizer/agents/prompts.py`

- [ ] **Step 1: Modify orchestrator.py — add `selected_skills` parameter**

In `src/ci_optimizer/agents/orchestrator.py`, replace the `run_analysis` function (lines 86-103):

```python
async def run_analysis(
    ctx: AnalysisContext,
    config: AgentConfig | None = None,
    selected_skills: list[str] | None = None,
) -> AnalysisResult:
    """Run analysis using the configured provider engine.

    Routes to:
      - Anthropic engine (Claude Agent SDK) when provider="anthropic"
      - OpenAI engine (OpenAI SDK) when provider="openai"

    selected_skills: list of dimension names to run, or None for all.
    """
    if config is None:
        config = AgentConfig.load()

    from ci_optimizer.agents.skill_registry import SkillRegistry
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

- [ ] **Step 2: Modify anthropic_engine.py — accept skills parameter**

In `src/ci_optimizer/agents/anthropic_engine.py`:

1. Remove the top-level imports of the 4 agent modules (lines 19-22) and the `AGENTS` dict (lines 68-73) and the `ORCHESTRATOR_PROMPT` (lines 27-66)
2. Modify `run_analysis_anthropic` signature to accept `skills` parameter
3. Build agents and orchestrator prompt from skills

Replace the file content. Key changes:

- Delete: `from ci_optimizer.agents.cost import cost_agent` and similar imports
- Delete: `ORCHESTRATOR_PROMPT = """..."""` (the entire string)
- Delete: `AGENTS = {...}` dict
- Delete: `_build_agents` function
- Modify `run_analysis_anthropic` to accept `skills: list[Skill]` and build agents/prompt from it:

```python
async def run_analysis_anthropic(
    ctx: AnalysisContext, config: AgentConfig, skills: "list[Skill]"
) -> "AnalysisResult":
    """Run analysis using Claude Agent SDK."""
    from ci_optimizer.agents.orchestrator import AnalysisResult
    from ci_optimizer.agents.skill_registry import SkillRegistry

    # Build agents from skills
    agents = {s.name: s.to_agent_definition(config.model) for s in skills}

    # Build orchestrator prompt dynamically
    registry = SkillRegistry()
    orchestrator_prompt = registry.build_orchestrator_prompt(skills)

    prompt = _build_analysis_prompt(ctx, language=config.language)
    start_time = time.time()

    collected_text = []
    result = AnalysisResult()

    lang_instruction = LANGUAGE_INSTRUCTIONS.get(config.language, LANGUAGE_INSTRUCTIONS["en"])
    system_prompt = orchestrator_prompt + lang_instruction

    sdk_options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=["Agent"],
        agents=agents,
        cwd=str(ctx.local_path),
        max_turns=config.max_turns,
    )
    # ... rest unchanged from line 153 onwards
```

- [ ] **Step 3: Modify openai_engine.py — accept skills parameter**

In `src/ci_optimizer/agents/openai_engine.py`:

1. Remove imports of the 4 prompt constants (lines 16-19)
2. Remove the `SPECIALISTS` dict (lines 24-29)
3. Add `_build_context_for_skill` function
4. Modify `_run_analysis_with_client` to accept `skills` and iterate over them

Remove old imports and SPECIALISTS dict. Add new function:

```python
def _build_context_for_skill(ctx: "AnalysisContext", requires: list[str]) -> str:
    """Build context text for a single skill based on its requires_data."""
    parts = []
    if ctx.owner:
        parts.append(f"Repository: {ctx.owner}/{ctx.repo}")
    else:
        parts.append(f"Path: {ctx.local_path}")

    if "workflows" in requires:
        parts.append(f"Workflow files ({len(ctx.workflow_files)}):")
        for wf in ctx.workflow_files:
            parts.append(f"  - {wf.name}")
        for wf in ctx.workflow_files:
            try:
                content = wf.read_text()
                parts.append(f"\n--- {wf.name} ---\n{content}")
            except OSError:
                pass

    if "jobs" in requires and ctx.jobs_json_path and ctx.jobs_json_path.exists():
        try:
            jobs_text = ctx.jobs_json_path.read_text()
            if len(jobs_text) > 30000:
                jobs_text = jobs_text[:30000] + "\n... (truncated)"
            parts.append(f"\n--- Jobs Data ---\n{jobs_text}")
        except OSError:
            pass

    if "usage_stats" in requires and ctx.usage_stats_json_path and ctx.usage_stats_json_path.exists():
        try:
            parts.append(f"\n--- Usage Statistics ---\n{ctx.usage_stats_json_path.read_text()}")
        except OSError:
            pass

    if "logs" in requires and ctx.logs_json_path and ctx.logs_json_path.exists():
        try:
            logs_text = ctx.logs_json_path.read_text()
            if len(logs_text) > 20000:
                logs_text = logs_text[:20000] + "\n... (truncated)"
            parts.append(f"\n--- Failure Logs ---\n{logs_text}")
        except OSError:
            pass

    return "\n".join(parts)
```

Modify function signatures:

```python
async def run_analysis_openai(
    ctx: "AnalysisContext", config: "AgentConfig", skills: "list"
) -> "AnalysisResult":
    # ... pass skills through to _run_analysis_with_client

async def _run_analysis_with_client(
    client, ctx, config, start_time, skills
) -> "AnalysisResult":
    # Replace SPECIALISTS iteration with skills iteration:
    async def _run_specialist(name, prompt, context_text):
        # ... same as before

    results = await asyncio.gather(
        *[
            _run_specialist(
                s.dimension, s.prompt,
                _build_context_for_skill(ctx, s.requires_data)
            )
            for s in skills
        ]
    )
```

- [ ] **Step 4: Clean up prompts.py — remove ORCHESTRATOR_PROMPT**

In `src/ci_optimizer/agents/prompts.py`, delete the `ORCHESTRATOR_PROMPT` constant (lines 56-88). Keep `LANGUAGE_INSTRUCTIONS` and `FINDING_JSON_FORMAT`.

- [ ] **Step 5: Run existing tests to verify nothing is broken**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_e2e.py -x`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/ci_optimizer/agents/orchestrator.py src/ci_optimizer/agents/anthropic_engine.py src/ci_optimizer/agents/openai_engine.py src/ci_optimizer/agents/prompts.py
git commit -m "feat: wire SkillRegistry into both engines, remove hardcoded specialists"
```

---

### Task 5: Delete Old Specialist Python Files

**Files:**
- Delete: `src/ci_optimizer/agents/efficiency.py`
- Delete: `src/ci_optimizer/agents/security.py`
- Delete: `src/ci_optimizer/agents/cost.py`
- Delete: `src/ci_optimizer/agents/errors.py`

- [ ] **Step 1: Delete the 4 files**

```bash
rm src/ci_optimizer/agents/efficiency.py
rm src/ci_optimizer/agents/security.py
rm src/ci_optimizer/agents/cost.py
rm src/ci_optimizer/agents/errors.py
```

- [ ] **Step 2: Verify no remaining imports reference deleted files**

Run: `cd /Users/zhenyu.jiang/ci-agent && grep -r "from ci_optimizer.agents.efficiency\|from ci_optimizer.agents.security\|from ci_optimizer.agents.cost\|from ci_optimizer.agents.errors" src/`
Expected: No output (no remaining references)

- [ ] **Step 3: Run all tests**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_e2e.py -x`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add -u src/ci_optimizer/agents/
git commit -m "refactor: delete old hardcoded specialist agent Python files"
```

---

### Task 6: Prefetch On-Demand Loading

**Files:**
- Modify: `src/ci_optimizer/prefetch.py:228-354`
- Modify: `src/ci_optimizer/api/routes.py:91`
- Modify: `src/ci_optimizer/cli.py:145`

- [ ] **Step 1: Modify `prepare_context` in prefetch.py to accept `required_data`**

Change the function signature at line 228 and add conditional logic:

```python
async def prepare_context(
    resolved: ResolvedInput,
    filters: AnalysisFilters | None = None,
    required_data: set[str] | None = None,
) -> AnalysisContext:
    """Pre-fetch all data needed for analysis.

    required_data: set of data types to fetch. None = fetch all (backward compatible).
    Valid values: {"workflows", "runs", "jobs", "logs", "usage_stats"}
    """
```

Inside the function body, after `ctx.workflow_files = sorted(...)`, replace the unconditional fetching block with:

```python
    if ctx.owner and ctx.repo:
        client = GitHubClient()
        try:
            need_all = required_data is None
            need_usage = need_all or "usage_stats" in required_data
            need_runs = need_all or "runs" in required_data or "jobs" in required_data or need_usage
            need_jobs = need_all or "jobs" in required_data or need_usage
            need_logs = need_all or "logs" in required_data

            runs = []
            all_jobs: dict[str, list[dict]] = {}

            if need_runs:
                runs = await client.list_workflow_runs(ctx.owner, ctx.repo, filters)
                ctx.runs_json_path = _write_temp_json(runs, "runs")

            if need_jobs:
                # ... existing job fetching code (lines 262-306), unchanged
                ctx.jobs_json_path = _write_temp_json(all_jobs, "jobs")

            if need_usage and runs and all_jobs:
                usage_stats = _compute_usage_stats(runs, all_jobs)
                ctx.usage_stats_json_path = _write_temp_json(usage_stats, "usage")

            if need_logs:
                # ... existing log fetching code (lines 312-342), unchanged
                ctx.logs_json_path = _write_temp_json(logs, "logs")

            # Always fetch workflow definitions and repo info when we have owner/repo
            workflows = await client.get_workflows(ctx.owner, ctx.repo)
            ctx.workflows_json_path = _write_temp_json(workflows, "workflows")
            ctx.repo_info = await client.get_repo_info(ctx.owner, ctx.repo)

        finally:
            await client.close()

    return ctx
```

- [ ] **Step 2: Update routes.py `_run_analysis_task` to pass `required_data`**

In `src/ci_optimizer/api/routes.py`, modify lines 91-93 in `_run_analysis_task`:

```python
            # Load skills and compute required data
            from ci_optimizer.agents.skill_registry import SkillRegistry
            registry = SkillRegistry().load()
            skills = registry.get_active_skills()
            required_data = registry.collect_required_data(skills)

            resolved = resolve_input(repo_input)
            ctx = await prepare_context(resolved, filters, required_data=required_data)
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_prefetch.py tests/test_api.py -v -x`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/ci_optimizer/prefetch.py src/ci_optimizer/api/routes.py
git commit -m "feat: prefetch on-demand loading based on skill requires_data"
```

---

### Task 7: CLI `--skills` Flag + `skills` Subcommand

**Files:**
- Modify: `src/ci_optimizer/cli.py`

- [ ] **Step 1: Add `--skills` argument to analyze subparser**

In `src/ci_optimizer/cli.py`, after line 35 (`--verbose`), add:

```python
    analyze.add_argument("--skills", help="Comma-separated list of dimensions to run (e.g. security,cost). Default: all")
```

- [ ] **Step 2: Add `skills` subcommand**

After the `config` subparser block (after line 53), add:

```python
    # skills command
    skills_cmd = subparsers.add_parser("skills", help="List and inspect available analysis skills")
    skills_sub = skills_cmd.add_subparsers(dest="skills_action")

    skills_sub.add_parser("list", help="List all discovered skills")

    skills_show = skills_sub.add_parser("show", help="Show details of a specific skill")
    skills_show.add_argument("name", help="Skill name (e.g. security-analyst)")
```

- [ ] **Step 3: Pass `selected_skills` to `run_analysis` in `run_analyze`**

In `run_analyze`, modify line 154:

```python
    selected = args.skills.split(",") if args.skills else None
    result = await run_analysis(ctx, config=config, selected_skills=selected)
```

- [ ] **Step 4: Add `run_skills` function**

```python
def run_skills(args):
    from ci_optimizer.agents.skill_registry import SkillRegistry

    registry = SkillRegistry().load()

    if args.skills_action == "list":
        skills = registry.get_active_skills()
        if not skills:
            print("No skills found.")
            return

        print(f"{'DIMENSION':<16} {'NAME':<24} {'SOURCE':<10} {'ENABLED':<10} {'PRIORITY'}")
        for s in skills:
            print(f"{s.dimension:<16} {s.name:<24} {s.source:<10} {str(s.enabled):<10} {s.priority}")

    elif args.skills_action == "show":
        skills = registry.get_active_skills()
        skill = next((s for s in skills if s.name == args.name), None)
        # Also check disabled skills
        if not skill:
            all_skills = list(registry._skills.values())
            skill = next((s for s in all_skills if s.name == args.name), None)
        if not skill:
            print(f"Skill not found: {args.name}", file=sys.stderr)
            sys.exit(1)

        print(f"Name:          {skill.name}")
        print(f"Description:   {skill.description}")
        print(f"Dimension:     {skill.dimension}")
        print(f"Source:        {skill.source} ({skill.source_path})")
        print(f"Tools:         {', '.join(skill.tools)}")
        print(f"Requires Data: {', '.join(skill.requires_data)}")
        print(f"Enabled:       {skill.enabled}")
        print(f"Priority:      {skill.priority}")

    else:
        print("Usage: ci-agent skills {list|show}")
        sys.exit(1)
```

- [ ] **Step 5: Wire `skills` command in `main`**

In `main()`, add before the `else` clause:

```python
    elif args.command == "skills":
        run_skills(args)
```

Update the usage message:

```python
    else:
        print("Usage: ci-agent {analyze|serve|config|skills} [options]")
```

- [ ] **Step 6: Run CLI smoke test**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m ci_optimizer.cli skills list`
Expected: Table showing 4 builtin skills

- [ ] **Step 7: Commit**

```bash
git add src/ci_optimizer/cli.py
git commit -m "feat: add --skills filter flag and skills list/show CLI subcommands"
```

---

### Task 8: API `skills` Field in AnalyzeRequest

**Files:**
- Modify: `src/ci_optimizer/api/schemas.py:27-30`
- Modify: `src/ci_optimizer/api/routes.py:170-171`

- [ ] **Step 1: Add `skills` field to AnalyzeRequest**

In `src/ci_optimizer/api/schemas.py`, modify the `AnalyzeRequest` class:

```python
class AnalyzeRequest(BaseModel):
    repo: str  # local path or GitHub URL
    filters: FilterSchema | None = None
    agent_config: AgentConfigSchema | None = None  # per-request overrides
    skills: list[str] | None = None  # dimension names to run, None = all
```

- [ ] **Step 2: Pass skills to background task**

In `src/ci_optimizer/api/routes.py`, modify `_run_analysis_task` signature and `background_tasks.add_task` call.

Add `selected_skills` parameter to `_run_analysis_task`:

```python
async def _run_analysis_task(
    report_id: int,
    repo_input: str,
    filters: AnalysisFilters | None,
    config: AgentConfig | None = None,
    selected_skills: list[str] | None = None,
):
```

And inside it, pass to `run_analysis`:

```python
            result = await run_analysis(ctx, config=config, selected_skills=selected_skills)
```

And update the `background_tasks.add_task` call in the `analyze` endpoint:

```python
    background_tasks.add_task(
        _run_analysis_task, report.id, request.repo, filters, config, request.skills
    )
```

- [ ] **Step 3: Run API tests**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_api.py -v -x`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/ci_optimizer/api/schemas.py src/ci_optimizer/api/routes.py
git commit -m "feat: add skills field to AnalyzeRequest API schema"
```

---

### Task 9: Frontend Dynamic Tabs

**Files:**
- Modify: `web/src/types/index.ts:7`
- Modify: `web/src/app/reports/[id]/ReportTabs.tsx:18-30`
- Modify: `web/src/app/reports/[id]/page.tsx:164-169`

- [ ] **Step 1: Change Dimension type from union to string**

In `web/src/types/index.ts`, replace line 7:

```typescript
export type Dimension = string;
```

- [ ] **Step 2: Make ReportTabs color fallback dynamic**

In `web/src/app/reports/[id]/ReportTabs.tsx`, replace the hardcoded color maps with fallback logic:

```typescript
const DIMENSION_ACCENT: Record<string, string> = {
  efficiency: 'text-accent-blue border-accent-blue',
  security: 'text-accent-purple border-accent-purple',
  cost: 'text-accent-green border-accent-green',
  errors: 'text-accent-red border-accent-red',
};

const DIMENSION_COUNT_BG: Record<string, string> = {
  efficiency: 'bg-blue-500/15 text-blue-400',
  security: 'bg-purple-500/15 text-purple-400',
  cost: 'bg-green-500/15 text-green-400',
  errors: 'bg-red-500/15 text-red-400',
};

const DEFAULT_ACCENT = 'text-slate-300 border-slate-300';
const DEFAULT_COUNT_BG = 'bg-slate-500/15 text-slate-400';
```

Then in the JSX, replace `DIMENSION_ACCENT[dim.key]` with `DIMENSION_ACCENT[dim.key] ?? DEFAULT_ACCENT` and `DIMENSION_COUNT_BG[dim.key]` with `DIMENSION_COUNT_BG[dim.key] ?? DEFAULT_COUNT_BG`.

- [ ] **Step 3: Build dimensions dynamically in page.tsx**

In `web/src/app/reports/[id]/page.tsx`, replace lines 164-169 (hardcoded dimensions array) with:

```typescript
  // Build dimensions dynamically from findings
  const dimensionKeys = [...new Set(findings.map((f) => f.dimension))];
  // Keep known dimensions in standard order, append unknown ones
  const KNOWN_ORDER: string[] = ['efficiency', 'security', 'cost', 'errors'];
  const ordered = [
    ...KNOWN_ORDER.filter((k) => dimensionKeys.includes(k)),
    ...dimensionKeys.filter((k) => !KNOWN_ORDER.includes(k)),
  ];
  const dimensions = ordered.map((key) => ({
    key,
    label: key.charAt(0).toUpperCase() + key.slice(1),
    count: (byDimension[key] ?? []).length,
  }));
```

- [ ] **Step 4: Run frontend type check**

Run: `cd /Users/zhenyu.jiang/ci-agent/web && npx tsc --noEmit`
Expected: No type errors

- [ ] **Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/app/reports/[id]/ReportTabs.tsx web/src/app/reports/[id]/page.tsx
git commit -m "feat: dynamic dimension tabs in frontend, support user-defined dimensions"
```

---

### Task 10: Integration Test — Full Skill Lifecycle

**Files:**
- Create: `tests/test_skill_system.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_skill_system.py
"""Integration tests for the skill system end-to-end."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ci_optimizer.agents.skill_registry import SkillRegistry, _BUILTIN_DIR


class TestSkillSystemIntegration:
    """Test the full skill lifecycle: load → registry → orchestrator prompt."""

    def test_builtin_skills_produce_valid_orchestrator_prompt(self):
        """Builtin skills generate an orchestrator prompt with all dimensions."""
        registry = SkillRegistry(builtin_dir=_BUILTIN_DIR, user_dir=Path("/nonexistent"))
        registry.load()
        skills = registry.get_active_skills()

        prompt = registry.build_orchestrator_prompt(skills)

        assert "efficiency" in prompt
        assert "security" in prompt
        assert "cost" in prompt
        assert "errors" in prompt
        assert "efficiency-analyst" in prompt
        assert "security-analyst" in prompt
        assert "cost-analyst" in prompt
        assert "error-analyst" in prompt
        assert "4 specialist" in prompt

    def test_user_skill_adds_dimension_to_prompt(self, tmp_path):
        """A user-added skill appears in the orchestrator prompt."""
        user_dir = tmp_path / "user_skills"
        rel_dir = user_dir / "reliability"
        rel_dir.mkdir(parents=True)
        (rel_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: reliability-analyst
            description: Reliability analysis
            dimension: reliability
            requires_data:
              - workflows
              - jobs
            ---

            Analyze reliability.
        """))

        registry = SkillRegistry(builtin_dir=_BUILTIN_DIR, user_dir=user_dir)
        registry.load()
        skills = registry.get_active_skills()

        assert len(skills) == 5
        prompt = registry.build_orchestrator_prompt(skills)
        assert "reliability" in prompt
        assert "5 specialist" in prompt

    def test_collect_required_data_for_all_builtins(self):
        """All builtins together need workflows, jobs, logs, usage_stats."""
        registry = SkillRegistry(builtin_dir=_BUILTIN_DIR, user_dir=Path("/nonexistent"))
        registry.load()
        skills = registry.get_active_skills()
        required = registry.collect_required_data(skills)

        assert required == {"workflows", "jobs", "logs", "usage_stats"}

    def test_select_single_skill_reduces_data(self):
        """Selecting only security should only require workflows."""
        registry = SkillRegistry(builtin_dir=_BUILTIN_DIR, user_dir=Path("/nonexistent"))
        registry.load()
        skills = registry.get_active_skills(selected=["security"])

        assert len(skills) == 1
        required = registry.collect_required_data(skills)
        assert required == {"workflows"}

    def test_skill_to_agent_definition(self):
        """Skill.to_agent_definition produces valid AgentDefinition."""
        registry = SkillRegistry(builtin_dir=_BUILTIN_DIR, user_dir=Path("/nonexistent"))
        registry.load()
        skill = registry.get_active_skills(selected=["security"])[0]

        agent_def = skill.to_agent_definition(model="claude-sonnet-4-20250514")
        assert agent_def.description == skill.description
        assert agent_def.prompt == skill.prompt
        assert agent_def.tools == ["Read", "Glob", "Grep"]
        assert agent_def.model == "claude-sonnet-4-20250514"
```

- [ ] **Step 2: Run the integration tests**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/test_skill_system.py -v`
Expected: All 5 tests PASS

- [ ] **Step 3: Run the full test suite**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_e2e.py`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_skill_system.py
git commit -m "test: add skill system integration tests"
```

---

### Task 11: Final Cleanup — Remove Dead Imports + Verify

**Files:**
- Verify: all `src/ci_optimizer/agents/*.py` files
- Verify: `tests/` for any broken imports

- [ ] **Step 1: Search for any remaining references to deleted modules**

Run:
```bash
cd /Users/zhenyu.jiang/ci-agent
grep -rn "from ci_optimizer.agents.efficiency\|from ci_optimizer.agents.security\|from ci_optimizer.agents.cost\|from ci_optimizer.agents.errors\|EFFICIENCY_PROMPT\|SECURITY_PROMPT\|COST_PROMPT\|ERRORS_PROMPT\|efficiency_agent\|security_agent\|cost_agent\|error_agent" src/ tests/
```
Expected: No output

- [ ] **Step 2: Verify `agents/__init__.py` is clean**

Run: `cat src/ci_optimizer/agents/__init__.py`
Expected: Empty or just docstring

- [ ] **Step 3: Full test suite**

Run: `cd /Users/zhenyu.jiang/ci-agent && python -m pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_e2e.py`
Expected: All tests PASS

- [ ] **Step 4: CLI smoke tests**

```bash
cd /Users/zhenyu.jiang/ci-agent
python -m ci_optimizer.cli skills list
python -m ci_optimizer.cli skills show security-analyst
python -m ci_optimizer.cli --help
```
Expected: All commands produce expected output

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: final cleanup for skill system migration"
```
