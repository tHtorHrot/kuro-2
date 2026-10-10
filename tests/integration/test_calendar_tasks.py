"""Native PG only: durable jobs, outbox, tenant boundaries and provider crash recovery."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_calendar_chat import setup, submit
from test_telegram import incoming, receipt

from jarvis.integrations.calendar.recovery import reconcile_solo_create
from jarvis.storage.models import (
    AssistantRequest,
    CalendarNotification,
    CalendarTask,
    ExternalIdentity,
    TelegramReceipt,
    ToolAction,
)
from jarvis.tools.authority import set_grant
from jarvis.tools.execution import ExecutionBroker
from jarvis.tools.journal import ActionJournalError, now_utc

pytestmark = pytest.mark.integration


async def task_for(repo):
    async with repo.db.tenant(repo.owner) as session:
        return await session.scalar(select(CalendarTask).order_by(CalendarTask.created_at.desc()))


async def draft(tg, repo):
    assert await submit(tg, repo, "buat rapat besok jam 10") is None
    task = await task_for(repo)
    assert "judul" in (await receipt(tg)).reply_text
    return task


async def finish_draft(tg, repo, number=101):
    return await submit(tg, repo, 'judul "Review"; durasi 60 menit', number)


async def approve(tg, row, number=102):
    await tg.ingest(
        [incoming(tg, number, f"/toolapprove {row.id} {row.action_fingerprint}")], "TestBot"
    )


async def test_restart_replay_and_completion_have_distinct_delivery_identities(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    task = await draft(tg, repo)
    await repo.initialize()  # Same config: simulates recovery of the durable draft.
    await tg.ingest([incoming(tg, 100, "buat rapat besok jam 10")], "TestBot")
    row = await finish_draft(tg, repo)
    assert row.status == "awaiting_approval" and row.fingerprint_version == 2
    async with test_db.tenant(repo.owner) as session:
        saved = await session.get(CalendarTask, task.id)
        assert saved.anchor_at == task.anchor_at
        assert (await session.get(AssistantRequest, row.request_id)).status == "handed_off"
        assert await session.scalar(select(func.count()).select_from(CalendarTask)) == 1
    await approve(tg, row)
    # Acknowledgement is sent on a receipt; completion must survive this receipt being sent.
    async with test_db.tenant(repo.owner) as session:
        receipt_row = await session.get(TelegramReceipt, (repo.owner, tg.config.bot_id, 102))
        receipt_row.delivery_status = "sent"
    assert (await scheduler.run_pass()).processed == 1
    await repo.heartbeat()
    await repo.heartbeat()
    provider.create_event.assert_awaited_once()
    async with test_db.tenant(repo.owner) as session:
        notifications = (await session.scalars(select(CalendarNotification))).all()
        assert len(notifications) == 1 and "provider-event" in notifications[0].reply_text
        assert notifications[0].action_id == row.id
        assert (await session.get(CalendarTask, task.id)).status == "succeeded"


async def test_future_job_does_not_block_read_chat_or_prematurely_dispatch(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    command = (
        'besok jam 08.00 jalankan pembuatan acara untuk lusa jam 10 judul "Review" durasi 60 menit'
    )
    row = await submit(tg, repo, command)
    await approve(tg, row)
    assert (await scheduler.run_pass()).processed == 0
    read = await submit(tg, repo, "apa jadwalku besok?", 103)
    assert read.tool_name == "calendar_list_events"
    assert (await scheduler.run_pass()).processed == 1
    await repo.heartbeat()
    provider.create_event.assert_not_awaited()
    provider.list_events.assert_awaited_once()
    await tg.ingest([incoming(tg, 104, "Halo")], "TestBot")
    assert await repo.next_request() is not None


async def test_superseding_proposal_changes_fingerprint_and_does_not_inherit_approval(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    task = await draft(tg, repo)
    old = await finish_draft(tg, repo)
    await approve(tg, old)
    new = await submit(tg, repo, f"draft {task.id}: durasi 90 menit", 103)
    assert new.status == "awaiting_approval" and new.id != old.id
    assert new.action_fingerprint != old.action_fingerprint
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, old.id)).status == "cancelled"
    with pytest.raises(ActionJournalError):
        await journal.approve(new.id, old.action_fingerprint)
    assert (await scheduler.run_pass()).processed == 0


@pytest.mark.parametrize("change", ["cancel", "new", "clear", "scope", "pairing"])
async def test_drafts_fail_closed_after_context_scope_or_identity_change(test_db, change):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    task = await draft(tg, repo)
    if change == "scope":
        await set_grant(test_db, repo.owner, "calendar", frozenset({"calendar:read"}), enabled=True)
    elif change == "pairing":
        async with test_db.tenant(repo.owner) as session:
            identity = await session.get(ExternalIdentity, task.identity_id)
            identity.enabled = False
    else:
        await tg.ingest([incoming(tg, 101, "/" + change)], "TestBot")
    await repo.heartbeat()
    async with test_db.tenant(repo.owner) as session:
        saved = await session.get(CalendarTask, task.id)
        assert saved.status == "cancelled"
        if change == "clear":
            assert saved.slots == {} and saved.provenance == {}
    provider.create_event.assert_not_awaited()


async def test_expiry_and_cross_owner_draft_cannot_be_merged(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    task = await draft(tg, repo)
    async with test_db.tenant(repo.owner) as session:
        (await session.get(CalendarTask, task.id)).expires_at = now_utc() - timedelta(seconds=1)
    await repo.heartbeat()
    assert await finish_draft(tg, repo) is None
    async with test_db.tenant(uuid4()) as session:
        assert await session.get(CalendarTask, task.id) is None
        assert (
            await session.get(ToolAction, task.current_action_id) is None
            if task.current_action_id
            else True
        )
    assert (await task_for(repo)).status == "expired"


async def test_concurrent_replayed_final_turn_produces_one_action(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await draft(tg, repo)
    turn = incoming(tg, 101, 'judul "Review"; durasi 60 menit')
    await asyncio.gather(tg.ingest([turn], "TestBot"), tg.ingest([turn], "TestBot"))
    rid = await repo.next_request()
    a, b = await asyncio.gather(repo.route_tool(rid), repo.route_tool(rid))
    assert sorted([a, b]) == [False, True]
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(ToolAction)) == 1


async def test_scheduled_payload_is_immutable_and_stale_window_never_writes(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await draft(tg, repo)
    row = await finish_draft(tg, repo)
    await approve(tg, row)
    with pytest.raises(DBAPIError):
        async with test_db.tenant(repo.owner) as session:
            await session.execute(
                text("UPDATE app.tool_actions SET due_at=due_at+interval '1 hour' WHERE id=:id"),
                {"id": row.id},
            )
    # Clock change simulates downtime without mutating immutable payload.
    import jarvis.tools.journal as clock

    old_clock = clock.now_utc
    clock.now_utc = lambda: row.latest_dispatch_at + timedelta(seconds=1)
    try:
        assert (await scheduler.run_pass()).processed == 0
    finally:
        clock.now_utc = old_clock
    provider.create_event.assert_not_awaited()
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, row.id)).error_code == "execution_window_expired"


async def test_crash_after_provider_accepts_write_recovers_with_get_and_one_post(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await draft(tg, repo)
    row = await finish_draft(tg, repo)
    await approve(tg, row)

    class ProcessCrash(BaseException):
        pass

    async def accepted_then_crashed(args):
        await provider.create_event(
            title=args["title"],
            start=args["start"],
            end=args["end"],
            timezone=args["timezone"],
            request_id="kuro" + row.id.hex,
        )
        raise ProcessCrash()

    broker = ExecutionBroker(
        journal, journal.registry, {"calendar_create_event": accepted_then_crashed}
    )
    claim = await journal.claim()
    with pytest.raises(ProcessCrash):
        await broker.execute_claimed(claim)
    async with test_db.tenant(repo.owner) as session:
        (await session.get(ToolAction, row.id)).lease_until = now_utc() - timedelta(seconds=1)
    await scheduler.run_pass()
    await repo.heartbeat()
    provider.create_event.assert_awaited_once()
    provider.get_event.return_value = {
        "id": "kuro" + row.id.hex,
        "summary": row.arguments["title"],
        "start": {"dateTime": row.arguments["start"]},
        "end": {"dateTime": row.arguments["end"]},
    }
    await reconcile_solo_create(journal, provider, row.id)
    await repo.heartbeat()
    provider.create_event.assert_awaited_once()
    provider.get_event.assert_awaited_once()
    async with test_db.tenant(repo.owner) as session:
        states = set((await session.scalars(select(CalendarNotification.event_key))).all())
        assert states == {f"{row.id}:uncertain", f"{row.id}:succeeded"}


async def test_notification_ambiguous_delivery_is_not_reactivated(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await draft(tg, repo)
    row = await finish_draft(tg, repo)
    await approve(tg, row)
    await scheduler.run_pass()
    await repo.heartbeat()
    async with test_db.tenant(repo.owner) as session:
        # Remove receipt backlog; isolate completion claim.
        await session.execute(text("UPDATE app.telegram_receipts SET delivery_status='sent'"))
        state = await tg.state(session)
        state.send_not_before = None
    delivery = await tg.claim()
    assert delivery.notification_id is not None
    await tg.finish(delivery)  # Unknown send result.
    await repo.heartbeat()
    async with test_db.tenant(repo.owner) as session:
        assert (
            await session.get(CalendarNotification, delivery.notification_id)
        ).delivery_status == "uncertain"
    assert await tg.claim() is None
