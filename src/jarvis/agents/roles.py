"""Logical agent roles — Bagian 6.1 MD.

Role adalah konfigurasi capability/prompt, bukan alasan membuat satu
service per agent. Lima role dimuat sesuai kebutuhan task; default awal
satu core planner dan maksimal dua worker aktif.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleSpec:
    name: str
    description: str
    tool_allowlist: frozenset[str]
    model_class: str  # economy | standard | reasoning
    max_steps: int = 8
    context_budget_tokens: int = 8000
    # Stage 7: capability deklaratif + skill kanonis (data saja; lihat skills/).
    capabilities: frozenset[str] = frozenset()
    skill: str | None = None


ROLES: dict[str, RoleSpec] = {
    "research": RoleSpec(
        name="research",
        description="Pencarian/reading sumber, evidence notes, citation provenance.",
        tool_allowlist=frozenset({"knowledge_search", "knowledge_read"}),
        model_class="economy",
        max_steps=6,
        capabilities=frozenset({"read_only", "local_index", "citations"}),
        skill="research",
    ),
    "coding": RoleSpec(
        name="coding",
        description="Repo inspection, code/test/build dalam workspace terisolasi.",
        tool_allowlist=frozenset({"workspace_read", "workspace_write", "code_exec"}),
        model_class="standard",
        max_steps=12,
        context_budget_tokens=16000,
        capabilities=frozenset({"workspace_write", "code_exec"}),
    ),
    "knowledge": RoleSpec(
        name="knowledge",
        description="Ingest, retrieve, resolve evidence dan approved memory proposals.",
        tool_allowlist=frozenset({"knowledge_search", "knowledge_read"}),
        model_class="economy",
        max_steps=6,
        capabilities=frozenset({"read_only", "local_index"}),
        skill="knowledge",
    ),
    "data": RoleSpec(
        name="data",
        description="Analisis terstruktur, perhitungan reproducible, charts/tables.",
        tool_allowlist=frozenset({"workspace_read", "code_exec", "knowledge_read"}),
        model_class="standard",
        max_steps=10,
        capabilities=frozenset({"workspace_read", "code_exec"}),
    ),
    "communication": RoleSpec(
        name="communication",
        description="Draft, format, recipient mapping dan authorized send.",
        tool_allowlist=frozenset({"draft_write"}),
        model_class="economy",
        max_steps=4,
        capabilities=frozenset({"draft_write"}),
    ),
    "planner": RoleSpec(
        name="planner",
        description="Core planner: menyusun plan terstruktur, tanpa tool write.",
        tool_allowlist=frozenset(),
        model_class="reasoning",
        max_steps=4,
        capabilities=frozenset({"plan_only"}),
        skill="planner",
    ),
    "documents": RoleSpec(
        name="documents",
        description="Tulis file deterministik ke artifact store berversi.",
        tool_allowlist=frozenset({"artifact_write", "knowledge_read"}),
        model_class="economy",
        max_steps=4,
        capabilities=frozenset({"artifact_write", "versioned"}),
        skill="documents",
    ),
}

ALLOWED_ROLES = frozenset(ROLES)


def role_exists(name: str) -> bool:
    return name in ROLES


def get_role(name: str) -> RoleSpec:
    try:
        return ROLES[name]
    except KeyError:
        raise ValueError("unknown_role") from None


def require_capability(roles: list[str], capability: str) -> None:
    """Tolak role tanpa capability sebelum claim; tanpa pengecualian diam-diam."""
    offenders = [name for name in roles if capability not in get_role(name).capabilities]
    if offenders:
        raise ValueError(f"capability_denied:{capability}:{','.join(sorted(offenders))}")


def has_capability(role: str, capability: str) -> bool:
    return capability in get_role(role).capabilities
