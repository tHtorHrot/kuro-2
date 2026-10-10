"""Real PostgreSQL handoff/recovery; provider calls are deliberately mocked."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from test_assistant import fixture
from test_telegram import incoming, receipt

from jarvis.assistant.graph import AssistantWorkflow
from jarvis.integrations.calendar.agent import calendar_tool_specs
from jarvis.integrations.calendar.recovery import reconcile_solo_create
from jarvis.integrations.calendar.tools import calendar_handlers
from jarvis.storage.models import AssistantRequest, LLMCall, ToolAction, User
from jarvis.tools.authority import set_grant
from jarvis.tools.contracts import AuthorizationContext, ToolProposal
from jarvis.tools.execution import ExecutionBroker
from jarvis.tools.journal import ActionJournal, ActionJournalError, now_utc
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.scheduler import ActionScheduler

pytestmark = pytest.mark.integration
CREATE = 'buat rapat "Review" pada 2026-10-05 jam 10:00 sampai 11:00 zona Asia/Jakarta'
SCOPES = frozenset({"calendar:read", "calendar:write", "calendar:send"})


async def setup(db):
    tg, repo = await fixture(db)
    await set_grant(db, repo.owner, "calendar", SCOPES, enabled=True)
    registry = ToolRegistry(calendar_tool_specs())
    journal = ActionJournal(db, repo.owner, registry)
    provider = AsyncMock()
    provider.create_event.return_value = {"id": "provider-event"}
    provider.create_invite.return_value = {"id": "provider-invite"}
    provider.list_events.return_value = [{"id": "read-event", "summary": "Review"}]
    provider.delete_event.return_value = None
    broker = ExecutionBroker(journal, registry, calendar_handlers(provider))
    return tg, repo, journal, provider, ActionScheduler(journal, broker)


async def submit(tg, repo, message=CREATE, number=100):
    await tg.ingest([incoming(tg, number, message)], "TestBot")
    request_id = await repo.next_request()
    assert request_id is not None
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(request_id)
    router.plan.assert_not_awaited()
    router.complete.assert_not_awaited()
    async with repo.db.tenant(repo.owner) as session:
        return await session.scalar(select(ToolAction).where(ToolAction.request_id == request_id))


async def test_calendar_chat_to_result_outbox_without_llm_or_duplicate_write(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    row = await submit(tg, repo)
    assert row.status == "queued"
    assert (await receipt(tg)).delivery_status == "waiting"
    result = await scheduler.run_pass()
    assert result.results[0].outcome == "succeeded"
    await repo.heartbeat()
    assert "provider-event" in (await receipt(tg)).reply_text
    assert provider.create_event.call_args.kwargs["request_id"] == "kuro" + row.id.hex
    await tg.ingest([incoming(tg, 100, CREATE)], "TestBot")
    assert (await scheduler.run_pass()).processed == 0
    await repo.heartbeat()
    provider.create_event.assert_awaited_once()
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, row.id)).result == {"id": "provider-event"}
        assert await session.scalar(select(func.count()).select_from(LLMCall)) == 0


@pytest.mark.parametrize("change", ["revoke", "suspend", "cancel", "clear"])
async def test_revocation_and_cancellation_prevent_queued_http_write(test_db, change):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    await submit(tg, repo)
    if change == "revoke":
        await set_grant(test_db, repo.owner, "calendar", frozenset(), enabled=False)
    elif change == "suspend":
        async with test_db.tenant(repo.owner) as session:
            (await session.get(User, repo.owner)).status = "suspended"
    else:
        await tg.ingest([incoming(tg, 101, "/" + change)], "TestBot")
    await scheduler.run_pass()
    provider.create_event.assert_not_awaited()


async def test_invite_approval_is_separate_exact_once_and_replayed_update_is_safe(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    row = await submit(tg, repo, CREATE + " undang a@example.com")
    assert row.status == "awaiting_approval"
    assert "a@example.com" in (await receipt(tg)).reply_text
    assert (await scheduler.run_pass()).processed == 0
    await tg.ingest([incoming(tg, 101, "/approve wrong-premium-code")], "TestBot")
    assert await journal.claim() is None
    approved = incoming(tg, 102, f"/toolapprove {row.id} {row.action_fingerprint}")
    await asyncio.gather(tg.ingest([approved], "TestBot"), tg.ingest([approved], "TestBot"))
    assert (await scheduler.run_pass()).results[0].outcome == "succeeded"
    await repo.heartbeat()
    assert "provider-invite" in (await receipt(tg, 102)).reply_text
    provider.create_invite.assert_awaited_once()


async def test_source_step_dedup_is_concurrent_and_changed_arguments_are_rejected(test_db):
    _, repo, journal, _, _ = await setup(test_db)
    p = ToolProposal("calendar_delete_event", {"event_id": "evt1"})
    context = AuthorizationContext(SCOPES)
    a, b = await asyncio.gather(
        *(journal.create(p, context, source_key="source:1:step:1") for _ in range(2))
    )
    assert a.id == b.id
    with pytest.raises(ActionJournalError, match="source_action_conflict"):
        await journal.create(
            ToolProposal("calendar_delete_event", {"event_id": "evt2"}),
            context,
            source_key="source:1:step:1",
        )


async def test_dispatch_crash_becomes_uncertain_and_never_recreates_event(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    row = await submit(tg, repo)
    claim = await journal.claim()
    assert await journal.begin_dispatch(claim) is None
    async with test_db.tenant(repo.owner) as session:
        (await session.get(ToolAction, row.id)).lease_until = now_utc() - timedelta(seconds=1)
    await scheduler.run_pass()
    await repo.heartbeat()
    assert "belum dapat dipastikan" in (await receipt(tg)).reply_text
    provider.create_event.assert_not_awaited()


async def test_read_uses_owner_timezone_and_same_durable_result_path(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    row = await submit(tg, repo, "apa jadwalku besok?")
    assert row.tool_name == "calendar_list_events"
    assert row.arguments["time_min"].endswith("+07:00")
    await scheduler.run_pass()
    await repo.heartbeat()
    reply = (await receipt(tg)).reply_text
    assert "Review" in reply and "(WIB)" in reply
    assert "read-event" not in reply
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, row.id)).result[0]["id"] == "read-event"
    provider.list_events.assert_awaited_once()


async def test_incomplete_create_requests_details_without_action_or_llm(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    assert await submit(tg, repo, "buat rapat besok jam 10") is None
    assert "durasi/jam selesai" in (await receipt(tg)).reply_text
    assert (await scheduler.run_pass()).processed == 0
    async with test_db.tenant(repo.owner) as session:
        assert (await session.scalar(select(AssistantRequest))).status == "clarified"


async def test_regrant_does_not_revive_an_older_approval(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    row = await submit(tg, repo, CREATE + " undang a@example.com")
    await set_grant(test_db, repo.owner, "calendar", frozenset(), enabled=False)
    await set_grant(test_db, repo.owner, "calendar", SCOPES, enabled=True)
    with pytest.raises(ActionJournalError, match="authorization_changed"):
        await journal.approve(row.id, row.action_fingerprint)
    assert (await scheduler.run_pass()).processed == 0


async def test_reconciliation_reads_the_stable_id_without_repeating_post(test_db):
    tg, repo, journal, provider, scheduler = await setup(test_db)
    row = await submit(tg, repo)
    claim = await journal.claim()
    await journal.begin_dispatch(claim)
    await journal.finish(claim, outcome="uncertain")
    provider.get_event.return_value = {
        "id": "kuro" + row.id.hex,
        "summary": "Review",
        "start": {"dateTime": row.arguments["start"]},
        "end": {"dateTime": row.arguments["end"]},
    }
    result = await reconcile_solo_create(journal, provider, row.id)
    assert result["status"] == "succeeded" and not result["provider_write_repeated"]
    provider.get_event.assert_awaited_once_with(event_id="kuro" + row.id.hex)
    provider.create_event.assert_not_awaited()
    await repo.heartbeat()
    assert "kuro" + row.id.hex in (await receipt(tg)).reply_text


async def test_proposal_is_readable_and_prefix_cancel_works(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow
    from jarvis.orchestration.calendar_chat import (
        approval_text,
        resolve_action,
        short_id,
    )

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await tg.ingest([incoming(tg, 100, "buat rapat besok jam 10")], "TestBot")
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 101, 'judul "Review"; durasi 60 menit')], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    assert "usulan 1 dari 1 menunggu" in (await receipt(tg, 101)).reply_text
    async with test_db.tenant(repo.owner) as session:
        row = await session.scalar(
            select(ToolAction).where(ToolAction.status == "awaiting_approval")
        )
    text = approval_text(row)
    assert "10.00–11.00 (WIB)" in text
    assert f"Ref: {short_id(row.id)}" in text
    assert f"/toolapprove {row.id} {row.action_fingerprint}" in text
    async with test_db.tenant(repo.owner) as session:
        assert (await resolve_action(session, repo.owner, short_id(row.id))).id == row.id
        assert await resolve_action(session, repo.owner, "babecafe") is None
    await tg.ingest([incoming(tg, 102, f"/cancel {short_id(row.id)}")], "TestBot")
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, row.id)).status == "cancelled"


def tap(tg, number, action_id, kind="approve", query_id="cb-1"):
    from datetime import UTC, datetime

    sender = tg.config.sender_id
    return {
        "update_id": number,
        "callback_query": {
            "id": query_id,
            "from": {"id": sender, "is_bot": False},
            "message": {
                "message_id": 60,
                "date": int(datetime.now(UTC).timestamp()),
                "text": "proposal",
                "chat": {"id": sender, "type": "private"},
            },
            "data": f"{kind}:{action_id}",
        },
    }


async def test_inline_button_tap_approves_exact_action_once(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await tg.ingest([incoming(tg, 100, "buat rapat besok jam 10")], "TestBot")
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 101, 'judul "Review"; durasi 60 menit')], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    async with test_db.tenant(repo.owner) as session:
        row = await session.scalar(
            select(ToolAction).where(ToolAction.status == "awaiting_approval")
        )
    await tg.ingest([tap(tg, 102, row.id)], "TestBot")
    answers = tg.take_callback_outbox()
    assert [a["answer"] for a in answers] == ["Disetujui ✓"]
    assert answers[0]["callback_id"] == "cb-1" and answers[0]["message_id"] == 60
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, row.id)).status == "queued"
    await tg.ingest([tap(tg, 103, row.id, query_id="cb-2")], "TestBot")
    assert [a["answer"] for a in tg.take_callback_outbox()] == [
        "Sudah diputuskan / kedaluwarsa / izin berubah."
    ]


async def test_inline_button_tap_cancels_before_dispatch(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await tg.ingest([incoming(tg, 100, "buat rapat besok jam 10")], "TestBot")
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 101, 'judul "Review"; durasi 60 menit')], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    async with test_db.tenant(repo.owner) as session:
        row = await session.scalar(
            select(ToolAction).where(ToolAction.status == "awaiting_approval")
        )
    await tg.ingest([tap(tg, 102, row.id, kind="cancel")], "TestBot")
    assert [a["answer"] for a in tg.take_callback_outbox()] == ["Dibatalkan."]
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(ToolAction, row.id)).status == "cancelled"


async def _two_pendings(tg, repo):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    router = AsyncMock()
    await tg.ingest([incoming(tg, 100, "buat rapat besok jam 10")], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 101, 'judul "Pagi"; durasi 60 menit')], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 102, "buat rapat besok jam 12")], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 103, 'judul "Siang"; durasi 60 menit')], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())


async def test_bare_ya_lists_when_several_wait(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await _two_pendings(tg, repo)
    await tg.ingest([incoming(tg, 104, "ya")], "TestBot")
    await AssistantWorkflow(repo, AsyncMock(), AsyncMock()).invoke(await repo.next_request())
    text = (await receipt(tg, 104)).reply_text
    assert "2 usulan menunggu" in text and "setujui nomor 1" in text
    async with test_db.tenant(repo.owner) as session:
        rows = (
            await session.scalars(
                select(ToolAction).where(ToolAction.status == "awaiting_approval")
            )
        ).all()
    assert len(rows) == 2


async def test_setujui_nomor_approves_that_queue_entry(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await _two_pendings(tg, repo)
    await tg.ingest([incoming(tg, 104, "setujui nomor 2")], "TestBot")
    await AssistantWorkflow(repo, AsyncMock(), AsyncMock()).invoke(await repo.next_request())
    text = (await receipt(tg, 104)).reply_text
    assert "Menyetujui usulan 2" in text
    async with test_db.tenant(repo.owner) as session:
        rows = (
            await session.scalars(
                select(ToolAction).where(ToolAction.status == "awaiting_approval")
            )
        ).all()
        queued = (
            await session.scalars(select(ToolAction).where(ToolAction.status == "queued"))
        ).all()
    assert len(rows) == 1 and len(queued) == 1


async def test_single_ya_approves_and_batal_cancels(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await tg.ingest([incoming(tg, 100, "buat rapat besok jam 10")], "TestBot")
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 101, 'judul "Pagi"; durasi 60 menit')], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    await tg.ingest([incoming(tg, 102, "ya")], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    assert "Menyetujui usulan 1" in (await receipt(tg, 102)).reply_text
    async with test_db.tenant(repo.owner) as session:
        assert not (
            await session.scalars(
                select(ToolAction).where(ToolAction.status == "awaiting_approval")
            )
        ).all()


async def test_compound_approves_then_cancels_in_order(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await _two_pendings(tg, repo)
    router = AsyncMock()
    await tg.ingest([incoming(tg, 104, "setujui nomor 2 dan batalkan nomor 1")], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    text = (await receipt(tg, 104)).reply_text
    assert "Menyetujui usulan 2" in text and "dibatalkan" in text
    async with test_db.tenant(repo.owner) as session:
        assert not (
            await session.scalars(
                select(ToolAction).where(ToolAction.status == "awaiting_approval")
            )
        ).all()


async def test_compound_with_vague_clause_executes_nothing(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await _two_pendings(tg, repo)
    await tg.ingest([incoming(tg, 104, "setujui nomor 5 dan batalkan nomor 1")], "TestBot")
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    assert "Nomor 1–2 saja" in (await receipt(tg, 104)).reply_text
    async with test_db.tenant(repo.owner) as session:
        rows = (
            await session.scalars(
                select(ToolAction).where(ToolAction.status == "awaiting_approval")
            )
        ).all()
    assert len(rows) == 2


async def test_salvage_reports_known_missing_and_ignored(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await tg.ingest(
        [incoming(tg, 100, "buat rapat jijik besok sore jam 3 durasi 20 menit")], "TestBot"
    )
    router = AsyncMock()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    router.plan.assert_not_awaited()
    router.complete.assert_not_awaited()
    text = (await receipt(tg, 100)).reply_text
    assert "Diketahui:" in text and "judul" in text
    assert "Abaikan: 'jijik'" in text


async def test_bulk_cancel_all_reports_each_and_approve_all_refuses(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo, journal, provider, scheduler = await setup(test_db)
    await _two_pendings(tg, repo)
    router = AsyncMock()
    await tg.ingest([incoming(tg, 104, "setujui semuanya")], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    assert "Setujui massal ditolak" in (await receipt(tg, 104)).reply_text
    await tg.ingest([incoming(tg, 105, "batalin semua")], "TestBot")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    assert (await receipt(tg, 105)).reply_text.count("dibatalkan") == 2
    async with test_db.tenant(repo.owner) as session:
        assert not (
            await session.scalars(
                select(ToolAction).where(ToolAction.status == "awaiting_approval")
            )
        ).all()
