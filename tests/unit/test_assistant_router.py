import json
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from jarvis.assistant.config import AssistantConfig, Route
from jarvis.assistant.policy import SYSTEM_PROMPT, PolicyError, consent_digest, money, safe_content
from jarvis.assistant.repository import telegram_text
from jarvis.assistant.router import OpenRouter, RouterError, endpoint_plan, request_payload


def config(**values):
    return AssistantConfig(
        owner_id=uuid4(),
        account_privacy_confirmed=True,
        free_route=Route(model="qwen/test:free", provider="example/fp8"),
        **values,
    )


def endpoint(cfg=None, premium=False):
    cfg = cfg or config()
    route = cfg.premium_route if premium else cfg.free_route
    return {
        "model_id": route.model,
        "tag": route.provider,
        "status": 0,
        "provider_name": "Example",
        "context_length": 32768,
        "max_prompt_tokens": None,
        "max_completion_tokens": 4096,
        "supported_parameters": ["max_tokens", "reasoning"],
        "pricing": {
            "prompt": "0.0000001" if premium else "0",
            "completion": "0.0000003" if premium else "0",
            "discount": 0,
        },
    }


def messages():
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Halo Jarvis"},
    ]


def response(plan):
    return {
        "model": plan["model"].removesuffix(":free"),
        "provider": "Example",
        "choices": [{"message": {"content": "Halo!"}, "finish_reason": "stop"}],
        "usage": {"cost": 0, "prompt_tokens": 200, "completion_tokens": 2},
    }


