"""Skill importer — convert external SKILL.md files into ci-agent format.

架构角色：外部技能的适配导入层，负责将来自不同系统的 SKILL.md 格式转换为 ci-agent 兼容格式。
核心职责：
  1. 从 Claude Code、OpenCode、本地路径或 GitHub 仓库导入技能定义
  2. 规范化字段差异（如 allowed-tools → tools、补充 dimension 和 requires_data）
  3. 写入 ~/.ci-agent/skills/<name>/ 并通过 SkillRegistry 进行校验
与其他模块的关系：供 CLI 命令（`ci-agent skill import`）调用，导入后的技能由 SkillRegistry 加载；
  ci-agent 的 SKILL.md schema 是 Claude Code/OpenCode schema 的超集（多了 dimension、requires_data）。

Supports importing from:
  - Claude Code (~/.claude/skills/<name>/SKILL.md)
  - OpenCode (~/.config/opencode/skills/<name>/SKILL.md)
  - Arbitrary local paths
  - GitHub repositories (git clone + import)

ci-agent's SKILL.md schema differs slightly from Claude Code / OpenCode:
  - Requires an extra `dimension` field (not present in other systems)
  - Requires `requires_data` for prefetch-stage data loading
  - Uses `tools` instead of Claude Code's `allowed-tools`

The importer normalizes these fields, validates the result, and writes
the merged SKILL.md to ~/.ci-agent/skills/<name>/.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from ci_optimizer.agents.skill_registry import (
    _USER_DIR,
    VALID_REQUIRES_DATA,
    SkillRegistry,
)

logger = logging.getLogger(__name__)

CLAUDE_CODE_SKILLS_DIR = Path.home() / ".claude" / "skills"
OPENCODE_SKILLS_DIR = Path.home() / ".config" / "opencode" / "skills"


class SkillImportError(Exception):
    """技能导入失败时抛出，涵盖格式错误、字段缺失、校验失败等不可恢复情形。

    Raised when a skill cannot be imported.
    """


@dataclass
class ImportResult:
    """导入操作的结果，包含目标路径、来源信息和非致命警告列表。"""

    name: str
    target_path: Path
    dimension: str
    source_kind: str  # "claude-code" | "opencode" | "path" | "github"
    source_ref: str
    warnings: list[str]


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split SKILL.md into (frontmatter_dict, body_str)."""
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise SkillImportError("SKILL.md is missing YAML frontmatter delimited by '---'")
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        raise SkillImportError(f"Invalid YAML frontmatter: {e}")
    if not isinstance(meta, dict):
        raise SkillImportError("Frontmatter must be a YAML mapping")
    return meta, parts[2].lstrip("\n")


def _normalize_name(raw: str) -> str:
    """将技能名规范化为文件系统安全的目录名（小写、连字符分隔）。

    Convert a skill name to a filesystem-safe directory name.
    """
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw.strip().lower())
    return safe.strip("-") or "unnamed-skill"


