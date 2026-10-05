"""Trusted Stage 4 operator surface. Never expose credential values or raw action arguments."""

import asyncio
import signal
from uuid import UUID

from sqlalchemy import func, select

from jarvis.core.config import load_settings
from jarvis.integrations.calendar.activation import activate_google_calendar
from jarvis.integrations.calendar.agent import calendar_tool_specs
from jarvis.integrations.calendar.config import calendar_binding, load_calendar_secrets
from jarvis.storage.database import Database
from jarvis.storage.models import ToolAction, ToolGrant
from jarvis.tools.journal import ActionJournal, now_utc
from jarvis.tools.registry import ToolRegistry

SCOPES = frozenset({"calendar:read", "calendar:write", "calendar:send"})


async def grant_calendar(owner_id, scopes, *, enabled):
    from jarvis.tools.authority import set_grant

    if not scopes.issubset(SCOPES):
        raise ValueError("Unknown Calendar scope")
    db = Database(load_settings())
    try:
        await db.verify_runtime_role()
        binding = None
        if enabled:
            secrets = load_calendar_secrets()
            binding = calendar_binding(
                secrets.client_id, secrets.refresh_token, secrets.calendar_id
            )
        return await set_grant(
            db, owner_id, "calendar", scopes, enabled=enabled, binding_fingerprint=binding
        )
    finally:
        await db.close()


async def activation(owner_id: UUID):
    settings = load_settings()
    db = Database(settings)
    await db.verify_runtime_role()
    secrets = load_calendar_secrets()
    active = activate_google_calendar(
        db,
        owner_id,
        client_id=secrets.client_id,
        client_secret=secrets.client_secret,
        refresh_token=secrets.refresh_token,
        calendar_id=secrets.calendar_id,
    )
    return db, active


async def action_status(owner_id: UUID) -> dict:
    settings = load_settings()
    db = Database(settings)
    await db.verify_runtime_role()
    try:
        async with db.tenant(owner_id) as session:
            rows = (
                await session.execute(
                    select(ToolAction.status, func.count())
                    .where(ToolAction.owner_id == owner_id)
                    .group_by(ToolAction.status)
                )
            ).all()
            oldest = await session.scalar(
                select(func.min(ToolAction.due_at)).where(
                    ToolAction.owner_id == owner_id,
                    ToolAction.status == "queued",
                    ToolAction.due_at <= now_utc(),
                )
            )
            grant = await session.get(ToolGrant, (owner_id, "calendar"))
            age = (
                (now_utc() - grant.last_poll_at).total_seconds()
                if grant and grant.last_poll_at
                else None
            )
        return {
            "owner_id": str(owner_id),
            "actions": dict(rows),
            "stage": 4,
            "worker_recent": age is not None and age < 120,
            "heartbeat_age_seconds": age,
            "calendar_enabled": bool(grant and grant.enabled),
            "oldest_due_age_seconds": (now_utc() - oldest).total_seconds() if oldest else 0,
        }
    finally:
        await db.close()


async def _journal(owner_id: UUID):
    settings = load_settings()
    db = Database(settings)
    await db.verify_runtime_role()
    return db, ActionJournal(db, owner_id, ToolRegistry(calendar_tool_specs()))


async def approve(owner_id: UUID, action_id: UUID, fingerprint: str) -> dict:
    db, journal = await _journal(owner_id)
    try:
        await journal.approve(action_id, fingerprint)
        return {"action_id": str(action_id), "status": "queued"}
    finally:
        await db.close()


async def reconcile(owner_id: UUID, action_id: UUID) -> dict:
    from jarvis.integrations.calendar.recovery import reconcile_solo_create

    db, active = await activation(owner_id)
    try:
        return await reconcile_solo_create(active.journal, active.provider, action_id)
    finally:
        await db.close()


async def cancel(owner_id: UUID, action_id: UUID) -> dict:
    db, journal = await _journal(owner_id)
    try:
        await journal.cancel(action_id)
        return {"action_id": str(action_id), "status": "cancelled"}
    finally:
        await db.close()


async def run_scheduler(owner_id: UUID, *, once: bool = False) -> dict:
    db, active = await activation(owner_id)
    try:
        if once:
            r = await active.scheduler.run_pass(max_actions=25)
            return {
                "recovered": r.recovered,
                "processed": r.processed,
                "outcomes": [x.outcome for x in r.results],
            }
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass

        async def stopped():
            return stop.is_set()

        await active.scheduler.run_forever(stop=stopped, idle_seconds=1.0, max_actions_per_pass=25)
        return {"stopped": True}
    finally:
        await db.close()
