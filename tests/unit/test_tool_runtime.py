from unittest.mock import AsyncMock

import pytest

from jarvis.tools import (
    AuthorizationContext,
    ToolEffect,
    ToolProposal,
    ToolRegistry,
    ToolRuntime,
    ToolRuntimeError,
    ToolSpec,
)


def runtime(handler=None):
    spec = ToolSpec(
        "calendar_move",
        "Move event",
        "calendar",
        frozenset({"calendar:write"}),
        ToolEffect.REVERSIBLE_WRITE,
        argument_keys=frozenset({"event_id", "start"}),
    )
    registry = ToolRegistry([spec])
    handler = handler or AsyncMock(return_value={"ok": True})
    return ToolRuntime(registry, {"calendar_move": handler}), handler


async def test_runtime_requires_durable_journal_even_for_explicit_write():
    rt, handler = runtime()
    proposal = ToolProposal("calendar_move", {"event_id": "e1", "start": "10:00"})
    context = AuthorizationContext(frozenset({"calendar:write"}), explicit_user_instruction=True)
    with pytest.raises(ToolRuntimeError, match="durable_journal_required"):
        await rt.execute(proposal, context)
    handler.assert_not_awaited()


async def test_runtime_never_executes_unapproved_or_malformed_proposal():
    rt, handler = runtime()
    proposal = ToolProposal("calendar_move", {"event_id": "e1", "start": "10:00"})
    context = AuthorizationContext(frozenset({"calendar:write"}))
    with pytest.raises(ToolRuntimeError, match="write_not_authorized"):
        await rt.execute(proposal, context)
    malformed = ToolProposal("calendar_move", {"event_id": "e1"})
    explicit = AuthorizationContext(frozenset({"calendar:write"}), explicit_user_instruction=True)
    with pytest.raises(ToolRuntimeError, match="invalid_arguments"):
        await rt.execute(malformed, explicit)
    handler.assert_not_awaited()
