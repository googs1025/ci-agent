"""Skill registry — discovers, parses, validates, and manages SKILL.md definitions."""

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
        self._builtin_dir = builtin_dir if builtin_dir is not None else _BUILTIN_DIR
        self._user_dir = user_dir if user_dir is not None else _USER_DIR
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

    def reload(self) -> "SkillRegistry":
        """Clear cached skills and rescan the directories. Thread-unsafe."""
        self._skills.clear()
        self._load_dir(self._builtin_dir, source="builtin")
        self._load_dir(self._user_dir, source="user")
        return self

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


# ──────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ──────────────────────────────────────────────────────────────

_global_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """Return a lazily-initialized, process-wide SkillRegistry singleton.

    Use this from long-lived code paths (API routes, engines) so we don't
    re-scan the filesystem on every request. Call ``get_registry().reload()``
    to pick up on-disk changes.

    Tests and CLI one-shots that want isolation can still construct a
    ``SkillRegistry(...)`` directly.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry().load()
    return _global_registry


def reset_registry() -> None:
    """Discard the global singleton. Intended for tests."""
    global _global_registry
    _global_registry = None
