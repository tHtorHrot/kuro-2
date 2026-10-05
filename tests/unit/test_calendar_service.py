from types import SimpleNamespace
from uuid import uuid4

import pytest

from jarvis.integrations.calendar.service import CalendarService


class Runtime:
    async def execute(self, proposal, context):
        assert proposal.tool_name == "calendar_list_events"
        return [{"id": "evt-1"}]


class Journal:
    def __init__(self, status):
        self.status = status

    async def create(self, proposal, context, **kwargs):
        return SimpleNamespace(id=uuid4(), status=self.status, action_fingerprint="f" * 64)


def service(status="queued"):
    activation = SimpleNamespace(runtime=Runtime(), journal=Journal(status))
    return CalendarService(
        activation, frozenset({"calendar:read", "calendar:write", "calendar:send"})
    )


@pytest.mark.asyncio
async def test_read_is_queued_for_the_credential_owning_worker():
    result = await service().list_events(time_min="a", time_max="b")
    assert result.kind == "queued" and set(result.value) == {"action_id", "fingerprint"}


@pytest.mark.asyncio
async def test_write_returns_durable_action_reference_not_provider_result():
    result = await service().submit_write(
        "calendar_create_event", {"x": 1}, explicit_user_instruction=True
    )
    assert result.kind == "queued"
    assert set(result.value) == {"action_id", "fingerprint"}


@pytest.mark.asyncio
async def test_sensitive_write_surfaces_approval_required():
    result = await service("awaiting_approval").submit_write(
        "calendar_create_invite", {"x": 1}, explicit_user_instruction=True
    )
    assert result.kind == "approval_required"
