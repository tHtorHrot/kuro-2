"""Provider-neutral calendar contract.

Provider implementations receive normalized arguments only. They do not decide
whether an operation is authorized; KURO's tool policy and durable journal do.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class CalendarProviderError(Exception):
    """Stable provider-boundary failure; never include remote response bodies."""


class CalendarProvider(Protocol):
    async def list_events(self, *, time_min: str, time_max: str) -> Sequence[Mapping[str, Any]]: ...

    async def create_event(
        self, *, title: str, start: str, end: str, timezone: str, request_id: str | None = None
    ) -> Mapping[str, Any]: ...

    async def create_invite(
        self,
        *,
        title: str,
        start: str,
        end: str,
        timezone: str,
        attendees: list[str],
        request_id: str | None = None,
    ) -> Mapping[str, Any]: ...

    async def update_event(
        self, *, event_id: str, title: str, start: str, end: str, timezone: str
    ) -> Mapping[str, Any]: ...

    async def delete_event(self, *, event_id: str) -> None: ...
