"""Verify an exact solo-event instruction without trusting a model's interpretation.

This deliberately accepts a small complete grammar. Unmatched natural language
is still a proposal, but cannot grant automatic write authority. A later semantic
planner must ask for missing details or present the exact action for approval.
"""

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_CREATE = re.compile(
    r"(?:KURO[, :]\s*)?(?:tolong\s+)?(?:buat(?:kan)?|tambahkan|jadwalkan)\s+"
    r'(?:acara|rapat|meeting|event)\s+"(?P<title>[^"\r\n]{1,200})"\s+'
    r"pada\s+(?P<date>\d{4}-\d{2}-\d{2})\s+jam\s+"
    r"(?P<start>\d{2}:\d{2})\s+(?:sampai|hingga)\s+(?P<end>\d{2}:\d{2})\s+"
    r"zona\s+(?P<timezone>[A-Za-z0-9_+\-/]{1,64})",
    re.IGNORECASE,
)
_KEYS = frozenset({"title", "start", "end", "timezone"})


def _local_time(day: str, clock: str, zone: ZoneInfo) -> datetime:
    wall = datetime.fromisoformat(f"{day}T{clock}:00")
    first = wall.replace(tzinfo=zone, fold=0)
    second = wall.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("ambiguous_or_missing_local_time")
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != wall:
        raise ValueError("missing_local_time")
    return first


def parse_solo_create(text: str) -> dict | None:
    """Extract all fields from the complete, user-authored command only."""
    match = _CREATE.fullmatch(text.strip())
    if not match:
        return None
    fields = match.groupdict()
    try:
        zone = ZoneInfo(fields["timezone"])
        args = {
            "title": fields["title"],
            "timezone": fields["timezone"],
            "start": _local_time(fields["date"], fields["start"], zone).isoformat(),
            "end": _local_time(fields["date"], fields["end"], zone).isoformat(),
        }
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return args if matches_solo_create(text, args) else None


def matches_solo_create(text: str, arguments: Mapping) -> bool:
    """True only if the entire user instruction matches every proposed field.

    Example: KURO, buat rapat "Review" pada 2026-10-03 jam 10:00
    sampai 11:00 zona Asia/Jakarta
    """
    if not isinstance(text, str) or not isinstance(arguments, Mapping):
        return False
    if set(arguments) != _KEYS or any(type(v) is not str for v in arguments.values()):
        return False
    match = _CREATE.fullmatch(text.strip())
    if match is None:
        return False
    fields = match.groupdict()
    if arguments["title"] != fields["title"] or not fields["title"].strip():
        return False
    if any(ord(c) < 32 for c in fields["title"]):
        return False
    if arguments["timezone"] != fields["timezone"]:
        return False
    try:
        zone = ZoneInfo(fields["timezone"])
        start = _local_time(fields["date"], fields["start"], zone)
        end = _local_time(fields["date"], fields["end"], zone)
        proposed_start = datetime.fromisoformat(arguments["start"])
        proposed_end = datetime.fromisoformat(arguments["end"])
        return bool(
            end > start
            and proposed_start.tzinfo is not None
            and proposed_end.tzinfo is not None
            and proposed_start.astimezone(UTC) == start.astimezone(UTC)
            and proposed_end.astimezone(UTC) == end.astimezone(UTC)
        )
    except (ValueError, TypeError, ZoneInfoNotFoundError, OverflowError):
        return False
