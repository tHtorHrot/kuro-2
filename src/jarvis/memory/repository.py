"""Memory repository — explicit profile + bounded episodic task memory.

Hanya outcome berguna yang disimpan, dengan expiry/importance/provenance.
Conflicting facts disimpan dengan source/date, bukan last-write-wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

KINDS = frozenset({"profile", "preference", "project", "episodic", "task"})
SOURCES = frozenset({"user", "validated", "inference"})
STATUSES = frozenset({"active", "superseded", "deleted"})

PROJECT_PATTERN = r"[a-z][a-z0-9_-]{0,39}"

KIND_WEIGHT = {"preference": 30, "profile": 20, "project": 20, "task": 10, "episodic": 10}
MAX_CONTEXT_CHARS = 4000
MAX_CONTEXT_FACTS = 20


@dataclass(frozen=True)
class MemoryFact:
    key: str
    value: str
    provenance: str
    expires_at: datetime | None = None
    importance: float = 0.5
    kind: str = "profile"
    source: str = "inference"
    project: str | None = None


class MemoryPolicyError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def validate_fact(fact: MemoryFact) -> None:
    if not fact.key or len(fact.key) > 40:
        raise MemoryPolicyError("memory_key_invalid")
    if not fact.value or len(fact.value.encode()) > 2000:
        raise MemoryPolicyError("memory_value_invalid")
    if not fact.provenance:
        raise MemoryPolicyError("memory_provenance_required")
    if not 0 <= fact.importance <= 1:
        raise MemoryPolicyError("memory_importance_invalid")
    if fact.kind not in KINDS:
        raise MemoryPolicyError("memory_kind_invalid")
    if fact.source not in SOURCES:
        raise MemoryPolicyError("memory_source_invalid")
    if fact.project is not None:
        import re

        if not re.fullmatch(PROJECT_PATTERN, fact.project):
            raise MemoryPolicyError("memory_project_invalid")


def default_expiry(*, days: int = 90) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def rank_facts(
    facts: list[dict],
    *,
    budget_chars: int = MAX_CONTEXT_CHARS,
    now=None,
    project: str | None = None,
) -> list[dict]:
    """Deterministic context selection: kind priors, importance, recency, char budget.

    Project scoping: global facts (project None) always compete; facts tagged
    to another project never surface. A fact of the active project outranks an
    otherwise equal global one. Defense in depth: only explicit private facts
    are ever selected, even if the caller forgets to filter.
    """
    moment = now or datetime.now(UTC)
    scored = []
    for fact in facts:
        if fact.get("data_class", "private") != "private":
            continue
        if fact.get("status", "active") != "active":
            continue
        expires = fact.get("expires_at")
        if expires is not None and expires <= moment:
            continue
        tag = fact.get("project")
        if tag is not None and tag != project:
            continue
        updated = fact.get("updated_at")
        recent = (
            10 if isinstance(updated, datetime) and (moment - updated) <= timedelta(days=7) else 0
        )
        score = (
            KIND_WEIGHT.get(fact.get("kind"), 0)
            + float(fact.get("importance") or 0) * 5
            + recent
            + (25 if tag is not None and project is not None else 0)
        )
        scored.append((score, fact.get("key") or "", fact))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked, used = [], 0
    for _, _, fact in scored:
        cost = len(fact.get("value") or "")
        if len(picked) >= MAX_CONTEXT_FACTS or used + cost > budget_chars:
            break
        picked.append(fact)
        used += cost
    return picked
