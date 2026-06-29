"""Local skill registry for the ingestion agent.

The agent's behaviour is driven by **local skills** — one directory per skill
under ``skills/``, each containing a ``SKILL.md`` with YAML frontmatter and a
markdown body. The frontmatter declares:

  * ``name``        — the skill id
  * ``description`` — what the skill does / when to use it
  * ``objective``   — the asset objective the skill owns (``identify`` for the
                       triage skill; ``use case`` / ``code`` / ``method`` for the
                       processing skills)
  * ``processor``   — which processing strategy the skill binds to
                       (``classify`` | ``case-study`` | ``concept`` | ``repository``)

The body of ``asset-identification/SKILL.md`` is used verbatim as the system
prompt for classification, so the skill literally *is* the policy. Processing
skills declare which shared extractor strategy to run; the runtime dispatches by
``objective`` so adding a new asset type is a matter of dropping in a new skill.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a ``--- ... ---`` YAML frontmatter block, returning (meta, body).

    Uses PyYAML when available, otherwise a minimal ``key: value`` parser that
    also supports the ``key: |`` block-scalar used for multi-line descriptions.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text.strip()

    raw_meta, body = match.group(1), match.group(2)

    try:
        import yaml  # type: ignore

        meta = yaml.safe_load(raw_meta) or {}
        if isinstance(meta, dict):
            return meta, body.strip()
    except Exception:  # pragma: no cover - fallback path
        logger.debug("PyYAML unavailable or failed; using minimal frontmatter parser")

    meta: Dict[str, str] = {}
    current_key: Optional[str] = None
    block_lines: list[str] = []
    for line in raw_meta.splitlines():
        block_match = re.match(r"^(\w[\w-]*):\s*\|\s*$", line)
        kv_match = re.match(r"^(\w[\w-]*):\s*(.+?)\s*$", line)
        if block_match:
            if current_key and block_lines:
                meta[current_key] = " ".join(s.strip() for s in block_lines).strip()
            current_key = block_match.group(1)
            block_lines = []
        elif kv_match and not line.startswith(" "):
            if current_key and block_lines:
                meta[current_key] = " ".join(s.strip() for s in block_lines).strip()
                current_key = None
                block_lines = []
            meta[kv_match.group(1)] = kv_match.group(2).strip().strip('"').strip("'")
        elif current_key:
            block_lines.append(line)
    if current_key and block_lines:
        meta[current_key] = " ".join(s.strip() for s in block_lines).strip()
    return meta, body.strip()


@dataclass
class Skill:
    """A loaded local skill: its metadata plus the markdown instruction body."""

    name: str
    description: str
    objective: str
    processor: str
    instructions: str
    path: Path


class SkillRegistry:
    """Discovers and indexes the local ``SKILL.md`` skills by objective."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = Path(skills_dir)
        self._by_name: Dict[str, Skill] = {}
        self._by_objective: Dict[str, Skill] = {}

    def load(self) -> "SkillRegistry":
        if not self.skills_dir.is_dir():
            raise FileNotFoundError(f"Skills directory not found: {self.skills_dir}")

        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            meta, body = _parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            name = str(meta.get("name") or skill_md.parent.name)
            objective = str(meta.get("objective") or "").strip().lower()
            processor = str(meta.get("processor") or "").strip().lower()
            skill = Skill(
                name=name,
                description=str(meta.get("description") or "").strip(),
                objective=objective,
                processor=processor,
                instructions=body,
                path=skill_md,
            )
            self._by_name[name] = skill
            if objective:
                self._by_objective[objective] = skill
            logger.info("Loaded skill '%s' (objective=%s, processor=%s)", name, objective, processor)

        if not self._by_name:
            raise RuntimeError(f"No skills found under {self.skills_dir}")
        return self

    @property
    def identification_skill(self) -> Skill:
        skill = self._by_objective.get("identify")
        if not skill:
            raise RuntimeError("No asset-identification skill (objective: identify) is registered")
        return skill

    def processing_skill_for(self, objective: str) -> Skill:
        key = (objective or "").strip().lower()
        skill = self._by_objective.get(key)
        if not skill:
            available = ", ".join(sorted(o for o in self._by_objective if o != "identify"))
            raise RuntimeError(
                f"No processing skill registered for objective '{objective}'. Available: {available}"
            )
        return skill

    def get(self, name: str) -> Skill:
        return self._by_name[name]

    def names(self) -> list[str]:
        return sorted(self._by_name)
