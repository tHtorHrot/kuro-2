from unittest.mock import AsyncMock
from uuid import uuid4

from jarvis.tools import ToolEffect, ToolRegistry, ToolSpec
from jarvis.tools.execution import ExecutionBroker
from jarvis.tools.journal import ClaimedAction


def spec(effect=ToolEffect.REVERSIBLE_WRITE):
    return ToolSpec(
        "calendar_move",
        "Move event",
        "calendar",
        frozenset({"calendar:write"}),
        effect,
        argument_keys=frozenset({"event_id", "start"}),
    )


def claimed(*, effect="reversible_write"):
    return ClaimedAction(
        uuid4(),
        "calendar",
        "calendar_move",
        effect,
        {"event_id": "e1", "start": "10:00"},
        "fingerprint",
        uuid4(),
        1,
    )


async def test_broker_executes_only_after_dispatch_boundary(monkeypatch):
    journal = AsyncMock()
    journal.owner = uuid4()
    journal.begin_dispatch.return_value = None
    handler = AsyncMock(return_value={"ok": True})
    broker = ExecutionBroker(journal, ToolRegistry([spec()]), {"calendar_move": handler})
    monkeypatch.setattr("jarvis.tools.execution.action_fingerprint", lambda *_: "fingerprint")
    item = claimed()
    result = await broker.execute_claimed(item)
    journal.begin_dispatch.assert_awaited_once_with(item)
    handler.assert_awaited_once_with(item.arguments)
    journal.finish.assert_awaited_once_with(item, outcome="succeeded", result={"ok": True})
    assert result.outcome == "succeeded"


async def test_broker_fails_closed_when_registry_definition_changed(monkeypatch):
    journal = AsyncMock()
    journal.owner = uuid4()
    handler = AsyncMock()
    broker = ExecutionBroker(
        journal, ToolRegistry([spec(ToolEffect.HIGH_IMPACT)]), {"calendar_move": handler}
    )
    monkeypatch.setattr("jarvis.tools.execution.action_fingerprint", lambda *_: "fingerprint")
    item = claimed()
    result = await broker.execute_claimed(item)
    journal.reject_claim.assert_awaited_once_with(item, "tool_definition_changed")
    journal.begin_dispatch.assert_not_awaited()
    handler.assert_not_awaited()
    assert result.outcome == "failed"


async def test_broker_missing_handler_fails_before_dispatch(monkeypatch):
    journal = AsyncMock()
    journal.owner = uuid4()
    broker = ExecutionBroker(journal, ToolRegistry([spec()]), {})
    monkeypatch.setattr("jarvis.tools.execution.action_fingerprint", lambda *_: "fingerprint")
    item = claimed()
    result = await broker.execute_claimed(item)
    journal.reject_claim.assert_awaited_once_with(item, "handler_unavailable")
    journal.begin_dispatch.assert_not_awaited()
    assert result.code == "handler_unavailable"


async def test_broker_ambiguous_handler_failure_is_uncertain(monkeypatch):
    journal = AsyncMock()
    journal.owner = uuid4()
    journal.begin_dispatch.return_value = None
    handler = AsyncMock(side_effect=RuntimeError("provider secret detail"))
    broker = ExecutionBroker(journal, ToolRegistry([spec()]), {"calendar_move": handler})
    monkeypatch.setattr("jarvis.tools.execution.action_fingerprint", lambda *_: "fingerprint")
    item = claimed()
    result = await broker.execute_claimed(item)
    journal.finish.assert_awaited_once_with(item, outcome="uncertain")
    assert result.code == "tool_execution_uncertain"
    assert "provider" not in result.code
