import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from jarvis.interfaces.telegram.client import MAX_RESPONSE_BYTES, TelegramClient, TelegramError
from jarvis.interfaces.telegram.repository import Delivery
from jarvis.interfaces.telegram.worker import send_one

TOKEN = "123456:" + "test-only-synthetic-credential-0000"


async def run_call(handler, method="sendMessage", payload=None):
    client = TelegramClient(SecretStr(TOKEN), transport=httpx.MockTransport(handler))
    try:
        return await client.call(method, payload or {})
    finally:
        await client.close()


@pytest.mark.parametrize(
    "error_type,ambiguous,retryable",
    [
        (httpx.ConnectError, False, True),
        (httpx.ConnectTimeout, False, True),
        (httpx.PoolTimeout, False, True),
        (httpx.WriteTimeout, True, False),
        (httpx.ReadTimeout, True, False),
        (httpx.ReadError, True, False),
        (httpx.RemoteProtocolError, True, False),
    ],
)
async def test_send_failure_classification_and_redacted_error(error_type, ambiguous, retryable):
    def handler(request):
        raise error_type("TOKEN-IN-URL: " + str(request.url), request=request)

    with pytest.raises(TelegramError) as caught:
        await run_call(handler)
    assert caught.value.ambiguous is ambiguous
    assert caught.value.retryable is retryable
    assert TOKEN not in str(caught.value)
    assert "TOKEN-IN-URL" not in str(caught.value)


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_send_server_failures_are_ambiguous(status):
    with pytest.raises(TelegramError) as caught:
        await run_call(lambda request: httpx.Response(status, text=TOKEN))
    assert caught.value.ambiguous and not caught.value.retryable
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("delay", [0, -1, True, "4", 86401, None])
async def test_invalid_retry_header_fails_closed(delay):
    with pytest.raises(TelegramError) as caught:
        await run_call(
            lambda request: httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "parameters": {"retry_after": delay},
                },
            )
        )
    assert caught.value.fatal


async def test_retry_after_and_fatal_auth_or_conflict():
    with pytest.raises(TelegramError) as caught:
        await run_call(
            lambda request: httpx.Response(
                429,
                json={
                    "ok": False,
                    "error_code": 429,
                    "parameters": {"retry_after": 37},
                    "description": TOKEN,
                },
            )
        )
    assert caught.value.retry_after == 37
    assert caught.value.retryable and not caught.value.ambiguous
    for status in (401, 409):
        with pytest.raises(TelegramError) as fatal:
            await run_call(
                lambda request, status=status: httpx.Response(status, text="sensitive body")
            )
        assert fatal.value.fatal and "sensitive" not in str(fatal.value)


async def test_redirect_refused_without_following_and_response_bounded():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/leak"})

    with pytest.raises(TelegramError) as caught:
        await run_call(handler)
    assert len(calls) == 1 and caught.value.fatal and caught.value.ambiguous
    with pytest.raises(TelegramError, match="response_too_large"):
        await run_call(lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(TelegramError, match="invalid_response"):
        await run_call(lambda request: httpx.Response(200, text=TOKEN))


async def test_outbound_replies_are_private_fixed_host_and_no_paid_broadcast(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:4444")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 14,
                    "chat": {"id": 123, "type": "private"},
                },
            },
        )

    client = TelegramClient(SecretStr(TOKEN), transport=httpx.MockTransport(handler))
    try:
        assert client._http._trust_env is False
        assert await client.send(123, "Fixed reply") == 14
        assert seen[0].url.host == "api.telegram.org" and seen[0].url.scheme == "https"
        sent = json.loads(seen[0].content)
        assert sent["protect_content"] is True and sent["allow_paid_broadcast"] is False
        assert sent["link_preview_options"]["is_disabled"] is True
        assert "parse_mode" not in sent
        assert await client.send(123, "Copyable", protect_content=False) == 14
        assert json.loads(seen[1].content)["protect_content"] is False
        with pytest.raises(ValueError):
            await client.send(-123, "group")
        with pytest.raises(ValueError):
            await client.call("deleteWebhook", {})
        assert len(seen) == 2
    finally:
        await client.close()


