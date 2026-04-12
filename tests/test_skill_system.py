"""Integration tests for the skill system end-to-end."""

import textwrap
from pathlib import Path

from ci_optimizer.agents.skill_registry import _BUILTIN_DIR, SkillRegistry


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
        (rel_dir / "SKILL.md").write_text(
            textwrap.dedent("""\
            ---
            name: reliability-analyst
            description: Reliability analysis
            dimension: reliability
            requires_data:
              - workflows
              - jobs
            ---

            Analyze reliability.
        """)
        )

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

        assert required == {"workflows", "jobs", "logs", "usage_stats", "action_shas"}

    def test_select_single_skill_reduces_data(self):
        """Selecting only security should only require workflows."""
        registry = SkillRegistry(builtin_dir=_BUILTIN_DIR, user_dir=Path("/nonexistent"))
        registry.load()
        skills = registry.get_active_skills(selected=["security"])

        assert len(skills) == 1
        required = registry.collect_required_data(skills)
        assert required == {"workflows", "action_shas"}

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
