"""Skill discovery and loading from the IRIS skills directory."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.errors import SkillError
from ..core.logging import log_debug, log_error


# ---------------------------------------------------------------------------
# Minimal frontmatter parser (no PyYAML dependency)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """Parse YAML-like frontmatter between --- markers.

    Supports:
      key: value              → str
      key: [a, b, c]          → list (inline)
      key:                     → list (block)
        - item1
        - item2
    """
    result: Dict[str, Any] = {}
    lines = text.strip().splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # key: value
        m = re.match(r"^(\w[\w\-]*)\s*:\s*(.*)", line)
        if not m:
            i += 1
            continue

        key = m.group(1).strip()
        value_part = m.group(2).strip()

        if value_part:
            # Inline list: [a, b, c]
            if value_part.startswith("[") and value_part.endswith("]"):
                inner = value_part[1:-1]
                items = [s.strip().strip("\"'") for s in inner.split(",") if s.strip()]
                result[key] = items
            else:
                # Scalar — strip surrounding quotes
                result[key] = value_part.strip("\"'")
        else:
            # Check for block list (next lines starting with "  - ")
            block_items: List[str] = []
            j = i + 1
            while j < len(lines):
                bline = lines[j]
                bm = re.match(r"^\s+-\s+(.*)", bline)
                if bm:
                    block_items.append(bm.group(1).strip().strip("\"'"))
                    j += 1
                elif not bline.strip():
                    j += 1
                else:
                    break
            if block_items:
                result[key] = block_items
                i = j
                continue
            else:
                result[key] = ""

        i += 1

    return result


def _split_frontmatter(text: str) -> tuple:
    """Split a SKILL.md into (frontmatter_text, body_text).

    Returns ("", text) if no frontmatter markers found.
    """
    stripped = text.lstrip("\n")
    if not stripped.startswith("---"):
        return ("", text)

    # Find closing ---
    rest = stripped[3:].lstrip("\n")
    idx = rest.find("\n---")
    if idx == -1:
        return ("", text)

    fm_text = rest[:idx]
    body = rest[idx + 4:]  # skip past "\n---"
    return (fm_text, body.lstrip("\n"))


# ---------------------------------------------------------------------------
# SkillDefinition
# ---------------------------------------------------------------------------

@dataclass
class SkillDefinition:
    """A loaded skill from the IRIS skills directory<slug>/SKILL.md."""

    name: str
    description: str
    directory: str
    allowed_tools: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    author: str = ""
    version: str = ""
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    _body: Optional[str] = field(default=None, repr=False)
    _md_path: str = field(default="", repr=False)

    @property
    def slug(self) -> str:
        """Slug = directory basename, used as /slug invocation."""
        return os.path.basename(self.directory)

    @property
    def body(self) -> str:
        """Lazy-load the body text on first access."""
        if self._body is None:
            self._body = _load_body(self._md_path)
        return self._body


def _load_body(md_path: str) -> str:
    """Read the body (everything after frontmatter) from a SKILL.md file."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise SkillError(f"Cannot read skill file {md_path}: {e}")

    _fm, body = _split_frontmatter(text)
    return body.strip()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_skills(skills_dir: str) -> List[SkillDefinition]:
    """Scan skills_dir for <slug>/SKILL.md, return loaded SkillDefinitions.

    Each subdirectory with a SKILL.md is treated as a skill.
    Metadata is eagerly loaded from frontmatter; body is lazy.
    """
    if not os.path.isdir(skills_dir):
        log_debug(f"Skills directory not found: {skills_dir}")
        return []

    skills: List[SkillDefinition] = []

    for entry in sorted(os.listdir(skills_dir)):
        skill_dir = os.path.join(skills_dir, entry)
        md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(md_path):
            continue

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                text = f.read()

            fm_text, _body = _split_frontmatter(text)
            fm = _parse_frontmatter(fm_text) if fm_text else {}

            skill = SkillDefinition(
                name=fm.get("name", entry),
                description=fm.get("description", ""),
                directory=skill_dir,
                allowed_tools=fm.get("allowed_tools", []),
                tags=fm.get("tags", []),
                author=fm.get("author", ""),
                version=fm.get("version", ""),
                frontmatter=fm,
                _body=None,  # lazy
                _md_path=md_path,
            )
            skills.append(skill)
            log_debug(f"Discovered skill: /{entry} — {skill.description or '(no description)'}")

        except Exception as e:
            log_error(f"Failed to load skill from {md_path}: {e}")

    return skills
