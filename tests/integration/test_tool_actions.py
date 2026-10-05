"""Stage 4 durable action journal: PostgreSQL state, RLS, approval binding and recovery."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from test_assistant import fixture

from jarvis.assistant.repository import now_utc
from jarvis.storage.models import AuditEvent, ToolAction
from jarvis.tools import (
    ActionJournal,
    ActionJournalError,
    AuthorizationContext,
    ToolEffect,
    ToolProposal,
    ToolRegistry,
    ToolSpec,
)
from jarvis.tools.authority import set_grant

pytestmark = pytest.mark.integration


def registry():
    return ToolRegistry(
        [
            ToolSpec(
                "calendar_read",
                "Read calendar",
                "calendar",
                frozenset({"calendar:read"}),
                ToolEffect.READ,
                argument_keys=frozenset({"date"}),
            ),
            ToolSpec(
                "email_send",
                "Send email",
                "email",
                frozenset({"email:send"}),
                ToolEffect.EXTERNAL_SEND,
                argument_keys=frozenset({"to", "body"}),
            ),
        ]
    )


async def setup(test_db):
    _, assistant = await fixture(test_db)
    await set_grant(
        test_db, assistant.owner, "calendar", frozenset({"calendar:read"}), enabled=True
    )
    await set_grant(test_db, assistant.owner, "email", frozenset({"email:send"}), enabled=True)
    return assistant, ActionJournal(test_db, assistant.owner, registry())


async def test_read_action_queues_without_approval_and_future_action_waits(test_db):
    assistant, journal = await setup(test_db)
    future = await journal.create(
        ToolProposal("calendar_read", {"date": "tomorrow"}),
        AuthorizationContext(frozenset({"calendar:read"})),
        due_at=now_utc() + timedelta(hours=1),
    )
    assert future.status == "queued"
    assert await journal.claim() is None
    async with test_db.tenant(assistant.owner) as session:
        stored = await session.get(ToolAction, future.id)
        assert stored.status == "queued" and stored.attempts == 0


async def test_sensitive_action_approval_is_bound_to_exact_payload(test_db):
    assistant, journal = await setup(test_db)
    row = await journal.create(
        ToolProposal("email_send", {"to": "a@example.test", "body": "hello"}),
        AuthorizationContext(frozenset({"email:send"}), explicit_user_instruction=True),
    )
    assert row.status == "awaiting_approval"
    with pytest.raises(ActionJournalError, match="approval_action_mismatch"):
        await journal.approve(row.id, "0" * 64)
    await journal.approve(row.id, row.action_fingerprint)
    claimed = await journal.claim()
    assert claimed and claimed.id == row.id and claimed.attempt == 1
    await journal.begin_dispatch(claimed)
    await journal.finish(claimed, outcome="succeeded")
    async with test_db.tenant(assistant.owner) as session:
        stored = await session.get(ToolAction, row.id)
        assert stored.status == "succeeded" and stored.approved_at is not None
        events = (
            await session.scalars(select(AuditEvent).where(AuditEvent.resource_id == row.id))
        ).all()
        assert {event.action for event in events} >= {
            "tool_action.created",
            "tool_action.approved",
            "tool_action.dispatching",
            "tool_action.succeeded",
        }
        assert all(event.metadata_safe == {} for event in events)


async def test_expired_claim_requeues_but_expired_dispatch_becomes_uncertain(test_db):
    assistant, journal = await setup(test_db)
    context = AuthorizationContext(frozenset({"calendar:read"}))
    first = await journal.create(ToolProposal("calendar_read", {"date": "one"}), context)
    claim = await journal.claim()
    assert claim and claim.id == first.id
    async with test_db.tenant(assistant.owner) as session:
        (await session.get(ToolAction, first.id)).lease_until = now_utc() - timedelta(seconds=1)
    assert await journal.recover_expired() == 1
    second_claim = await journal.claim()
    assert second_claim and second_claim.id == first.id and second_claim.attempt == 2
    await journal.begin_dispatch(second_claim)
    async with test_db.tenant(assistant.owner) as session:
        (await session.get(ToolAction, first.id)).lease_until = now_utc() - timedelta(seconds=1)
    assert await journal.recover_expired() == 1
    async with test_db.tenant(assistant.owner) as session:
        assert (await session.get(ToolAction, first.id)).status == "uncertain"
    assert await journal.claim() is None


async def test_stale_lease_cannot_dispatch_or_finish(test_db):
    assistant, journal = await setup(test_db)
    row = await journal.create(
        ToolProposal("calendar_read", {"date": "today"}),
        AuthorizationContext(frozenset({"calendar:read"})),
    )
    claim = await journal.claim()
    async with test_db.tenant(assistant.owner) as session:
        (await session.get(ToolAction, row.id)).lease_until = now_utc() - timedelta(seconds=1)
    with pytest.raises(ActionJournalError, match="stale_action_lease"):
        await journal.begin_dispatch(claim)


async def test_action_payload_is_database_immutable_and_owner_isolated(test_db):
    first, journal = await setup(test_db)
    row = await journal.create(
        ToolProposal("calendar_read", {"date": "today"}),
        AuthorizationContext(frozenset({"calendar:read"})),
    )
    with pytest.raises(DBAPIError):
        async with test_db.tenant(first.owner) as session:
            await session.execute(
                update(ToolAction)
                .where(ToolAction.id == row.id)
                .values(arguments={"date": "tomorrow"})
            )
    second, _ = await setup(test_db)
    async with test_db.tenant(second.owner) as session:
        assert await session.get(ToolAction, row.id) is None
