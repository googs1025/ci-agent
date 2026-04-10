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