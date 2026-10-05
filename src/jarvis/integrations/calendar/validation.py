"""Bounded Calendar input schemas. Reject coercion before any provider request."""

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

KEYS = {
    "calendar_list_events": {"time_min", "time_max"},
    "calendar_create_event": {"title", "start", "end", "timezone"},
    "calendar_create_invite": {"title", "start", "end", "timezone", "attendees"},
    "calendar_update_event": {"event_id", "title", "start", "end", "timezone"},
    "calendar_delete_event": {"event_id"},
}


def timestamp(value) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("invalid_calendar_timestamp")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("invalid_calendar_timestamp")
    return result


def validate_arguments(tool: str, args: Mapping) -> None:
    if tool not in KEYS or set(args) != KEYS[tool]:
        raise ValueError("invalid_calendar_arguments")
    for key, value in args.items():
        if key != "attendees" and (
            type(value) is not str or not value.strip() or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("invalid_calendar_argument_type")
    if "event_id" in args and not re.fullmatch(r"[A-Za-z0-9_-]{1,1024}", args["event_id"]):
        raise ValueError("invalid_event_id")
    if tool == "calendar_list_events":
        start, end = timestamp(args["time_min"]), timestamp(args["time_max"])
        if not timedelta(0) < end - start <= timedelta(days=31):
            raise ValueError("invalid_calendar_window")
    elif "title" in args:
        if len(args["title"]) > 200 or len(args["timezone"]) > 64:
            raise ValueError("invalid_calendar_title_or_timezone")
        try:
            zone = ZoneInfo(args["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("invalid_calendar_timezone") from None
        start, end = timestamp(args["start"]), timestamp(args["end"])
        if not timedelta(0) < end - start <= timedelta(days=7):
            raise ValueError("invalid_calendar_duration")
        for time in (start, end):
            if time.utcoffset() != time.astimezone(zone).utcoffset():
                raise ValueError("calendar_offset_timezone_mismatch")
    if "attendees" in args:
        attendees = args["attendees"]
        if not isinstance(attendees, list) or not 1 <= len(attendees) <= 20:
            raise ValueError("invalid_attendees")
        if any(
            type(a) is not str
            or len(a) > 254
            or not re.fullmatch(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", a
            )
            for a in attendees
        ):
            raise ValueError("invalid_attendees")
        if len(set(a.lower() for a in attendees)) != len(attendees):
            raise ValueError("duplicate_attendees")
