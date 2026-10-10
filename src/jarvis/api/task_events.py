"""Task event feed — durable progress events dan operator status.

task_events ditulis bersama task transition dalam transaksi yang sama;
transport live hanya membaca event yang committed. Untuk fase satu-host,
polling dengan cursor cukup. SSE ditambahkan bila UI butuh live progress.

Anti-pola yang dihindari: `BIGSERIAL > last_seen` naif dapat melewatkan row
yang baru commit dengan sequence lebih kecil bila ada beberapa writer.
Target awal satu task-state writer sehingga cursor monoton aman; dokumen ini
menegaskan kontraknya dan membatasi limit agar client yang offline lama
mengambil snapshot baru bila cursor keluar retention window.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from jarvis.api.dependencies import CurrentPrincipal, TenantSession
from jarvis.orchestration import repository as task_repo

router = APIRouter(prefix="/api/v1/task-events", tags=["task-events"])

SNAPSHOT_THRESHOLD = 1000


@router.get("")
async def poll(
    actor: CurrentPrincipal,
    session: TenantSession,
    task_id: UUID | None = None,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    actor.require("tasks:read")
    events = await task_repo.recent_events(
        session, actor.owner_id, task_id=task_id, after_id=after_id, limit=limit + 1
    )
    truncated = len(events) > limit
    events = events[:limit]
    if truncated or (events and after_id > 0 and events[0].id - after_id > SNAPSHOT_THRESHOLD):
        return {
            "snapshot_required": True,
            "after_id": after_id,
            "events": [_view(e) for e in events],
        }
    return {"snapshot_required": False, "events": [_view(e) for e in events]}


def _view(e) -> dict:
    return {
        "id": e.id,
        "task_id": str(e.task_id) if e.task_id else None,
        "run_id": str(e.run_id) if e.run_id else None,
        "event_type": e.event_type,
        "payload": e.payload or {},
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/stream")
async def stream(
    actor: CurrentPrincipal, session: TenantSession, task_id: UUID | None = None, after_id: int = 0
):
    actor.require("tasks:read")
    events = await task_repo.recent_events(
        session, actor.owner_id, task_id=task_id, after_id=after_id, limit=100
    )

    async def _gen():
        for e in events:
            import json

            yield f"data: {json.dumps(_view(e))}\n\n"
        yield "event: snapshot_required\ndata: false\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