async def test_wrong_returned_chat_is_ambiguous_and_never_redirected():
    client = TelegramClient(
        SecretStr(TOKEN),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "message_id": 1,
                        "chat": {"id": 999, "type": "private"},
                    },
                },
            )
        ),
    )
    try:
        with pytest.raises(TelegramError) as caught:
            await client.send(123, "reply")
        assert caught.value.ambiguous
    finally:
        await client.close()


async def test_poll_sorts_validates_and_acknowledges_only_supplied_offset():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": [
                    {"update_id": 4},
                    {"update_id": 2},
                ],
            },
        )

    client = TelegramClient(SecretStr(TOKEN), transport=httpx.MockTransport(handler))
    try:
        assert [r["update_id"] for r in await client.updates(None, limit=2, wait=1)] == [2, 4]
        await client.updates(5, limit=2, wait=1)
        assert "offset" not in requests[0] and requests[1]["offset"] == 5
        assert requests[0]["allowed_updates"] == ["message", "callback_query"]
    finally:
        await client.close()


@pytest.mark.parametrize("result", [[{"update_id": True}], [{"update_id": -1}], {}, [1]])
async def test_malformed_updates_are_not_accepted(result):
    client = TelegramClient(
        SecretStr(TOKEN),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True, "result": result})
        ),
    )
    try:
        with pytest.raises(TelegramError):
            await client.updates(None, limit=20, wait=1)
    finally:
        await client.close()


async def test_startup_refuses_wrong_bot_or_webhook_without_deleting_it():
    seen = []

    def handler(request):
        seen.append(request.url.path.rsplit("/", 1)[1])
        result = {"id": 123456, "is_bot": True, "username": "TestJarvisBot"}
        if seen[-1] == "getWebhookInfo":
            result = {"url": "https://existing.invalid/private"}
        return httpx.Response(200, json={"ok": True, "result": result})

    client = TelegramClient(SecretStr(TOKEN), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(TelegramError, match="bot_identity_mismatch"):
            await client.identity(111)
        with pytest.raises(TelegramError, match="webhook_present"):
            await client.identity(123456)
        assert set(seen) == {"getMe", "getWebhookInfo"}
    finally:
        await client.close()


async def test_send_lifecycle_records_failure_once_and_propagates_fatal():
    delivery = Delivery(1, 123, "status", 1)
    repo, client = AsyncMock(), AsyncMock()
    repo.claim.return_value = delivery
    failure = TelegramError("transport_failed", ambiguous=True)
    client.send.side_effect = failure
    assert await send_one(repo, client)
    repo.finish.assert_awaited_once_with(delivery, error=failure)
    assert client.send.await_count == 1
    client.send.side_effect = TelegramError("unauthorized", fatal=True)
    with pytest.raises(TelegramError):
        await send_one(repo, client)


async def test_callback_methods_validate_and_use_bounded_endpoints():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    client = TelegramClient(SecretStr(TOKEN), transport=httpx.MockTransport(handler))
    try:
        await client.answer_callback("cb123", "Disetujui ✓")
        await client.strip_buttons(123, 7, "proposal text")
        assert [r.url.path.split("/")[-1] for r in seen] == [
            "answerCallbackQuery",
            "editMessageText",
        ]
        answered = json.loads(seen[0].content)
        assert answered == {"callback_query_id": "cb123", "text": "Disetujui ✓"}
        edited = json.loads(seen[1].content)
        assert edited["reply_markup"] == {} and edited["text"] == "proposal text"
        with pytest.raises(ValueError):
            await client.answer_callback("", "x" * 201)
        with pytest.raises(ValueError):
            await client.strip_buttons(-1, 0, "")
    finally:
        await client.close()


async def test_send_attaches_markup_only_when_present():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 9, "chat": {"id": 123, "type": "private"}}},
        )

    client = TelegramClient(SecretStr(TOKEN), transport=httpx.MockTransport(handler))
    try:
        markup = {"inline_keyboard": [[{"text": "Setuju ✓", "callback_data": "approve:x"}]]}
        await client.send(123, "proposal", reply_markup=markup)
        await client.send(123, "plain")
        assert json.loads(seen[0].content)["reply_markup"] == markup
        assert "reply_markup" not in json.loads(seen[1].content)
    finally:
        await client.close()
