import pytest

from jarvis.agents import AgentRegistry
from jarvis.integrations.calendar.agent import calendar_agent_spec, calendar_tool_specs
from jarvis.integrations.calendar.tools import calendar_handlers
from jarvis.tools import (
    AuthorizationContext,
    AuthorizationDecision,
    ToolProposal,
    ToolRegistry,
    ToolRuntime,
)
from jarvis.tools.runtime import ToolRuntimeError


class FakeCalendar:
    def __init__(self):
        self.calls = []

    async def list_events(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [{"id": "evt-1", "summary": "Review"}]

    async def create_event(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"id": "evt-2"}

    async def create_invite(self, **kwargs):
        self.calls.append(("invite", kwargs))
        return {"id": "evt-3"}

    async def update_event(self, **kwargs):
        self.calls.append(("update", kwargs))
        return {"id": kwargs["event_id"]}

    async def delete_event(self, **kwargs):
        self.calls.append(("delete", kwargs))


def runtime():
    registry = ToolRegistry(calendar_tool_specs())
    provider = FakeCalendar()
    return ToolRuntime(registry, calendar_handlers(provider)), provider, registry


def test_calendar_specialist_registers_only_its_closed_tool_set():
    _, _, tools = runtime()
    agents = AgentRegistry(tools)
    spec = calendar_agent_spec()
    agents.register(spec)
    assert agents.get("calendar").tools == frozenset(tools.names())


@pytest.mark.asyncio
async def test_read_is_immediate_without_confirmation():
    rt, provider, _ = runtime()
    proposal = ToolProposal(
        "calendar_list_events",
        {"time_min": "2026-10-03T00:00:00Z", "time_max": "2026-10-04T00:00:00Z"},
    )
    result = rt.authorize(proposal, AuthorizationContext(frozenset({"calendar:read"})))
    assert result.decision == AuthorizationDecision.ALLOW
    events = await rt.execute(proposal, AuthorizationContext(frozenset({"calendar:read"})))
    assert events[0]["id"] == "evt-1"
    assert provider.calls[0][0] == "list"


@pytest.mark.asyncio
async def test_explicit_solo_create_does_not_double_confirm():
    rt, provider, _ = runtime()
    args = {
        "title": "Focus",
        "start": "2026-10-03T10:00:00+07:00",
        "end": "2026-10-03T11:00:00+07:00",
        "timezone": "Asia/Jakarta",
    }
    proposal = ToolProposal("calendar_create_event", args)
    context = AuthorizationContext(frozenset({"calendar:write"}), explicit_user_instruction=True)
    assert rt.authorize(proposal, context).decision == AuthorizationDecision.ALLOW
    with pytest.raises(ToolRuntimeError, match="durable_journal_required"):
        await rt.execute(proposal, context)
    assert provider.calls == []


def test_invite_requires_approval_even_when_explicit():
    rt, _, _ = runtime()
    args = {
        "title": "Review",
        "start": "s",
        "end": "e",
        "timezone": "Asia/Jakarta",
        "attendees": ["a@example.com"],
    }
    proposal = ToolProposal("calendar_create_invite", args)
    context = AuthorizationContext(
        frozenset({"calendar:write", "calendar:send"}), explicit_user_instruction=True
    )
    assert rt.authorize(proposal, context).decision == AuthorizationDecision.REQUIRE_APPROVAL


def test_delete_requires_approval_even_when_explicit():
    rt, _, _ = runtime()
    proposal = ToolProposal("calendar_delete_event", {"event_id": "evt-1"})
    context = AuthorizationContext(frozenset({"calendar:write"}), explicit_user_instruction=True)
    assert rt.authorize(proposal, context).decision == AuthorizationDecision.REQUIRE_APPROVAL


def test_low_risk_create_cannot_smuggle_attendees():
    rt, _, _ = runtime()
    proposal = ToolProposal(
        "calendar_create_event",
        {
            "title": "Review",
            "start": "s",
            "end": "e",
            "timezone": "Asia/Jakarta",
            "attendees": ["a@example.com"],
        },
    )
    context = AuthorizationContext(frozenset({"calendar:write"}), explicit_user_instruction=True)
    result = rt.authorize(proposal, context)
    assert result.decision == AuthorizationDecision.DENY
    assert result.reason == "invalid_arguments"
