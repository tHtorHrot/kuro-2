"""Bounded response reader shared by Calendar and OAuth."""

import json

import httpx

from jarvis.integrations.calendar.provider import CalendarProviderError


async def request_json(client, method, url, *, limit=262144, **kwargs):
    try:
        async with client.stream(method, url, **kwargs) as response:
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise CalendarProviderError("calendar_response_too_large")
            if response.status_code == 204:
                return response.status_code, None
            if not 200 <= response.status_code < 300:
                return response.status_code, None
            try:
                data = json.loads(chunks)
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, UnicodeError):
                raise CalendarProviderError("calendar_invalid_response") from None
            return response.status_code, data
    except httpx.HTTPError:
        raise CalendarProviderError("calendar_transport_error") from None
