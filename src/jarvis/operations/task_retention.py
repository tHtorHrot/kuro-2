"""Task retention — batch pruning untuk event log turunan.

Hanya menghapus baris task_events lewat umur retensi. TIDAK menyentuh tasks,
runs, artifacts, journal, atau record uncertain/failed. Tanpa --apply hanya
menghitung (dry-run). Full-table delete saat startup dilarang; pakai batch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select

from jarvis.storage.models import TaskEvent


async def count_prunable(session, owner: UUID, older_than_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    return (
        await session.scalar(
            select(func.count())
            .select_from(TaskEvent)
            .where(TaskEvent.owner_id == owner, TaskEvent.created_at < cutoff)
        )
        or 0
    )


async def prune_events(
    db, owner: UUID, *, older_than_days: int = 90, limit: int = 500, apply: bool = False
) -> dict:
    if not 7 <= older_than_days <= 3650:
        raise ValueError("older_than_days must be 7..3650")
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be 1..5000")
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    async with db.tenant(owner) as session:
        ids = (
            await session.scalars(
                select(TaskEvent.id)
                .where(TaskEvent.owner_id == owner, TaskEvent.created_at < cutoff)
                .order_by(TaskEvent.id)
                .limit(limit)
            )
        ).all()
        deleted = 0
        if apply and ids:
            result = await session.execute(
                delete(TaskEvent).where(TaskEvent.owner_id == owner, TaskEvent.id.in_(ids))
            )
            deleted = result.rowcount or 0
        return {"prunable": len(ids), "deleted": deleted, "applied": apply}
