"""Minimal Google Calendar REST adapter.

Authentication is injected as a callable returning an OAuth access token. This
module never reads credentials from model-visible state, action arguments, or
the database. Token refresh/secret storage belongs to the deployment boundary.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from jarvis.integrations.calendar.http import request_json
from jarvis.integrations.calendar.provider import CalendarProviderError

TokenProvider = Callable[[], Awaitable[str]]


class GoogleCalendarProvider:
    BASE_URL = "https://www.googleapis.com/calendar/v3"

    def __init__(self, token_provider: TokenProvider, *, calendar_id: str = "primary", client=None):
        self._token_provider = token_provider
        self._calendar_id = calendar_id
        self._client = client

    async def _request(self, method: str, path: str, *, params=None, json=None):
        token = await self._token_provider()
        if not token:
            raise CalendarProviderError("calendar_auth_unavailable")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        owned = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=20.0, follow_redirects=False, trust_env=False
        )
        try:
            status, data = await request_json(
                client, method, f"{self.BASE_URL}{path}", headers=headers, params=params, json=json
            )
        except httpx.HTTPError:
            raise CalendarProviderError("calendar_transport_error") from None
        finally:
            if owned:
                await client.aclose()
        if status == 401 or status == 403:
            raise CalendarProviderError("calendar_auth_denied")
        if status == 404:
            raise CalendarProviderError("calendar_event_not_found")
        if status == 409:
            raise CalendarProviderError("calendar_id_conflict")
        if not 200 <= status < 300:
            raise CalendarProviderError("calendar_provider_error")
        return data

    @property
    def _events_path(self) -> str:
        return f"/calendars/{quote(self._calendar_id, safe='')}/events"

    async def list_events(self, *, time_min: str, time_max: str) -> Sequence[Mapping[str, Any]]:
        events, seen = [], set()
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50,
            "fields": "items(id,summary,start,end,status),nextPageToken",
        }
        for _ in range(4):
            data = await self._request("GET", self._events_path, params=params)
            items = data.get("items", [])
            if not isinstance(items, list) or len(events) + len(items) > 100:
                raise CalendarProviderError("calendar_result_limit")
            events.extend(self._event(item) for item in items)
            token = data.get("nextPageToken")
            if not token:
                return events
            if not isinstance(token, str) or len(token) > 2048 or token in seen:
                raise CalendarProviderError("calendar_invalid_pagination")
            seen.add(token)
            params["pageToken"] = token
        raise CalendarProviderError("calendar_page_limit")

    @staticmethod
    def _event(data, *, expected_id=None):
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("id"), str)
            or not 1 <= len(data["id"]) <= 1024
        ):
            raise CalendarProviderError("calendar_invalid_event")
        if expected_id is not None and data["id"] != expected_id:
            raise CalendarProviderError("calendar_event_identity_mismatch")
        result = {"id": data["id"]}
        for key in ("summary", "status"):
            if key in data:
                if not isinstance(data[key], str) or len(data[key]) > 2000:
                    raise CalendarProviderError("calendar_invalid_event")
                result[key] = data[key][:200]
        for key in ("start", "end"):
            if key in data:
                value = data[key]
                if not isinstance(value, dict):
                    raise CalendarProviderError("calendar_invalid_event")
                result[key] = {}
                for field in ("date", "dateTime", "timeZone"):
                    if field in value:
                        if not isinstance(value[field], str) or len(value[field]) > 64:
                            raise CalendarProviderError("calendar_invalid_event")
                        result[key][field] = value[field]
        return result

    async def get_event(self, *, event_id: str):
        return self._event(
            await self._request("GET", f"{self._events_path}/{quote(event_id, safe='')}")
        )

    @staticmethod
    def _body(*, title: str, start: str, end: str, timezone: str, attendees=None):
        body = {
            "summary": title,
            "start": {"dateTime": start, "timeZone": timezone},
            "end": {"dateTime": end, "timeZone": timezone},
        }
        if attendees is not None:
            body["attendees"] = [{"email": address} for address in attendees]
        return body

    async def create_event(
        self, *, title: str, start: str, end: str, timezone: str, request_id: str | None = None
    ):
        body = self._body(title=title, start=start, end=end, timezone=timezone)
        if request_id:
            body["id"] = request_id
        return self._event(
            await self._request(
                "POST",
                self._events_path,
                params={"sendUpdates": "none"},
                json=body,
            ),
            expected_id=request_id,
        )

    async def create_invite(
        self,
        *,
        title: str,
        start: str,
        end: str,
        timezone: str,
        attendees: list[str],
        request_id: str | None = None,
    ):
        body = self._body(title=title, start=start, end=end, timezone=timezone, attendees=attendees)
        if request_id:
            body["id"] = request_id
        return self._event(
            await self._request(
                "POST",
                self._events_path,
                params={"sendUpdates": "all"},
                json=body,
            ),
            expected_id=request_id,
        )

    async def update_event(self, *, event_id: str, title: str, start: str, end: str, timezone: str):
        event_path = f"{self._events_path}/{quote(event_id, safe='')}"
        return self._event(
            await self._request(
                "PATCH",
                event_path,
                params={"sendUpdates": "none"},
                json=self._body(title=title, start=start, end=end, timezone=timezone),
            )
        )

    async def delete_event(self, *, event_id: str) -> None:
        event_path = f"{self._events_path}/{quote(event_id, safe='')}"
        await self._request("DELETE", event_path, params={"sendUpdates": "all"})
