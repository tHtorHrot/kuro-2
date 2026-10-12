"""Native PG: satu pengingat approval, tidak spam, basi diblokir."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from test_calendar_chat import setup
from test_calendar_tasks import approve, draft, finish_draft

from jarvis.interfaces.telegram.notifications import claim_notification
from jarvis.orchestration.calendar_tasks import remind_approvals
from jarvis.storage.models import AssistantState, CalendarNotification, ToolAction
from jarvis.tools.journal import now_utc

pytestmark = pytest.mark.integration


async def state_of(db, owner):
    async with db.tenant(owner) as session:
        return await session.get(AssistantState, owner)


async def nudge_rows(db, owner):
    async with db.tenant(owner) as session:
        return (
            await session.scalars(
                select(CalendarNotification).where(
                    CalendarNotification.owner_id == owner,
                    CalendarNotification.event_key.startswith("nudge:"),
                )
            )
        ).all()


async def test_approval_reminded_once_then_stale_reminder_blocked(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await draft(tg, repo)
    row = await finish_draft(tg, repo)
    assert row.status == "awaiting_approval"
    async with test_db.tenant(repo.owner) as session:
        action = await session.get(ToolAction, row.id)
        action.approval_expires_at = now_utc() + timedelta(minutes=2)
    state = await state_of(test_db, repo.owner)
    async with test_db.tenant(repo.owner) as session:
        assert await remind_approvals(session, repo.owner, state) == 1
    async with test_db.tenant(repo.owner) as session:
        assert await remind_approvals(session, repo.owner, state) == 0
    rows = await nudge_rows(test_db, repo.owner)
    assert len(rows) == 1 and rows[0].delivery_status == "pending"
    assert rows[0].reply_text.startswith("Pengingat 1x:")
    # Disetujui tepat sebelum pengingat terkirim → pengingat basi diblokir.
    await approve(tg, row)
    async with test_db.tenant(repo.owner) as session:
        assert await claim_notification(tg, session, now_utc()) is None
    rows = await nudge_rows(test_db, repo.owner)
    assert rows[0].delivery_status == "blocked" and rows[0].reply_text is None


async def test_far_expiry_gets_no_reminder(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await draft(tg, repo)
    row = await finish_draft(tg, repo)
    async with test_db.tenant(repo.owner) as session:
        action = await session.get(ToolAction, row.id)
        action.approval_expires_at = now_utc() + timedelta(minutes=9)
    state = await state_of(test_db, repo.owner)
    async with test_db.tenant(repo.owner) as session:
        assert await remind_approvals(session, repo.owner, state) == 0
    assert await nudge_rows(test_db, repo.owner) == []
