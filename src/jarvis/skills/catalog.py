"""Skill discovery: SKILL.md kanonis, lazy-load per perintah.

Format (diadaptasi, disederhanakan):
    ---
    name: research
    description: satu paragraf pemicu untuk model/pembaca
    tools: knowledge_search, knowledge_read
    capabilities: read_only, local_index, citations
    ---
    # Judul
    isi imperatif Do/Don't ...

Discovery fail-closed: file tanpa frontmatter valid dilewati (tidak
pernah crash startup); duplikat nama ditolak saat discovery ketat atau
dilewati saat listing. Prompt hanya memuat path ("baca SKILL.md + satu
file relevan"), bukan seluruh isi — lazy-load.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

SKILL_FILE = "SKILL.md"
COMMANDS_DIR = "commands"


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    tools: frozenset[str]
    capabilities: frozenset[str]
    path: Path


def _parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            return None
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _split_list(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in value.split(",") if part.strip())


def discover_skills(directory: Path | None = None) -> dict[str, SkillSpec]:
    """Scan direktori skills/; malformed dilewati, duplikat menang pertama."""
    base = directory or (Path(__file__).resolve().parent)
    found: dict[str, SkillSpec] = {}
    for entry in sorted(base.iterdir()):
        skill_file = entry / SKILL_FILE
        if not entry.is_dir() or not skill_file.is_file():
            continue
        try:
            fields = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        except OSError:
            continue
        if not fields:
            continue
        name = fields.get("name", "")
        if (
            not name
            or name in found
            or not name.replace("_", "").isalnum()
            or entry.name != name
            or not fields.get("description")
        ):
            continue
        found[name] = SkillSpec(
            name=name,
            description=fields["description"],
            tools=_split_list(fields.get("tools", "")),
            capabilities=_split_list(fields.get("capabilities", "")),
            path=skill_file,
        )
    return found


def read_skill(directory: Path | None, name: str, command: str | None = None) -> str | None:
    """Lazy-load: SKILL.md saja, atau + satu file commands/<command>.md."""
    skills = discover_skills(directory)
    spec = skills.get(name)
    if spec is None:
        return None
    try:
        text = spec.path.read_text(encoding="utf-8")
    except OSError:
        return None
    if command is None:
        return text
    if not command.replace("_", "").replace("-", "").isalnum() or ".." in command:
        return None
    try:
        return (spec.path.parent / COMMANDS_DIR / f"{command}.md").read_text(encoding="utf-8")
    except OSError:
        return None


def skill_sha(spec: SkillSpec) -> str:
    try:
        return hashlib.sha256(spec.path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "unreadable"
