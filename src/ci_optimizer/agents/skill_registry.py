"""Skill registry — discovers, parses, validates, and manages SKILL.md definitions.

架构角色：技能（子 agent）的配置管理层，将磁盘上的 SKILL.md 文件转化为运行时可用的 Skill 对象。
核心职责：
  1. 扫描 builtin（项目内 skills/）和 user（~/.ci-agent/skills/）两个目录，同名技能以用户定义优先
  2. 解析 SKILL.md 的 YAML frontmatter + 正文，并对字段进行校验
  3. 动态生成 orchestrator 的 system prompt，使其知道要调度哪些 specialist
与其他模块的关系：orchestrator.py、anthropic_engine.py、openai_engine.py 均通过 get_registry()
  获取全局单例来查询激活的技能列表；failure_triage.py 通过 get_skill("failure-triage") 获取独立技能。
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ci_optimizer.agents.prompts import FINDING_JSON_FORMAT

logger = logging.getLogger(__name__)

VALID_REQUIRES_DATA = {"workflows", "runs", "jobs", "logs", "usage_stats", "action_shas"}

# Default paths
_BUILTIN_DIR = Path(__file__).resolve().parent.parent.parent.parent / "skills"
_USER_DIR = Path.home() / ".ci-agent" / "skills"


@dataclass
class Skill:
    """从 SKILL.md 解析得到的单个分析技能，代表一个 specialist subagent 的完整定义。

    dimension 对应分析维度（如 "security"、"performance"），是 orchestrator 组织结果的分类键。
    requires_data 决定 prefetch 阶段需要预先加载哪些数据（工作流文件、运行日志等）。
    standalone=True 的技能（如 failure-triage）不参与多专家编排流程，由专属 API 直接调用。
    """

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
    # Standalone skills are invoked directly (e.g., failure-triage for /api/ci-runs/diagnose)
    # and are excluded from the multi-specialist orchestrator flow.
    standalone: bool = False

    def to_agent_definition(self, model: str | None = None):
        """将 Skill 转换为 Claude Agent SDK 所需的 AgentDefinition 格式。

        仅在 Anthropic 引擎路径下使用；OpenAI 引擎直接使用 skill.prompt 字符串。
        """
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
    """从 builtin 和 user 两个目录发现并管理所有技能定义。

    采用"用户目录覆盖内置目录"的策略，允许用户在不修改项目代码的情况下覆盖或扩展技能。
    通常通过模块级单例 get_registry() 访问，避免每次请求重复扫描文件系统。
    """

    def __init__(
        self,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
    ):
        self._builtin_dir = builtin_dir if builtin_dir is not None else _BUILTIN_DIR
        self._user_dir = user_dir if user_dir is not None else _USER_DIR
        self._skills: dict[str, Skill] = {}

    def load(self) -> "SkillRegistry":
        """扫描 builtin 和 user 目录并填充技能字典，支持链式调用。

        User skills override builtin by name.
        """
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
        """解析单个 SKILL.md 文件：提取 YAML frontmatter 和正文 prompt。

        若 prompt 中不含 "## Output Format"，则自动追加标准 JSON 输出格式说明，
        确保所有 specialist 的输出格式一致，便于 orchestrator 聚合。
        Parse SKILL.md: YAML frontmatter + body.
        """
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
            standalone=meta.get("standalone", False),
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

    def get_active_skills(self, selected: list[str] | None = None) -> list[Skill]:
        """返回用于多专家编排流程的激活技能列表，按 priority 降序排列。

        Standalone skills (e.g., failure-triage) are excluded because they
        have a different input contract and are invoked directly by their
        own API endpoint. Use ``get_skill(name)`` to access them.

        selected 为 None 时返回全部非 standalone 技能；否则按 dimension 名过滤，
        允许用户在 API 请求中指定只运行哪些分析维度。
        """
        skills = [s for s in self._skills.values() if s.enabled and not s.standalone]
        if selected:
            skills = [s for s in skills if s.dimension in selected]
        return sorted(skills, key=lambda s: s.priority, reverse=True)

    def get_skill(self, name: str) -> Skill | None:
        """Return a skill by name (including standalone skills)."""
        return self._skills.get(name)

    def collect_required_data(self, skills: list[Skill]) -> set[str]:
        """Union of all active skills' requires_data."""
        result: set[str] = set()
        for s in skills:
            result.update(s.requires_data)
        return result

    def reload(self) -> "SkillRegistry":
        """Clear cached skills and rescan the directories. Thread-unsafe."""
        self._skills.clear()
        self._load_dir(self._builtin_dir, source="builtin")
        self._load_dir(self._user_dir, source="user")
        return self

    def build_orchestrator_prompt(self, skills: list[Skill]) -> str:
        """根据当前激活的技能列表动态生成 orchestrator 的 system prompt。

        将 dimension 名称、各 specialist 描述、以及期望的 JSON 输出 schema 内嵌进 prompt，
        使 orchestrator 知道要调用哪些 specialist 以及最终输出的结构。
        Dynamically generate orchestrator prompt from active skills.
        """
        dim_list = "\n".join(f"{i + 1}. **{s.dimension}**: {s.description}" for i, s in enumerate(skills))
        agent_list = "\n".join(f"   - **{s.name}**: {s.description}" for s in skills)
        dim_schema = "\n".join(f'    "{s.dimension}": {{ "findings": [...] }},' for s in skills)

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


# ──────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ──────────────────────────────────────────────────────────────

_global_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """返回进程级 SkillRegistry 单例（懒初始化）。

    Return a lazily-initialized, process-wide SkillRegistry singleton.

    Use this from long-lived code paths (API routes, engines) so we don't
    re-scan the filesystem on every request. Call ``get_registry().reload()``
    to pick up on-disk changes.

    Tests and CLI one-shots that want isolation can still construct a
    ``SkillRegistry(...)`` directly.

    设计权衡：单例模式避免每次 API 请求重扫文件系统，但热更新时需要手动调用 reload()。
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry().load()
    return _global_registry


def reset_registry() -> None:
    """Discard the global singleton. Intended for tests."""
    global _global_registry
    _global_registry = None