def _dump_skill_md(meta: dict, body: str) -> str:
    """Serialize (meta, body) back to SKILL.md format."""
    yaml_text = yaml.safe_dump(
        meta,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def _normalize_frontmatter(
    meta: dict,
    dimension: str | None,
    requires_data: list[str] | None,
    source_kind: str,
) -> tuple[dict, list[str]]:
    """将外部 SKILL.md 的 frontmatter 映射到 ci-agent 的 schema，返回 (规范化 meta, 警告列表)。

    Map foreign frontmatter to ci-agent's schema. Returns (normalized_meta, warnings).
    dimension 是 ci-agent 必需但外部格式通常没有的字段，必须由调用方通过参数或源文件提供。
    """
    warnings: list[str] = []
    out: dict = {}

    # Required: name + description
    if not meta.get("name"):
        raise SkillImportError("Source skill is missing required 'name' field")
    if not meta.get("description"):
        raise SkillImportError("Source skill is missing required 'description' field")

    out["name"] = str(meta["name"])
    out["description"] = str(meta["description"])

    # Dimension: required by ci-agent, foreign formats don't have it
    dim = dimension or meta.get("dimension")
    if not dim:
        raise SkillImportError("ci-agent requires a 'dimension' field. Pass --dimension or add one to the source SKILL.md frontmatter.")
    out["dimension"] = str(dim)

    # Tools: Claude Code uses 'allowed-tools', ci-agent uses 'tools'
    tools = meta.get("tools") or meta.get("allowed-tools")
    if tools is None:
        out["tools"] = ["Read", "Glob", "Grep"]
        if source_kind == "claude-code":
            warnings.append("No tools declared in source — defaulting to [Read, Glob, Grep]")
    else:
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        out["tools"] = list(tools)

    # requires_data: ci-agent-specific, foreign formats don't have it
    rd = requires_data or meta.get("requires_data") or ["workflows"]
    if isinstance(rd, str):
        rd = [x.strip() for x in rd.split(",") if x.strip()]
    invalid = set(rd) - VALID_REQUIRES_DATA
    if invalid:
        raise SkillImportError(f"Invalid requires_data values: {invalid}. Valid options: {sorted(VALID_REQUIRES_DATA)}")
    out["requires_data"] = list(rd)

    # Optional: priority, enabled
    if "priority" in meta:
        out["priority"] = int(meta["priority"])
    if "enabled" in meta:
        out["enabled"] = bool(meta["enabled"])

    return out, warnings


def _validate_imported(target_dir: Path) -> list[str]:
    """Parse + validate the freshly-written SKILL.md via SkillRegistry helpers."""
    skill_md = target_dir / "SKILL.md"
    try:
        skill = SkillRegistry._parse_skill_md(skill_md, source="user")
    except Exception as e:
        return [f"Parse failed: {e}"]
    return SkillRegistry._validate_skill(skill)


def import_from_path(
    source_dir: Path,
    dimension: str | None = None,
    requires_data: list[str] | None = None,
    target_dir: Path | None = None,
    source_kind: str = "path",
    name_override: str | None = None,
) -> ImportResult:
    """从本地目录导入技能，是所有导入函数的核心实现，其他入口函数最终都调用此函数。

    Import a skill from a local directory containing SKILL.md.
    The directory must have a SKILL.md at its root. After normalization
    the result is written to ~/.ci-agent/skills/<name>/.

    companion 文件（README、hooks.py 等）会原样复制，不做格式转换。
    写入后通过 SkillRegistry 做一次完整的解析校验，失败则回滚删除目标目录。
    """
    source_dir = Path(source_dir).expanduser().resolve()
    if not source_dir.is_dir():
        raise SkillImportError(f"Not a directory: {source_dir}")

    skill_md = source_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillImportError(f"No SKILL.md found in {source_dir}")

    text = skill_md.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    normalized, warnings = _normalize_frontmatter(meta, dimension, requires_data, source_kind)

    if name_override:
        normalized["name"] = name_override

    target_root = target_dir if target_dir is not None else _USER_DIR
    target_root.mkdir(parents=True, exist_ok=True)
    dir_name = _normalize_name(normalized["name"])
    target_skill_dir = target_root / dir_name

    if target_skill_dir.exists():
        raise SkillImportError(f"Target already exists: {target_skill_dir}. Remove it first or use a different --name.")

    # Copy any companion files (README, hooks.py, etc.) verbatim
    target_skill_dir.mkdir(parents=True)
    for item in source_dir.iterdir():
        if item.name == "SKILL.md":
            continue
        dest = target_skill_dir / item.name
        if item.is_file():
            shutil.copy2(item, dest)
        elif item.is_dir():
            shutil.copytree(item, dest)

    # Write normalized SKILL.md
    merged = _dump_skill_md(normalized, body)
    (target_skill_dir / "SKILL.md").write_text(merged, encoding="utf-8")

    # Validate by loading through the registry
    val_errors = _validate_imported(target_skill_dir)
    if val_errors:
        shutil.rmtree(target_skill_dir, ignore_errors=True)
        raise SkillImportError(f"Validation failed: {val_errors}")

    return ImportResult(
        name=normalized["name"],
        target_path=target_skill_dir,
        dimension=normalized["dimension"],
        source_kind=source_kind,
        source_ref=str(source_dir),
        warnings=warnings,
    )


def import_from_claude_code(
    name: str,
    dimension: str | None = None,
    requires_data: list[str] | None = None,
    target_dir: Path | None = None,
) -> ImportResult:
    """Import a skill from ~/.claude/skills/<name>/."""
    src = CLAUDE_CODE_SKILLS_DIR / name
    if not src.is_dir():
        raise SkillImportError(f"Claude Code skill not found: {src}. Check available skills with: ls {CLAUDE_CODE_SKILLS_DIR}")
    return import_from_path(
        src,
        dimension=dimension,
        requires_data=requires_data,
        target_dir=target_dir,
        source_kind="claude-code",
    )


def import_from_opencode(
    name: str,
    dimension: str | None = None,
    requires_data: list[str] | None = None,
    target_dir: Path | None = None,
) -> ImportResult:
    """Import a skill from ~/.config/opencode/skills/<name>/."""
    src = OPENCODE_SKILLS_DIR / name
    if not src.is_dir():
        raise SkillImportError(f"OpenCode skill not found: {src}. Check available skills with: ls {OPENCODE_SKILLS_DIR}")
    return import_from_path(
        src,
        dimension=dimension,
        requires_data=requires_data,
        target_dir=target_dir,
        source_kind="opencode",
    )


def install_from_github(
    url: str,
    dimension: str | None = None,
    requires_data: list[str] | None = None,
    target_dir: Path | None = None,
) -> ImportResult:
    """从 GitHub 仓库 clone 并导入技能，clone 到临时目录后复用 import_from_path 逻辑。

    Clone a GitHub repo containing a skill and import it.
    Accepted formats:
      - https://github.com/owner/repo
      - git@github.com:owner/repo.git
      - gh:owner/repo  (shorthand)

    使用 --depth=1 浅克隆降低带宽消耗；导入完成后临时目录由 TemporaryDirectory 自动清理。
    """
    if url.startswith("gh:"):
        url = f"https://github.com/{url[3:]}"

    with tempfile.TemporaryDirectory(prefix="ci-agent-skill-install-") as tmp:
        tmp_path = Path(tmp) / "skill"
        logger.info(f"Cloning {url} → {tmp_path}")
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(tmp_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as e:
            raise SkillImportError(f"git clone failed: {e.stderr.strip()}")
        except subprocess.TimeoutExpired:
            raise SkillImportError("git clone timed out after 60s")

        # Remove .git before importing
        git_dir = tmp_path / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir, ignore_errors=True)

        result = import_from_path(
            tmp_path,
            dimension=dimension,
            requires_data=requires_data,
            target_dir=target_dir,
            source_kind="github",
        )
        result.source_ref = url
        return result


def uninstall_skill(name: str, target_dir: Path | None = None) -> Path:
    """Remove a user-installed skill by name (directory name)."""
    target_root = target_dir if target_dir is not None else _USER_DIR
    skill_dir = target_root / _normalize_name(name)
    if not skill_dir.is_dir():
        raise SkillImportError(f"No installed skill at {skill_dir}")
    shutil.rmtree(skill_dir)
    return skill_dir
