import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import SecretStr

from jarvis.integrations.calendar.oauth import GoogleOAuthTokenProvider
from jarvis.integrations.calendar.provider import CalendarProviderError


class Response:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {"access_token": "access-1", "expires_in": 3600}

    def json(self):
        return self._data

    async def aiter_bytes(self):
        yield json.dumps(self._data).encode()


class Client:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.calls.append((url, kwargs))
        yield self.responses.pop(0)


@pytest.mark.asyncio
async def test_refresh_uses_fixed_origin_and_refresh_grant():
    client = Client([Response()])
    token = GoogleOAuthTokenProvider(
        SecretStr("cid"), SecretStr("secret"), SecretStr("refresh"), client=client
    )
    assert await token() == "access-1"
    url, call = client.calls[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert call["data"]["grant_type"] == "refresh_token"
    assert call["data"]["refresh_token"] == "refresh"


@pytest.mark.asyncio
async def test_cached_access_token_avoids_second_refresh():
    client = Client([Response()])
    token = GoogleOAuthTokenProvider(
        SecretStr("cid"), SecretStr("secret"), SecretStr("refresh"), client=client
    )
    assert await token() == "access-1"
    assert await token() == "access-1"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_oauth_denial_does_not_leak_remote_body():
    client = Client([Response(400, {"error_description": "SUPER SECRET"})])
    token = GoogleOAuthTokenProvider(
        SecretStr("cid"), SecretStr("secret"), SecretStr("refresh"), client=client
    )
    with pytest.raises(CalendarProviderError) as exc:
        await token()
    assert str(exc.value) == "calendar_oauth_denied"
    assert "SUPER SECRET" not in str(exc.value)


@pytest.mark.asyncio
async def test_invalid_oauth_payload_fails_closed():
    client = Client([Response(200, {"access_token": "x"})])
    token = GoogleOAuthTokenProvider(
        SecretStr("cid"), SecretStr("secret"), SecretStr("refresh"), client=client
    )
    with pytest.raises(CalendarProviderError, match="calendar_oauth_invalid_response"):
        await token()


@pytest.mark.asyncio
async def test_transport_failure_is_stable_code():
    class Broken:
        @asynccontextmanager
        async def stream(self, *args, **kwargs):
            raise httpx.ConnectError("credential-bearing diagnostic")
            yield

    token = GoogleOAuthTokenProvider(
        SecretStr("cid"), SecretStr("secret"), SecretStr("refresh"), client=Broken()
    )
    with pytest.raises(CalendarProviderError) as exc:
        await token()
    assert str(exc.value) == "calendar_oauth_transport_error"
