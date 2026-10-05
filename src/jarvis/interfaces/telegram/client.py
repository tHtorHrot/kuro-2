"""Bounded Telegram transport; errors never retain response bodies or token URLs."""

import asyncio
import json
from typing import Any

import httpx
from pydantic import SecretStr

MAX_RESPONSE_BYTES = 1024 * 1024
METHODS = frozenset({"getMe", "getWebhookInfo", "getUpdates", "sendMessage"})


class TelegramError(RuntimeError):
    def __init__(
        self,
        kind: str,
        *,
        retryable: bool = False,
        retry_after: int = 0,
        ambiguous: bool = False,
        fatal: bool = False,
    ):
        super().__init__("Telegram request failed: " + kind)
        self.kind = kind
        self.retryable = retryable
        self.retry_after = retry_after
        self.ambiguous = ambiguous
        self.fatal = fatal


def positive_id(value: Any) -> bool:
    return type(value) is int and 0 < value < 2**52


class TelegramClient:
    def __init__(self, token: SecretStr, *, transport: httpx.AsyncBaseTransport | None = None):
        self._token = token
        self._http = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def call(self, method: str, payload: dict, *, wait: int = 0) -> Any:
        if method not in METHODS:
            raise ValueError("Telegram method is not allowed")
        sending = method == "sendMessage"
        url = "https://api.telegram.org/bot" + self._token.get_secret_value() + "/" + method
        timeout = httpx.Timeout(connect=5, read=wait + 10, write=10, pool=5)
        try:
            async with asyncio.timeout(wait + 20):
                async with self._http.stream(
                    "POST", url, json=payload, timeout=timeout
                ) as response:
                    status = response.status_code
                    if 300 <= status < 400:
                        raise TelegramError("redirect_refused", fatal=True, ambiguous=sending)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise TelegramError("response_too_large", ambiguous=sending)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise TelegramError("connect_failed", retryable=True) from None
        except (httpx.HTTPError, TimeoutError):
            raise TelegramError(
                "transport_failed", retryable=not sending, ambiguous=sending
            ) from None
        if status in (401, 409):
            raise TelegramError("unauthorized" if status == 401 else "poller_conflict", fatal=True)
        if status >= 500:
            raise TelegramError("server_error", retryable=not sending, ambiguous=sending)
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError):
            raise TelegramError("invalid_response", ambiguous=sending) from None
        if not isinstance(data, dict) or type(data.get("ok")) is not bool:
            raise TelegramError("invalid_response", ambiguous=sending)
        if data["ok"] is False:
            code = data.get("error_code")
            if code == 429:
                parameters = data.get("parameters")
                delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
                if type(delay) is not int or not 1 <= delay <= 86400:
                    raise TelegramError("invalid_retry_after", fatal=True)
                raise TelegramError("rate_limited", retryable=True, retry_after=delay)
            raise TelegramError("api_rejected", fatal=code in (401, 409))
        if status != 200 or "result" not in data:
            raise TelegramError("unexpected_status", ambiguous=sending)
        return data["result"]

    async def identity(self, expected_bot_id: int) -> str:
        me = await self.call("getMe", {})
        if (
            not isinstance(me, dict)
            or me.get("is_bot") is not True
            or not positive_id(me.get("id"))
            or me["id"] != expected_bot_id
            or not isinstance(me.get("username"), str)
        ):
            raise TelegramError("bot_identity_mismatch", fatal=True)
        webhook = await self.call("getWebhookInfo", {})
        if not isinstance(webhook, dict) or webhook.get("url") != "":
            # Never delete an existing webhook or drop its backlog automatically.
            raise TelegramError("webhook_present_or_invalid", fatal=True)
        return me["username"]

    async def updates(self, offset: int | None, *, limit: int, wait: int) -> list[dict]:
        payload: dict[str, Any] = {"limit": limit, "timeout": wait, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        updates = await self.call("getUpdates", payload, wait=wait)
        if not isinstance(updates, list) or len(updates) > limit:
            raise TelegramError("invalid_updates")
        for update in updates:
            if (
                not isinstance(update, dict)
                or type(update.get("update_id")) is not int
                or not 0 <= update["update_id"] < 2**63 - 1
            ):
                raise TelegramError("invalid_update_id")
        return sorted(updates, key=lambda update: update["update_id"])

    async def send(self, chat_id: int, text: str) -> int:
        if not positive_id(chat_id) or not 1 <= len(text) <= 4096:
            raise ValueError("Invalid private reply")
        result = await self.call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "protect_content": True,
                "allow_paid_broadcast": False,
                "link_preview_options": {"is_disabled": True},
            },
        )
        chat = result.get("chat") if isinstance(result, dict) else None
        if (
            not isinstance(chat, dict)
            or chat.get("type") != "private"
            or chat.get("id") != chat_id
            or not positive_id(result.get("message_id"))
        ):
            raise TelegramError("invalid_send_result", ambiguous=True)
        return result["message_id"]
