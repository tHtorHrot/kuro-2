import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from jarvis.integrations.calendar.config import calendar_binding
from jarvis.integrations.calendar.google import GoogleCalendarProvider
from jarvis.integrations.calendar.provider import CalendarProviderError
from jarvis.integrations.calendar.validation import validate_arguments
from jarvis.orchestration.calendar_chat import propose
from jarvis.orchestration.trusted_intent import IntentKind
from jarvis.tools.execution import ExecutionResult
from jarvis.tools.journal import ActionJournalError
from jarvis.tools.scheduler import ActionScheduler

ARGS = {
    "title": "Review",
    "start": "2026-10-05T10:00:00+07:00",
    "end": "2026-10-05T11:00:00+07:00",
    "timezone": "Asia/Jakarta",
}


@pytest.mark.parametrize(
    "change",
    [
        {"title": 1},
        {"title": ""},
        {"title": "a" * 201},
        {"title": "private\ntext"},
        {"start": "tomorrow"},
        {"start": "2026-10-05T10:00:00"},
        {"start": "2026-10-05T10:00:00Z"},
        {"end": "2026-10-05T09:00:00+07:00"},
        {"end": "2026-11-05T10:00:00+07:00"},
        {"timezone": "Mars/Olympus"},
        {"attendees": ["unsolicited@example.com"]},
    ],
)
def test_calendar_rejects_bad_values_before_provider(change):
    with pytest.raises(ValueError):
        validate_arguments("calendar_create_event", {**ARGS, **change})


@pytest.mark.parametrize(
    "attendees",
    [
        [],
        "a@example.com",
        ["name"],
        ["a@example.com\nbcc:x@y.com"],
        ["a@example.com", "A@example.com"],
        ["a@example.com"] * 21,
    ],
)
def test_invite_rejects_malformed_ambiguous_or_unbounded_recipients(attendees):
    with pytest.raises(ValueError):
        validate_arguments("calendar_create_invite", {**ARGS, "attendees": attendees})


@pytest.mark.parametrize(
    "source",
    [
        'jangan buat rapat "X"',
        'bagaimana cara buat rapat "X"?',
        'katanya buat rapat "X"',
        '"buat rapat X"',
    ],
)
def test_non_instruction_is_not_a_calendar_write(source):
    assert propose(source, timezone="Asia/Jakarta", received_at=datetime.now(UTC)) is None


def test_relative_read_uses_original_received_time_and_owner_timezone():
    intent = propose(
        "apa jadwalku besok?",
        timezone="Asia/Jakarta",
        received_at=datetime(2026, 10, 3, 19, tzinfo=UTC),
    )
    assert intent.kind == IntentKind.CALENDAR_LIST
    assert intent.arguments == {
        "time_min": "2026-10-05T00:00:00+07:00",
        "time_max": "2026-10-06T00:00:00+07:00",
    }


def test_binding_changes_on_credential_account_or_calendar_change():
    first = calendar_binding(SecretStr("client"), SecretStr("secret-refresh"), "primary")
    assert len(first) == 64 and "secret" not in first
    assert first != calendar_binding(SecretStr("client"), SecretStr("other-refresh"), "primary")
    assert first != calendar_binding(SecretStr("client"), SecretStr("secret-refresh"), "other")


async def token():
    return "test-token"


async def test_provider_paginates_and_keeps_only_bounded_event_fields():
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "items": [{"id": "first", "description": "ignore"}],
                    "nextPageToken": "page2",
                },
            )
        assert request.url.params["pageToken"] == "page2"
        return httpx.Response(200, json={"items": [{"id": "second"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await GoogleCalendarProvider(token, client=client).list_events(
            time_min="a", time_max="b"
        )
    assert result == [{"id": "first"}, {"id": "second"}]
    assert len(calls) == 2


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"items": [{"id": "x"}] * 101}, "calendar_result_limit"),
        ({"items": [None]}, "calendar_invalid_event"),
        ({"items": [{"id": "x", "summary": 44}]}, "calendar_invalid_event"),
        ({"items": [], "nextPageToken": 9}, "calendar_invalid_pagination"),
        ({"items": [], "nextPageToken": "same"}, "calendar_invalid_pagination"),
    ],
)
async def test_provider_rejects_truncated_or_invalid_lists(payload, code):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(CalendarProviderError, match=code):
            await GoogleCalendarProvider(token, client=client).list_events(
                time_min="a", time_max="b"
            )


async def test_oversize_response_is_rejected_without_exposing_body():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"SECRET" * 50000))
    ) as client:
        with pytest.raises(CalendarProviderError) as error:
            await GoogleCalendarProvider(token, client=client).list_events(
                time_min="a", time_max="b"
            )
        assert str(error.value) == "calendar_response_too_large"


async def test_create_uses_stable_event_id_from_durable_action():
    event_id = "kuro" + uuid4().hex

    def respond(request):
        data = json.loads(request.content)
        assert data["id"] == event_id
        assert "attendees" not in data
        return httpx.Response(200, json={"id": event_id})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert (
            await GoogleCalendarProvider(token, client=client).create_event(
                **ARGS, request_id=event_id
            )
        )["id"] == event_id


async def test_scheduler_continues_after_a_fenced_claim():
    journal, broker = AsyncMock(), AsyncMock()
    from types import SimpleNamespace

    a, b = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    journal.claim.side_effect = [a, b, None]
    journal.recover_expired.return_value = 0
    broker.execute_claimed.side_effect = [
        ActionJournalError("stale_action_lease"),
        ExecutionResult(b.id, "succeeded", "ok"),
    ]
    result = await ActionScheduler(journal, broker).run_pass()
    assert [r.outcome for r in result.results] == ["fenced", "succeeded"]


async def test_scheduler_shutdown_stops_before_claiming_more_work():
    journal, broker = AsyncMock(), AsyncMock()
    journal.recover_expired.return_value = 0
    result = await ActionScheduler(journal, broker).run_pass(stop=AsyncMock(return_value=True))
    assert result.processed == 0
    journal.claim.assert_not_awaited()


async def test_provider_cannot_confirm_an_unrelated_event_id():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"id": "unrelated"}))
    ) as client:
        with pytest.raises(CalendarProviderError, match="calendar_event_identity_mismatch"):
            await GoogleCalendarProvider(token, client=client).create_event(
                **ARGS, request_id="kuro" + uuid4().hex
            )


async def test_raw_approval_flag_cannot_replace_durable_approval():
    from jarvis.integrations.calendar.agent import calendar_tool_specs
    from jarvis.tools.contracts import AuthorizationContext, ToolProposal
    from jarvis.tools.journal import ActionJournal
    from jarvis.tools.registry import ToolRegistry

    journal = ActionJournal(None, uuid4(), ToolRegistry(calendar_tool_specs()))
    with pytest.raises(ActionJournalError, match="approval_requires_journal"):
        await journal.create(
            ToolProposal("calendar_delete_event", {"event_id": "evt"}),
            AuthorizationContext(frozenset({"calendar:write"}), approval_granted=True),
        )
