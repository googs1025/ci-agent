"""Tests for the skill registry: parsing, validation, loading."""

import textwrap
from pathlib import Path

from ci_optimizer.agents.skill_registry import (
    SkillRegistry,
    get_registry,
    reset_registry,
)


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


class TestSingletonAndReload:
    """Test the get_registry singleton and reload behavior."""

    def setup_method(self):
        reset_registry()

    def teardown_method(self):
        reset_registry()

    def test_get_registry_returns_same_instance(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_get_registry_loads_builtin_skills(self):
        skills = get_registry().get_active_skills()
        # Should include all 4 builtins
        dims = {s.dimension for s in skills}
        assert {"efficiency", "security", "cost", "errors"} <= dims

    def test_reset_registry_discards_instance(self):
        r1 = get_registry()
        reset_registry()
        r2 = get_registry()
        assert r1 is not r2

    def test_reload_method_rescans_directory(self, tmp_path):
        # Use a custom registry so we can control the source.
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: test-analyst
            description: Test
            dimension: testing
            ---

            Prompt.
        """))

        reg = SkillRegistry(builtin_dir=tmp_path, user_dir=tmp_path / "noexist")
        reg.load()
        assert len(reg.get_active_skills()) == 1

        # Add a second skill on disk and reload
        skill2 = tmp_path / "second"
        skill2.mkdir()
        (skill2 / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: second-analyst
            description: Second
            dimension: second
            ---

            Prompt.
        """))

        reg.reload()
        skills = reg.get_active_skills()
        assert len(skills) == 2
        assert {s.dimension for s in skills} == {"testing", "second"}
