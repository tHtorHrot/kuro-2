"""Recovery/reconciliation — Bagian 6.6 MD.

Berjalan saat startup dan periodik, batch/timeout bounded. Mengecek
authority, live worker identity, lease, provider handle, artifact manifests
dan unresolved ToolActions. Process exited 0 saja tidak cukup untuk success.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from jarvis.storage.models import Task, TaskEvent, TaskRun

RECOVERY_BATCH = 50
LEASE_GRACE = timedelta(seconds=30)


def _now():
    return datetime.now(UTC)


async def recover_runs(db, owner: UUID) -> dict:
    """Expired claims -> queued ulang bila aman; lost worker -> lost (bukan auto-retry)."""
    stats = {"requeued": 0, "lost": 0, "uncertain_kept": 0}
    async with db.tenant(owner) as session:
        expired = (
            await session.scalars(
                select(TaskRun)
                .where(
                    TaskRun.owner_id == owner,
                    TaskRun.status.in_(("claimed", "running")),
                    TaskRun.lease_expires_at <= _now() - LEASE_GRACE,
                )
                .limit(RECOVERY_BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for run in expired:
            task = await session.get(Task, run.task_id, with_for_update=True)
            if run.status == "claimed":
                run.status = "lost"
                run.finished_at = _now()
                run.error_code = "worker_lost_before_start"
                stats["lost"] += 1
                if task is not None and task.status == "running":
                    task.status = "queued"
                    task.updated_at = _now()
                    stats["requeued"] += 1
            else:
                # running yang lease habis: tandai lost; task jadi uncertain
                # bila ada side effect yang mungkin sudah terbang.
                run.status = "lost"
                run.finished_at = _now()
                run.error_code = "worker_lost_during_run"
                stats["lost"] += 1
                if task is not None and task.status == "running":
                    from jarvis.storage.models import ToolAction

                    writes = await session.scalar(
                        select(ToolAction.id).where(
                            ToolAction.owner_id == owner,
                            ToolAction.task_run_id == run.id,
                            ToolAction.status.in_(("dispatching", "uncertain")),
                        )
                    )
                    task.status = "uncertain" if writes else "queued"
                    task.error_code = "run_lost_reconcile" if writes else None
                    task.updated_at = _now()
            session.add(
                TaskEvent(
                    owner_id=owner,
                    task_id=run.task_id,
                    run_id=run.id,
                    event_type=f"run.{run.status}",
                    payload={"reason": run.error_code or ""},
                )
            )
    return stats


async def startup_reconcile(db, owner: UUID) -> dict:
    """Durable state dan process reality dipertemukan sebelum dispatch baru."""
    from jarvis.orchestration.task_manager import release_ready

    runs = await recover_runs(db, owner)
    released = await release_ready(db, owner)
    return {**runs, "released": released}