def test_free_payload_enforces_fixed_route_privacy_no_tools_and_zero_price():
    cfg = config()
    plan = endpoint_plan(endpoint(cfg), cfg.free_route, cfg, "free")
    data = request_payload(plan, messages())
    assert data["provider"] == {
        "only": ["example/fp8"],
        "order": ["example/fp8"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
        "max_price": {"prompt": 0.0, "completion": 0.0, "request": 0.0},
    }
    assert data["max_tokens"] == 512 and not data["stream"]
    assert data["reasoning"] == {"enabled": False}
    assert not {"plugins", "tools", "models", "user", "trace", "session_id"} & data.keys()


@pytest.mark.parametrize(
    "patch",
    [
        {"pricing": {"prompt": "0.1", "completion": "0"}},
        {"pricing": {"prompt": "0", "completion": "0", "image": "0.1"}},
        {"pricing": {"prompt": "0", "completion": "0", "tier": {"long": "1"}}},
        {"pricing": {"prompt": "NaN", "completion": "0"}},
        {"status": 1},
        {"tag": "different"},
        {"model_id": "other/model"},
        {"context_length": None},
        {"supported_parameters": []},
    ],
)
def test_unknown_changed_or_nonfree_endpoints_fail_closed(patch):
    cfg = config()
    e = {**endpoint(cfg), **patch}
    with pytest.raises(PolicyError):
        endpoint_plan(e, cfg.free_route, cfg, "free")


def test_premium_cap_conservative_and_unit_conversion():
    cfg = config(
        premium_route=Route(model="qwen/paid", provider="example/fp8"),
        per_call_budget_usd="0.01",
        monthly_budget_usd="0.10",
    )
    plan = endpoint_plan(endpoint(cfg, True), cfg.premium_route, cfg, "premium")
    assert Decimal(plan["reserve_usd"]) == Decimal("0.0034304")
    assert request_payload(plan, messages())["provider"]["max_price"]["prompt"] == 0.1
    too_low = cfg.model_copy(update={"per_call_budget_usd": Decimal("0.001")})
    with pytest.raises(PolicyError, match="per_call_budget"):
        endpoint_plan(endpoint(cfg, True), cfg.premium_route, too_low, "premium")


@pytest.mark.parametrize(
    "text",
    ["password=abcdef", "sk-or-private123", "jvt1.private", "-----BEGIN RSA PRIVATE KEY-----"],
)
def test_secrets_never_enter_inference(text):
    cfg = config()
    plan = endpoint_plan(endpoint(cfg), cfg.free_route, cfg, "free")
    assert not safe_content(text)
    with pytest.raises(PolicyError):
        request_payload(plan, [messages()[0], {"role": "user", "content": text}])


def test_restricted_class_and_oversized_context_rejected():
    cfg = config()
    plan = endpoint_plan(endpoint(cfg), cfg.free_route, cfg, "free")
    with pytest.raises(PolicyError):
        request_payload(plan, messages(), "restricted")
    with pytest.raises(PolicyError):
        request_payload(plan, [messages()[0], {"role": "user", "content": "a" * 50000}])


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", -1, {}, None])
def test_price_parser_never_accepts_ambiguous_values(value):
    with pytest.raises(PolicyError):
        money(value)


def test_config_rejects_auto_paid_fallback_and_unconfirmed_privacy():
    assert not config().premium_enabled
    for model in ("openrouter/auto", "typesafe/jev-router", "qwen/model:floor"):
        with pytest.raises(ValidationError):
            Route(model=model, provider="example")
    with pytest.raises(ValidationError):
        AssistantConfig.model_validate(
            {**config().model_dump(), "account_privacy_confirmed": False}
        )
    with pytest.raises(ValidationError):
        config(per_call_budget_usd="1", monthly_budget_usd="0")


def test_consent_bound_to_exact_snapshot_plan_owner_request_and_secret():
    a = consent_digest("code", "req-a", "context", "plan", "pepper")
    assert len(a) == 32
    for args in (
        ("wrong", "req-a", "context", "plan", "pepper"),
        ("code", "req-b", "context", "plan", "pepper"),
        ("code", "req-a", "other", "plan", "pepper"),
        ("code", "req-a", "context", "pricechanged", "pepper"),
    ):
        assert a != consent_digest(*args)


def test_telegram_utf16_output_bound_with_astral_characters():
    output = telegram_text("😀" * 8000)
    assert len(output.encode("utf-16-le")) <= 7600
    assert len(output.encode()) < 16000


async def test_metadata_and_free_inference_fixed_origin_payload_and_response_validation():
    cfg = config()
    e = endpoint(cfg)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "openrouter.ai"
        if request.url.path.endswith("/zdr"):
            return httpx.Response(200, json={"data": [e]})
        if request.method == "GET":
            return httpx.Response(200, json={"data": {"endpoints": [e]}})
        plan = endpoint_plan(e, cfg.free_route, cfg, "free")
        return httpx.Response(200, json=response(plan))

    client = OpenRouter(SecretStr("fake-key-only"), transport=httpx.MockTransport(handler))
    try:
        plan = await client.plan(cfg, "free")
        result = await client.complete(plan, messages())
        assert result.content == "Halo!" and result.cost == 0
        assert len(calls) == 3 and json.loads(calls[-1].content)["provider"]["zdr"] is True
    finally:
        await client.close()


async def test_missing_zdr_no_inference_or_policy_downgrade():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": []})

    client = OpenRouter(SecretStr("fake"), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(PolicyError, match="zdr_not_verified"):
            await client.plan(config(), "free")
        assert len(calls) == 1 and calls[0].method == "GET"
    finally:
        await client.close()


@pytest.mark.parametrize("status,uncertain", [(429, False), (401, False), (500, True), (302, True)])
async def test_http_errors_never_retry_or_follow_redirect(status, uncertain):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"location": "https://other.example"}, text="PRIVATE PROVIDER ERROR"
        )

    cfg = config()
    plan = endpoint_plan(endpoint(cfg), cfg.free_route, cfg, "free")
    client = OpenRouter(SecretStr("fake"), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RouterError) as err:
            await client.complete(plan, messages())
        assert err.value.uncertain is uncertain and "PRIVATE" not in str(err.value)
        assert err.value.http_status == status
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.parametrize(
    "change", ["cost", "provider", "model", "tokens", "missing_usage", "tools"]
)
async def test_unexpected_provider_response_is_not_trusted(change):
    cfg = config()
    plan = endpoint_plan(endpoint(cfg), cfg.free_route, cfg, "free")
    data = deepcopy(response(plan))
    if change == "cost":
        data["usage"]["cost"] = 0.01
    if change == "tokens":
        data["usage"]["completion_tokens"] = 9000
    if change == "provider":
        data["provider"] = "Other"
    if change == "model":
        data["model"] = "other/paid"
    if change == "missing_usage":
        del data["usage"]
    if change == "tools":
        data["choices"][0]["message"]["tool_calls"] = [{}]
    client = OpenRouter(
        SecretStr("fake"), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    )
    try:
        with pytest.raises(RouterError) as err:
            await client.complete(plan, messages())
        assert err.value.uncertain
    finally:
        await client.close()
