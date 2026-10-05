"""Calendar reference specialist registration.

The specialist owns capabilities, not authority. Sensitive effects remain
subject to KURO Core authorization and exact-action approval binding.
"""

from jarvis.agents.registry import AgentSpec
from jarvis.tools.contracts import ToolEffect, ToolSpec

CALENDAR_AGENT = "calendar"


def calendar_tool_specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            "calendar_list_events",
            "List calendar events in an explicit time window",
            CALENDAR_AGENT,
            frozenset({"calendar:read"}),
            ToolEffect.READ,
            network_targets=("www.googleapis.com",),
            argument_keys=frozenset({"time_min", "time_max"}),
        ),
        ToolSpec(
            "calendar_create_event",
            "Create a solo calendar event without attendees",
            CALENDAR_AGENT,
            frozenset({"calendar:write"}),
            ToolEffect.REVERSIBLE_WRITE,
            network_targets=("www.googleapis.com",),
            argument_keys=frozenset({"title", "start", "end", "timezone"}),
        ),
        ToolSpec(
            "calendar_create_invite",
            "Create a calendar event that sends invitations to attendees",
            CALENDAR_AGENT,
            frozenset({"calendar:write", "calendar:send"}),
            ToolEffect.EXTERNAL_SEND,
            network_targets=("www.googleapis.com",),
            argument_keys=frozenset({"title", "start", "end", "timezone", "attendees"}),
        ),
        ToolSpec(
            "calendar_update_event",
            "Update title or time of an existing calendar event",
            CALENDAR_AGENT,
            frozenset({"calendar:write"}),
            ToolEffect.REVERSIBLE_WRITE,
            network_targets=("www.googleapis.com",),
            argument_keys=frozenset({"event_id", "title", "start", "end", "timezone"}),
        ),
        ToolSpec(
            "calendar_delete_event",
            "Delete or cancel an existing calendar event",
            CALENDAR_AGENT,
            frozenset({"calendar:write"}),
            ToolEffect.DESTRUCTIVE,
            network_targets=("www.googleapis.com",),
            argument_keys=frozenset({"event_id"}),
        ),
    )


def calendar_agent_spec() -> AgentSpec:
    return AgentSpec(
        CALENDAR_AGENT,
        "Calendar specialist for bounded read and event-management capabilities",
        frozenset(spec.name for spec in calendar_tool_specs()),
        max_steps=6,
    )
