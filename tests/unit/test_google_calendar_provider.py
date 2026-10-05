import json
from contextlib import asynccontextmanager

import pytest

from jarvis.integrations.calendar.google import GoogleCalendarProvider
from jarvis.integrations.calendar.provider import CalendarProviderError


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is ...:
            raise ValueError
        return self._payload

    async def aiter_bytes(self):
        yield json.dumps(self._payload).encode()


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        yield self.responses.pop(0)


async def token():
    return "secret-token"


@pytest.mark.asyncio
async def test_google_list_uses_fixed_origin_bearer_and_window():
    client = Client([Response(200, {"items": [{"id": "1"}]})])
    provider = GoogleCalendarProvider(token, client=client)
    result = await provider.list_events(time_min="a", time_max="b")
    assert result == [{"id": "1"}]
    method, url, kwargs = client.calls[0]
    assert method == "GET"
    assert url.startswith("https://www.googleapis.com/calendar/v3/calendars/primary/events")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert kwargs["params"]["timeMin"] == "a"


@pytest.mark.asyncio
async def test_google_solo_create_never_sends_updates_or_attendees():
    client = Client([Response(200, {"id": "2"})])
    provider = GoogleCalendarProvider(token, client=client)
    await provider.create_event(title="Focus", start="s", end="e", timezone="Asia/Jakarta")
    _, _, kwargs = client.calls[0]
    assert kwargs["params"] == {"sendUpdates": "none"}
    assert "attendees" not in kwargs["json"]


@pytest.mark.asyncio
async def test_google_invite_is_explicit_external_send():
    client = Client([Response(200, {"id": "3"})])
    provider = GoogleCalendarProvider(token, client=client)
    await provider.create_invite(
        title="Review", start="s", end="e", timezone="Asia/Jakarta", attendees=["a@example.com"]
    )
    _, _, kwargs = client.calls[0]
    assert kwargs["params"] == {"sendUpdates": "all"}
    assert kwargs["json"]["attendees"] == [{"email": "a@example.com"}]


@pytest.mark.asyncio
async def test_google_provider_maps_remote_error_without_leaking_body():
    client = Client([Response(500, {"secret": "remote body"})])
    provider = GoogleCalendarProvider(token, client=client)
    with pytest.raises(CalendarProviderError) as exc:
        await provider.list_events(time_min="a", time_max="b")
    assert str(exc.value) == "calendar_provider_error"
    assert "remote body" not in str(exc.value)
