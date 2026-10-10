"""Planner Engine — Bagian 6.1 MD.

Menghasilkan structured plan, dependencies, acceptance criteria, estimasi
budget. Output model harus lolos schema/cycle/capability validation.
Planner tidak memiliki jalan pintas ke credential/provider write.
"""

from __future__ import annotations

from collections import defaultdict, deque

from jarvis.agents.roles import role_exists
from jarvis.orchestration.contracts import (
    MAX_PLAN_DEPTH,
    MAX_PLAN_EDGES,
    MAX_TASKS_PER_PLAN,
    MAX_TITLE_LEN,
    PlanNode,
    TaskError,
    ValidatedPlan,
)


def _check_acceptance(acceptance: dict) -> None:
    if not isinstance(acceptance, dict) or not acceptance:
        raise TaskError("plan_acceptance_required")
    # Acceptance minimal: kriteria yang bisa diperiksa evaluator.
    if "criteria" not in acceptance and "checks" not in acceptance and "done" not in acceptance:
        raise TaskError("plan_acceptance_required")
    import json

    if len(json.dumps(acceptance, ensure_ascii=False).encode()) > 8000:
        raise TaskError("plan_acceptance_too_large")


def validate_plan(nodes: list[dict], *, revision: int = 1) -> ValidatedPlan:
    """Validasi murni (tanpa DB/LLM): schema bounded, cycle rejection, capability."""
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_TASKS_PER_PLAN:
        raise TaskError("plan_task_count_invalid")
    if revision < 1:
        raise TaskError("plan_revision_invalid")

    parsed: list[PlanNode] = []
    keys: list[str] = []
    for i, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise TaskError("plan_node_invalid")
        key = raw.get("key") or f"t{i}"
        if not isinstance(key, str) or not 1 <= len(key) <= 64:
            raise TaskError("plan_node_invalid")
        title = raw.get("title", "")
        if not isinstance(title, str) or not 1 <= len(title) <= MAX_TITLE_LEN:
            raise TaskError("plan_node_invalid")
        role = raw.get("role", "")
        if not isinstance(role, str) or not role_exists(role):
            raise TaskError("plan_unknown_role")
        acceptance = raw.get("acceptance", {})
        _check_acceptance(acceptance)
        depends = tuple(raw.get("depends_on") or ())
        inputs = tuple(raw.get("input_refs") or ())
        if len(depends) > MAX_TASKS_PER_PLAN or len(inputs) > 16:
            raise TaskError("plan_edges_too_many")
        try:
            ceiling = float(raw.get("cost_ceiling_usd", 1.0))
        except (TypeError, ValueError):
            raise TaskError("plan_budget_invalid") from None
        if not 0 <= ceiling <= 1000:
            raise TaskError("plan_budget_invalid")
        keys.append(key)
        parsed.append(
            PlanNode(
                title=title,
                role=role,
                acceptance=dict(acceptance),
                input_refs=inputs,
                depends_on=depends,
                cost_ceiling_usd=ceiling,
            )
        )

    if len(set(keys)) != len(keys):
        raise TaskError("plan_duplicate_key")
    keyset = set(keys)
    for node, key in zip(parsed, keys, strict=True):
        for dep in node.depends_on:
            if dep not in keyset:
                raise TaskError("plan_unknown_dependency")
            if dep == key:
                raise TaskError("plan_self_dependency")

    total_edges = sum(len(n.depends_on) for n in parsed)
    if total_edges > MAX_PLAN_EDGES:
        raise TaskError("plan_edges_too_many")

    # Cycle detection (Kahn).
    indeg = {k: 0 for k in keys}
    children: dict[str, list[str]] = defaultdict(list)
    for node, key in zip(parsed, keys, strict=True):
        for dep in node.depends_on:
            children[dep].append(key)
            indeg[key] += 1
    queue = deque([k for k, d in indeg.items() if d == 0])
    seen = 0
    depth: dict[str, int] = {k: 0 for k in keys}
    while queue:
        current = queue.popleft()
        seen += 1
        for child in children[current]:
            depth[child] = max(depth[child], depth[current] + 1)
            if depth[child] > MAX_PLAN_DEPTH:
                raise TaskError("plan_depth_exceeded")
            indeg[child] -= 1
            if indeg[child] == 0:
                queue.append(child)
    if seen != len(keys):
        raise TaskError("plan_cycle_rejected")

    return ValidatedPlan(nodes=tuple(parsed), revision=revision)


def plan_goal(goal: str, *, capability_snapshot: dict | None = None) -> ValidatedPlan:
    """Fallback deterministik: satu task read-only. LLM planner boleh
    mengusulkan plan lebih besar, tetapi tetap harus lewat validate_plan."""
    if not isinstance(goal, str) or not goal.strip():
        raise TaskError("goal_empty")
    goal = goal.strip()
    role = "research"
    if capability_snapshot and isinstance(capability_snapshot.get("roles"), list):
        available = [r for r in capability_snapshot["roles"] if role_exists(r)]
        if available and "research" not in available:
            role = available[0]
    return validate_plan(
        [
            {
                "key": "t0",
                "title": goal[:MAX_TITLE_LEN],
                "role": role,
                "acceptance": {"criteria": ["hasil ringkas dengan sumber bila ada"]},
            }
        ]
    )
