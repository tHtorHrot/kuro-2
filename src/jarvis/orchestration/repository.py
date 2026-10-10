"""Task repository — read model untuk status/progress/operator.

Status tampilan agregat dihitung dari persisted task, approval dan run
facts (pelajaran AO tentang derived status), bukan alasan menghapus
lifecycle task.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from jarvis.storage.models import Artifact, Task, TaskDependency, TaskEvent, TaskRun


async def get_task(session, owner: UUID, task_id: UUID) -> Task | None:
    task = await session.get(Task, task_id)
    if task is None or task.owner_id != owner:
        return None
    return task


async def list_tasks(
    session, owner: UUID, *, root_id: UUID | None = None, status: str | None = None, limit: int = 50
) -> list[Task]:
    stmt = (
        select(Task).where(Task.owner_id == owner).order_by(Task.priority.desc(), Task.created_at)
    )
    if root_id is not None:
        stmt = stmt.where(Task.root_id == root_id)
    if status is not None:
        stmt = stmt.where(Task.status == status)
    return list((await session.scalars(stmt.limit(limit))).all())


async def task_progress(session, owner: UUID, root_id: UUID) -> dict:
    rows = (
        await session.scalars(select(Task).where(Task.owner_id == owner, Task.root_id == root_id))
    ).all()
    total = len(rows)
    by_status: dict[str, int] = {}
    for task in rows:
        by_status[task.status] = by_status.get(task.status, 0) + 1
    done = by_status.get("succeeded", 0)
    return {
        "root_id": str(root_id),
        "total": total,
        "succeeded": done,
        "by_status": by_status,
        "display": f"Menunggu Anda — {done}/{total} task selesai" if total else "Belum ada task",
    }


async def queue_age(session, owner: UUID) -> list[dict]:
    rows = (
        await session.execute(
            select(Task.id, Task.status, Task.created_at, Task.priority)
            .where(
                Task.owner_id == owner, Task.status.in_(("queued", "waiting_dependency", "running"))
            )
            .order_by(Task.created_at)
            .limit(50)
        )
    ).all()
    return [
        {"task_id": str(r[0]), "status": r[1], "created_at": r[2].isoformat(), "priority": r[3]}
        for r in rows
    ]


async def artifacts_for_task(session, owner: UUID, task_id: UUID) -> list[Artifact]:
    return list(
        (
            await session.scalars(
                select(Artifact)
                .where(Artifact.owner_id == owner, Artifact.task_id == task_id)
                .order_by(Artifact.created_at)
            )
        ).all()
    )


async def runs_for_task(session, owner: UUID, task_id: UUID) -> list[TaskRun]:
    return list(
        (
            await session.scalars(
                select(TaskRun)
                .where(TaskRun.owner_id == owner, TaskRun.task_id == task_id)
                .order_by(TaskRun.attempt)
            )
        ).all()
    )


async def dependencies_for(session, owner: UUID, task_id: UUID):
    return list(
        (
            await session.scalars(
                select(TaskDependency).where(
                    TaskDependency.owner_id == owner, TaskDependency.task_id == task_id
                )
            )
        ).all()
    )


async def count_by_status(session, owner: UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Task.status, func.count()).where(Task.owner_id == owner).group_by(Task.status)
        )
    ).all()
    return {status: count for status, count in rows}


async def recent_events(
    session, owner: UUID, *, task_id: UUID | None = None, after_id: int = 0, limit: int = 50
) -> list[TaskEvent]:
    stmt = (
        select(TaskEvent)
        .where(TaskEvent.owner_id == owner, TaskEvent.id > after_id)
        .order_by(TaskEvent.id)
    )
    if task_id is not None:
        stmt = stmt.where(TaskEvent.task_id == task_id)
    return list((await session.scalars(stmt.limit(limit))).all())
