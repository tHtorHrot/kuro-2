"""Deterministic calendar handlers used by ToolRuntime/ExecutionBroker."""

from collections.abc import Mapping
from typing import Any

from jarvis.integrations.calendar.provider import CalendarProvider
from jarvis.integrations.calendar.validation import validate_arguments
from jarvis.tools.execution import DISPATCH_ACTION_ID


def provider_request_id():
    action_id = DISPATCH_ACTION_ID.get()
    return {"request_id": "kuro" + action_id.hex} if action_id else {}


def calendar_handlers(provider: CalendarProvider):
    async def list_events(args: Mapping[str, Any]):
        validate_arguments("calendar_list_events", args)
        return await provider.list_events(
            time_min=str(args["time_min"]), time_max=str(args["time_max"])
        )

    async def create_event(args: Mapping[str, Any]):
        validate_arguments("calendar_create_event", args)
        return await provider.create_event(
            title=str(args["title"]),
            start=str(args["start"]),
            end=str(args["end"]),
            timezone=str(args["timezone"]),
            **provider_request_id(),
        )

    async def create_invite(args: Mapping[str, Any]):
        validate_arguments("calendar_create_invite", args)
        attendees = args["attendees"]
        if (
            not isinstance(attendees, list)
            or not attendees
            or not all(isinstance(x, str) and x for x in attendees)
        ):
            raise ValueError("invalid_attendees")
        return await provider.create_invite(
            title=str(args["title"]),
            start=str(args["start"]),
            end=str(args["end"]),
            timezone=str(args["timezone"]),
            attendees=list(attendees),
            **provider_request_id(),
        )

    async def update_event(args: Mapping[str, Any]):
        validate_arguments("calendar_update_event", args)
        return await provider.update_event(
            event_id=str(args["event_id"]),
            title=str(args["title"]),
            start=str(args["start"]),
            end=str(args["end"]),
            timezone=str(args["timezone"]),
        )

    async def delete_event(args: Mapping[str, Any]):
        validate_arguments("calendar_delete_event", args)
        await provider.delete_event(event_id=str(args["event_id"]))
        return None

    return {
        "calendar_list_events": list_events,
        "calendar_create_event": create_event,
        "calendar_create_invite": create_invite,
        "calendar_update_event": update_event,
        "calendar_delete_event": delete_event,
    }
