"""Agent Manager — Bagian 6.1 MD.

Memilih role/backend, membatasi concurrency, mengelola worker/run.
AgentSpec != process; tidak spawn rekursif tanpa batas. Default maksimal
dua worker aktif (Bagian 9.1); task dependen dikerjakan sequential.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from jarvis.agents.roles import get_role
from jarvis.orchestration.contracts import MAX_ACTIVE_WORKERS, TaskError
from jarvis.storage.models import Task, TaskRun

RUN_LEASE = timedelta(seconds=300)


def _now():
    return datetime.now(UTC)


@dataclass
class WorkerSlot:
    worker_id: str
    run_id: UUID | None = None
    busy_since: datetime | None = None


@dataclass
class AgentManager:
    max_workers: int = MAX_ACTIVE_WORKERS
    slots: dict[str, WorkerSlot] = field(default_factory=dict)

    def __post_init__(self):
        if not 1 <= self.max_workers <= 4:
            raise ValueError("max_workers must be 1..4")

    def available_slot(self) -> WorkerSlot | None:
        for slot in self.slots.values():
            if slot.run_id is None:
                return slot
        if len(self.slots) < self.max_workers:
            slot = WorkerSlot(worker_id=f"worker-{len(self.slots) + 1}")
            self.slots[slot.worker_id] = slot
            return slot
        return None


async def claim_task(
    db,
    owner: UUID,
    *,
    worker_instance: str,
    roles: list[str] | None = None,
    model_route: str = "standard",
) -> TaskRun | None:
    """Claim atomik satu live attempt per task; dependencies harus fulfilled."""
    async with db.tenant(owner) as session:
        active = await session.scalar(
            select(func.count())
            .select_from(TaskRun)
            .where(
                TaskRun.owner_id == owner,
                TaskRun.status.in_(("claimed", "running")),
            )
        )
        if (active or 0) >= MAX_ACTIVE_WORKERS:
            return None
        stmt = (
            select(Task)
            .where(
                Task.owner_id == owner,
                Task.status.in_(("queued", "running")),
            )
            .order_by(Task.priority.desc(), Task.created_at)
            .limit(10)
        )
        if roles:
            stmt = stmt.where(Task.role.in_(roles))
        candidates = (await session.scalars(stmt.with_for_update(skip_locked=True))).all()
        for task in candidates:
            # Dependencies harus succeeded semua.
            from jarvis.storage.models import TaskDependency

            deps = (
                await session.scalars(
                    select(TaskDependency).where(
                        TaskDependency.owner_id == owner, TaskDependency.task_id == task.id
                    )
                )
            ).all()
            if deps:
                need = {d.depends_on_id for d in deps}
                done = set(
                    (
                        await session.scalars(
                            select(Task.id).where(
                                Task.owner_id == owner,
                                Task.id.in_(need),
                                Task.status == "succeeded",
                            )
                        )
                    ).all()
                )
                if done != need:
                    continue
            dupe = await session.scalar(
                select(TaskRun)
                .where(
                    TaskRun.owner_id == owner,
                    TaskRun.task_id == task.id,
                    TaskRun.status.in_(("claimed", "running")),
                )
                .with_for_update()
            )
            if dupe is not None:
                continue
            try:
                role = get_role(task.role)
            except ValueError:
                continue
            attempt = (
                await session.scalar(
                    select(func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.owner_id == owner, TaskRun.task_id == task.id)
                )
                or 0
            )
            run = TaskRun(
                id=uuid4(),
                owner_id=owner,
                task_id=task.id,
                attempt=(attempt or 0) + 1,
                worker_instance=worker_instance,
                generation=1,
                lease_token=uuid4(),
                lease_expires_at=_now() + RUN_LEASE,
                heartbeat_at=_now(),
                status="claimed",
                model_route=f"{role.model_class}:{model_route}",
            )
            session.add(run)
            task.status = "running"
            task.updated_at = _now()
            from jarvis.storage.models import TaskEvent

            session.add(
                TaskEvent(
                    owner_id=owner,
                    task_id=task.id,
                    run_id=run.id,
                    event_type="run.claimed",
                    payload={"worker": worker_instance, "role": task.role},
                )
            )
            await session.flush()
            return run
    return None


async def heartbeat_run(db, owner: UUID, run_id: UUID, lease_token: UUID) -> None:
    """Stale worker tidak memperpanjang run baru (generation/lease fencing)."""
    async with db.tenant(owner) as session:
        run = await session.get(TaskRun, run_id, with_for_update=True)
        if run is None or run.owner_id != owner:
            raise TaskError("run_not_found")
        if run.lease_token != lease_token or run.status not in ("claimed", "running"):
            raise TaskError("stale_run_lease")
        if run.lease_expires_at is not None and run.lease_expires_at <= _now():
            raise TaskError("run_lease_expired")
        run.lease_expires_at = _now() + RUN_LEASE
        run.heartbeat_at = _now()
        if run.status == "claimed":
            run.status = "running"


async def finish_run(
    db, owner: UUID, run_id: UUID, lease_token: UUID, status: str, *, error_code: str | None = None
) -> None:
    if status not in ("succeeded", "failed", "lost", "cancelled", "uncertain"):
        raise TaskError("run_status_invalid")
    async with db.tenant(owner) as session:
        run = await session.get(TaskRun, run_id, with_for_update=True)
        if run is None or run.owner_id != owner:
            raise TaskError("run_not_found")
        if run.lease_token != lease_token:
            raise TaskError("stale_run_lease")
        run.status = status
        run.error_code = error_code
        run.finished_at = _now()
        run.lease_token = None
        from jarvis.storage.models import TaskEvent

        session.add(
            TaskEvent(
                owner_id=owner,
                task_id=run.task_id,
                run_id=run.id,
                event_type=f"run.{status}",
                payload={"error": error_code} if error_code else {},
            )
        )
