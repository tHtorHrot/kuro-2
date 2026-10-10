"""Owner-scoped health/queue snapshot. Heartbeats do not establish provider validity."""

from datetime import timedelta

from sqlalchemy import func, select

from jarvis.storage.models import (
    AssistantState,
    CalendarNotification,
    Document,
    KnowledgeState,
    TelegramReceipt,
    TelegramState,
    ToolAction,
    ToolGrant,
)
from jarvis.tools.journal import now_utc


async def snapshot(db, owner):
    ready = await db.ready()
    now = now_utc()
    async with db.tenant(owner) as session:
        actions = dict(
            (
                await session.execute(
                    select(ToolAction.status, func.count())
                    .where(ToolAction.owner_id == owner)
                    .group_by(ToolAction.status)
                )
            ).all()
        )
        due = await session.scalar(
            select(func.min(ToolAction.due_at)).where(
                ToolAction.owner_id == owner,
                ToolAction.status.in_({"queued", "claimed"}),
                ToolAction.due_at <= now,
            )
        )
        stale = await session.scalar(
            select(func.count())
            .select_from(ToolAction)
            .where(
                ToolAction.owner_id == owner,
                ToolAction.status.in_({"claimed", "dispatching"}),
                ToolAction.lease_until <= now,
            )
        )
        delivery = await session.scalar(
            select(func.count())
            .select_from(TelegramReceipt)
            .where(
                TelegramReceipt.owner_id == owner,
                TelegramReceipt.delivery_status.in_({"pending", "sending"}),
            )
        )
        notifications = await session.scalar(
            select(func.count())
            .select_from(CalendarNotification)
            .where(
                CalendarNotification.owner_id == owner,
                CalendarNotification.delivery_status.in_({"pending", "sending"}),
            )
        )
        documents = dict(
            (
                await session.execute(
                    select(Document.status, func.count())
                    .where(Document.owner_id == owner)
                    .group_by(Document.status)
                )
            ).all()
        )
        states = {
            "telegram": await session.get(TelegramState, owner),
            "assistant": await session.get(AssistantState, owner),
            "knowledge": await session.get(KnowledgeState, owner),
            "scheduler": await session.get(ToolGrant, (owner, "calendar")),
        }
        heartbeat = {}
        for name, state in states.items():
            expected = state is not None and (
                name not in {"assistant", "scheduler"} or state.enabled
            )
            age = (
                (now - state.last_poll_at).total_seconds() if state and state.last_poll_at else None
            )
            heartbeat[name] = {
                "expected": expected,
                "age_seconds": age,
                "recent": age is not None and age <= timedelta(minutes=2).total_seconds(),
            }
    return {
        "database_ready": ready,
        "heartbeat": heartbeat,
        "actions": actions,
        "due_age_seconds": max(0, (now - due).total_seconds()) if due else None,
        "stale_leases": stale,
        "delivery_backlog": delivery + notifications,
        "documents": documents,
        "provider_auth": "not_verified_by_heartbeat",
        "tasks": await _task_snapshot(session, owner),
    }


async def _task_snapshot(session, owner):
    from jarvis.operations.tasks import snapshot as task_snapshot

    try:
        return await task_snapshot(session, owner)
    except Exception:
        return {"error": "task_snapshot_unavailable"}
