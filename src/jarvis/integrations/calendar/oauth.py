"""Google OAuth refresh-token boundary for Calendar.

Long-lived credentials are read by the deployment layer and passed here as
SecretStr values. Tokens are cached only in process memory and never exposed to
agents, action arguments, journals, or logs.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import SecretStr

from jarvis.integrations.calendar.http import request_json
from jarvis.integrations.calendar.provider import CalendarProviderError


class GoogleOAuthTokenProvider:
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        client_id: SecretStr,
        client_secret: SecretStr,
        refresh_token: SecretStr,
        *,
        client=None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._client = client
        self._access_token: str | None = None
        self._expires_at = datetime.min.replace(tzinfo=UTC)
        self._lock = asyncio.Lock()

    async def __call__(self) -> str:
        # Refresh five minutes early; concurrent callers share one refresh.
        if self._access_token and datetime.now(UTC) + timedelta(minutes=5) < self._expires_at:
            return self._access_token
        async with self._lock:
            if self._access_token and datetime.now(UTC) + timedelta(minutes=5) < self._expires_at:
                return self._access_token
            await self._refresh()
            assert self._access_token is not None
            return self._access_token

    async def _refresh(self) -> None:
        owned = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=15.0, follow_redirects=False, trust_env=False
        )
        try:
            status, data = await request_json(
                client,
                "POST",
                self.TOKEN_URL,
                limit=16384,
                data={
                    "client_id": self._client_id.get_secret_value(),
                    "client_secret": self._client_secret.get_secret_value(),
                    "refresh_token": self._refresh_token.get_secret_value(),
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError:
            raise CalendarProviderError("calendar_oauth_transport_error") from None
        except CalendarProviderError as exc:
            if str(exc) == "calendar_transport_error":
                raise CalendarProviderError("calendar_oauth_transport_error") from None
            raise
        finally:
            if owned:
                await client.aclose()
        if status != 200:
            raise CalendarProviderError("calendar_oauth_denied")
        try:
            token, expires_in = data["access_token"], data["expires_in"]
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 8192
                or type(expires_in) is not int
            ):
                raise ValueError
            if not 60 <= expires_in <= 86400:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise CalendarProviderError("calendar_oauth_invalid_response") from None
        self._access_token = token
        self._expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
