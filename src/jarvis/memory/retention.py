"""Retention memory dan journal — batch dengan indexes.

Tabel audit/cost dapat mempertahankan metadata minimal lebih lama daripada
prompt/PII; failed/uncertain journal tetap dipertahankan sampai reconciled.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BATCH = 500


async def prune_memory(
    db, owner, *, deleted_older_days: int = 30, expired_older_days: int = 90
) -> dict:
    """Hard-delete forgotten tombstones and long-expired facts. Live facts untouched."""
    from sqlalchemy import delete

    from jarvis.storage.models import ProfileMemory

    now = datetime.now(UTC)
    async with db.tenant(owner) as session:
        forgotten = (
            await session.execute(
                delete(ProfileMemory).where(
                    ProfileMemory.owner_id == owner,
                    ProfileMemory.status == "deleted",
                    ProfileMemory.updated_at < now - timedelta(days=deleted_older_days),
                )
            )
        ).rowcount or 0
        stale = (
            await session.execute(
                delete(ProfileMemory).where(
                    ProfileMemory.owner_id == owner,
                    ProfileMemory.expires_at.is_not(None),
                    ProfileMemory.expires_at < now - timedelta(days=expired_older_days),
                )
            )
        ).rowcount or 0
        return {"forgotten_hard_deleted": forgotten, "expired_hard_deleted": stale}


async def prune_expired_task_events(db, owner, *, older_than_days: int = 90) -> int:
    from sqlalchemy import delete

    from jarvis.storage.models import TaskEvent

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    async with db.tenant(owner) as session:
        result = await session.execute(
            delete(TaskEvent)
            .where(TaskEvent.owner_id == owner, TaskEvent.created_at < cutoff)
            .limit(BATCH)
            if hasattr(delete(TaskEvent), "limit")
            else delete(TaskEvent).where(TaskEvent.owner_id == owner, TaskEvent.created_at < cutoff)
        )
        return result.rowcount or 0
