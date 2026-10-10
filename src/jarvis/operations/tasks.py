"""Operator task monitoring — queue age, worker/lease health, uncertain, budget.

Mulai dari status task dan blockers, bukan dashboard kosmetik (Bagian 5).
Heartbeat bukan bukti provider authorization atau correctness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select

from jarvis.storage.models import Task, TaskRun, ToolAction


async def snapshot(session, owner: UUID) -> dict:
    now = datetime.now(UTC)
    counts = dict(
        (
            await session.execute(
                select(Task.status, func.count())
                .where(Task.owner_id == owner)
                .group_by(Task.status)
            )
        ).all()
    )
    active_runs = (
        await session.scalar(
            select(func.count())
            .select_from(TaskRun)
            .where(TaskRun.owner_id == owner, TaskRun.status.in_(("claimed", "running")))
        )
        or 0
    )
    stale_runs = (
        await session.scalar(
            select(func.count())
            .select_from(TaskRun)
            .where(
                TaskRun.owner_id == owner,
                TaskRun.status.in_(("claimed", "running")),
                TaskRun.lease_expires_at <= now,
            )
        )
        or 0
    )
    uncertain = (
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.owner_id == owner, Task.status == "uncertain")
        )
        or 0
    )
    uncertain_actions = (
        await session.scalar(
            select(func.count())
            .select_from(ToolAction)
            .where(ToolAction.owner_id == owner, ToolAction.status == "uncertain")
        )
        or 0
    )
    oldest = await session.scalar(
        select(func.min(Task.created_at)).where(
            Task.owner_id == owner, Task.status.in_(("queued", "waiting_dependency"))
        )
    )
    spent = (
        await session.scalar(
            select(func.coalesce(func.sum(Task.cost_spent_usd), 0)).where(Task.owner_id == owner)
        )
        or 0
    )
    return {
        "tasks_by_status": counts,
        "active_runs": active_runs,
        "stale_runs": stale_runs,
        "uncertain_tasks": uncertain,
        "uncertain_actions": uncertain_actions,
        "oldest_queued_at": oldest.isoformat() if oldest else None,
        "cost_spent_usd": str(spent),
        "checked_at": now.isoformat(),
    }
