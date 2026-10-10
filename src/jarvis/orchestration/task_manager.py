"""Task Manager — Bagian 6.1 MD.

State transition, admission, dependency release, cancellation dan attempts.
DB authority; idempotent commands. Satu task-state writer awal agar urutan
event terserialisasi; jangan pakai BIGSERIAL > last_seen secara naif
sebagai queue (lihat api/task_events.py).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from jarvis.orchestration.contracts import (
    MAX_GOAL_LEN,
    SubmitGoalInput,
    TaskError,
    TaskStatus,
    ValidatedPlan,
)
from jarvis.orchestration.planner import validate_plan
from jarvis.storage.models import Task, TaskDependency, TaskEvent, TaskRun

RUN_LEASE = timedelta(seconds=300)
RUN_HEARTBEAT_TIMEOUT = timedelta(seconds=120)


def _payload_hash(goal: str, constraints: dict, plan_keys: list[str]) -> str:
    raw = json.dumps(
        {"goal": goal, "constraints": constraints, "plan": plan_keys},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def _emit(
    session,
    owner: UUID,
    task_id: UUID | None,
    event_type: str,
    payload: dict | None = None,
    run_id: UUID | None = None,
) -> None:
    session.add(
        TaskEvent(
            owner_id=owner,
            task_id=task_id,
            run_id=run_id,
            event_type=event_type,
            payload=payload or {},
        )
    )


async def submit_goal(
    db,
    inp: SubmitGoalInput,
    *,
    plan: ValidatedPlan | None = None,
    plan_keys: list[str] | None = None,
) -> Task:
    """Idempotent: same key + same payload -> same task; mismatch ditolak."""
    if not inp.goal or len(inp.goal) > MAX_GOAL_LEN:
        raise TaskError("goal_invalid")
    if not inp.client_request_key or len(inp.client_request_key) > 128:
        raise TaskError("request_key_required")
    keys = plan_keys or ([n.title for n in plan.nodes] if plan else [inp.goal[:80]])
    digest = _payload_hash(inp.goal.strip(), inp.constraints, keys)
    async with db.tenant(inp.owner_id) as session:
        existing = await session.scalar(
            select(Task).where(
                Task.owner_id == inp.owner_id,
                Task.client_request_key == inp.client_request_key,
            )
        )
        if existing is not None:
            if existing.payload_hash != digest:
                raise TaskError("request_key_payload_mismatch")
            return existing
        root = Task(
            id=uuid4(),
            owner_id=inp.owner_id,
            client_request_key=inp.client_request_key,
            payload_hash=digest,
            title=inp.goal.strip()[:120],
            goal=inp.goal.strip(),
            role="planner",
            acceptance={"criteria": ["goal selesai dan lolos acceptance"]},
            plan_json={"nodes": keys},
            plan_revision=plan.revision if plan else 1,
            status=TaskStatus.QUEUED.value,
            cost_ceiling_usd=Decimal(str(inp.cost_ceiling_usd)),
            deadline_at=_now() + timedelta(seconds=inp.deadline_seconds)
            if inp.deadline_seconds > 0
            else None,
        )
        root.root_id = root.id
        session.add(root)
        await session.flush()
        await _emit(
            session, inp.owner_id, root.id, "goal.submitted", {"key": inp.client_request_key}
        )
        # Subtasks dari validated plan (dibuat sebagai child tasks).
        if plan is not None:
            key_to_id: dict[str, UUID] = {}
            for i, node in enumerate(plan.nodes):
                child = Task(
                    id=uuid4(),
                    owner_id=inp.owner_id,
                    parent_id=root.id,
                    root_id=root.id,
                    title=node.title,
                    role=node.role,
                    input_refs={"refs": list(node.input_refs)},
                    acceptance=dict(node.acceptance),
                    plan_revision=plan.revision,
                    status=TaskStatus.WAITING_DEPENDENCY.value
                    if node.depends_on
                    else TaskStatus.QUEUED.value,
                    cost_ceiling_usd=Decimal(str(node.cost_ceiling_usd)),
                )
                session.add(child)
                # Cari key asli via urutan (plan_keys tidak disimpan di node).
                key_to_id[f"t{i}"] = child.id
            await session.flush()
            # Dependencies — key mapping t0..tn sesuai urutan validate_plan.
            ordered_keys = [f"t{i}" for i in range(len(plan.nodes))]
            for node, ckey in zip(plan.nodes, ordered_keys, strict=True):
                child_id = key_to_id[ckey]
                for dep in node.depends_on:
                    # dep merujuk key user (mis. "t0"); fallback ke urutan.
                    dep_id = key_to_id.get(dep)
                    if dep_id is None:
                        continue
                    session.add(
                        TaskDependency(
                            owner_id=inp.owner_id, task_id=child_id, depends_on_id=dep_id
                        )
                    )
            await _emit(
                session,
                inp.owner_id,
                root.id,
                "plan.committed",
                {"tasks": len(plan.nodes), "revision": plan.revision},
            )
        return root


async def create_plan_tasks(db, owner: UUID, root_id: UUID, raw_nodes: list[dict]) -> list[Task]:
    """Buat subtasks dari structured JSON yang sudah divalidasi."""
    plan = validate_plan(raw_nodes)
    async with db.tenant(owner) as session:
        root = await session.get(Task, root_id)
        if root is None or root.owner_id != owner:
            raise TaskError("root_not_found")
        if root.status in ("succeeded", "failed", "cancelled"):
            raise TaskError("root_terminal")
        created: list[Task] = []
        key_to_id: dict[str, UUID] = {}
        # Key user dipertahankan sesuai input untuk dependency mapping.
        user_keys = [n.get("key") or f"t{i}" for i, n in enumerate(raw_nodes)]
        for raw_key, node in zip(user_keys, plan.nodes, strict=True):
            child = Task(
                id=uuid4(),
                owner_id=owner,
                parent_id=root.id,
                root_id=root.id,
                title=node.title,
                role=node.role,
                input_refs={"refs": list(node.input_refs)},
                acceptance=dict(node.acceptance),
                plan_revision=plan.revision,
                status=TaskStatus.WAITING_DEPENDENCY.value
                if node.depends_on
                else TaskStatus.QUEUED.value,
                cost_ceiling_usd=Decimal(str(node.cost_ceiling_usd)),
            )
            session.add(child)
            key_to_id[raw_key] = child.id
            created.append(child)
        await session.flush()
        for raw_key, node in zip(user_keys, plan.nodes, strict=True):
            for dep in node.depends_on:
                if dep not in key_to_id:
                    raise TaskError("plan_unknown_dependency")
                session.add(
                    TaskDependency(
                        owner_id=owner, task_id=key_to_id[raw_key], depends_on_id=key_to_id[dep]
                    )
                )
        root.plan_revision = plan.revision
        root.plan_json = {"nodes": user_keys}
        root.updated_at = _now()
        await _emit(
            session,
            owner,
            root.id,
            "plan.committed",
            {"tasks": len(created), "revision": plan.revision},
        )
        return created


async def _dependencies_met(session, owner: UUID, task_id: UUID) -> bool:
    deps = (
        await session.scalars(
            select(TaskDependency).where(
                TaskDependency.owner_id == owner, TaskDependency.task_id == task_id
            )
        )
    ).all()
    if not deps:
        return True
    need = {d.depends_on_id for d in deps}
    done = (
        await session.scalars(
            select(Task.id).where(
                Task.owner_id == owner, Task.id.in_(need), Task.status == TaskStatus.SUCCEEDED.value
            )
        )
    ).all()
    return set(done) == need


async def release_ready(db, owner: UUID, *, limit: int = 25) -> int:
    """Dependency release: waiting_dependency -> queued bila semua deps succeeded."""
    changed = 0
    async with db.tenant(owner) as session:
        rows = (
            await session.scalars(
                select(Task)
                .where(
                    Task.owner_id == owner,
                    Task.status == TaskStatus.WAITING_DEPENDENCY.value,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for task in rows:
            if await _dependencies_met(session, owner, task.id):
                task.status = TaskStatus.QUEUED.value
                task.updated_at = _now()
                await _emit(session, owner, task.id, "task.released", {})
                changed += 1
    return changed


async def cancel_task(db, owner: UUID, task_id: UUID) -> Task:
    """Stop future dispatch; cancellation request dan provider effect dicatat terpisah.

    Uncertain BOLEH di-cancel eksplisit (operator reconcile path): tidak ada
    dispatch baru, efek terdahulu tetap dicatat. Succeeded/failed/cancelled
    adalah no-op.
    """
    async with db.tenant(owner) as session:
        task = await session.get(Task, task_id, with_for_update=True)
        if task is None or task.owner_id != owner:
            raise TaskError("task_not_found")
        if task.status in ("succeeded", "failed", "cancelled"):
            return task
        task.status = TaskStatus.CANCELLED.value
        task.updated_at = _now()
        runs = (
            await session.scalars(
                select(TaskRun)
                .where(
                    TaskRun.owner_id == owner,
                    TaskRun.task_id == task.id,
                    TaskRun.status.in_(("claimed", "running")),
                )
                .with_for_update()
            )
        ).all()
        for run in runs:
            run.status = "cancelled"
            run.finished_at = _now()
            run.lease_token = None
        await _emit(session, owner, task.id, "task.cancelled", {"runs_cancelled": len(runs)})
        return task


async def maybe_complete_parent(db, owner: UUID, task_id: UUID) -> Task | None:
    """Rollup jujur: parent mengikuti status terminal terburuk anak-anaknya,
    hanya bila SEMUA anak sudah terminal.

    Prioritas: failed > uncertain > cancelled > succeeded. Tidak menebak
    hasil; anak non-terminal (queued/running/waiting) memblokir rollup
    sampai operator reconcile. Kembalikan parent bila transisi terjadi.
    """
    async with db.tenant(owner) as session:
        task = await session.get(Task, task_id, with_for_update=True)
        if task is None or task.owner_id != owner:
            return None
        if task.root_id is None or task.id == task.root_id:
            return None
        root = await session.get(Task, task.root_id, with_for_update=True)
        if (
            root is None
            or root.owner_id != owner
            or root.status in ("succeeded", "failed", "cancelled")
        ):
            return None
        kids = (
            await session.scalars(
                select(Task).where(Task.owner_id == owner, Task.parent_id == root.id)
            )
        ).all()
        if not kids:
            return None
        states = {k.status for k in kids}
        if not states.issubset({"succeeded", "failed", "uncertain", "cancelled"}):
            return None
        for candidate in ("failed", "uncertain", "cancelled", "succeeded"):
            if candidate in states:
                resolved = candidate
                break
        root.status = resolved
        root.error_code = None if resolved == "succeeded" else f"rollup_{resolved}_child"
        root.updated_at = _now()
        await _emit(session, owner, root.id, f"task.{resolved}", {"rollup_children": len(kids)})
        return root


async def mark_task(
    db,
    owner: UUID,
    task_id: UUID,
    status: str,
    *,
    error_code: str | None = None,
    run_id: UUID | None = None,
) -> Task:
    allowed = {s.value for s in TaskStatus}
    if status not in allowed:
        raise TaskError("task_status_invalid")
    async with db.tenant(owner) as session:
        task = await session.get(Task, task_id, with_for_update=True)
        if task is None or task.owner_id != owner:
            raise TaskError("task_not_found")
        if task.status in ("succeeded", "failed", "cancelled"):
            raise TaskError("task_terminal")
        # uncertain tidak masuk automatic retry — hanya operator/reconcile boleh keluar.
        if task.status == TaskStatus.UNCERTAIN.value and status in (
            TaskStatus.QUEUED.value,
            TaskStatus.RUNNING.value,
        ):
            raise TaskError("uncertain_requires_reconcile")
        task.status = status
        task.error_code = error_code
        task.updated_at = _now()
        await _emit(
            session,
            owner,
            task.id,
            f"task.{status}",
            {"error": error_code} if error_code else {},
            run_id=run_id,
        )
        closed_id = task.id
    try:
        await maybe_complete_parent(db, owner, closed_id)
    except Exception:
        pass
    async with db.tenant(owner) as session:
        return await session.get(Task, task_id)
