"""Fixed-origin OpenRouter boundary: metadata first; no automatic retries/fallbacks."""

import asyncio
import json
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

import httpx
from pydantic import SecretStr

from jarvis.assistant.config import AssistantConfig, Route
from jarvis.assistant.policy import PolicyError, digest, money, validate_messages

BASE = "https://openrouter.ai/api/v1"


class RouterError(Exception):
    def __init__(self, kind: str, *, uncertain: bool = False, http_status: int | None = None):
        self.kind, self.uncertain = kind, uncertain
        self.http_status = (
            http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        )
        super().__init__("OpenRouter: " + kind)


@dataclass(frozen=True)
class Completion:
    content: str = field(repr=False)
    cost: Decimal
    prompt_tokens: int
    completion_tokens: int


def endpoint_plan(endpoint: dict, route: Route, config: AssistantConfig, kind: str) -> dict:
    if (
        endpoint.get("model_id") != route.model
        or endpoint.get("tag") != route.provider
        or endpoint.get("status") != 0
        or not endpoint.get("provider_name")
    ):
        raise PolicyError("endpoint_unavailable")
    if "max_tokens" not in endpoint.get("supported_parameters", []):
        raise PolicyError("output_limit_unsupported")
    context = endpoint.get("context_length")
    maximum = endpoint.get("max_prompt_tokens") or context
    completion = endpoint.get("max_completion_tokens") or context
    if any(type(v) is not int or not 1024 <= v <= 4000000 for v in (context, maximum)):
        raise PolicyError("unknown_context_limit")
    if type(completion) is not int or completion < config.max_output_tokens:
        raise PolicyError("output_limit_unsupported")
    pricing = endpoint.get("pricing")
    if not isinstance(pricing, dict) or not {"prompt", "completion"}.issubset(pricing):
        raise PolicyError("unknown_pricing")
    costs = {key: money(value) for key, value in pricing.items()}
    for key, value in costs.items():
        if key in {"prompt", "completion", "request"}:
            continue
        if key in {"input_cache_read", "input_cache_write"} and value <= costs["prompt"]:
            continue
        if value != 0:
            raise PolicyError("unsupported_pricing")
    if kind == "free" and any(value != 0 for value in costs.values()):
        raise PolicyError("free_route_has_cost")
    if kind not in {"free", "premium"}:
        raise PolicyError("unknown_route_kind")
    cap = (
        costs["prompt"] * min(context, maximum)
        + costs["completion"] * config.max_output_tokens
        + costs.get("request", Decimal(0))
    )
    cap = cap.quantize(Decimal("0.0000000001"), rounding=ROUND_CEILING)
    if cap > config.per_call_budget_usd and kind == "premium":
        raise PolicyError("per_call_budget_exceeded")
    return {
        "model": route.model,
        "provider": route.provider,
        "provider_name": endpoint["provider_name"],
        "pricing_hash": digest({key: str(value.normalize()) for key, value in costs.items()}),
        "kind": kind,
        "prompt_price": str(costs["prompt"]),
        "completion_price": str(costs["completion"]),
        "request_price": str(costs.get("request", Decimal(0))),
        "context_limit": min(context, maximum),
        "max_tokens": config.max_output_tokens,
        "reserve_usd": str(cap),
        "config_hash": config.fingerprint,
        "disable_reasoning": "reasoning" in endpoint.get("supported_parameters", []),
    }


def request_payload(plan: dict, messages: list[dict], data_class: str = "private") -> dict:
    validate_messages(messages, data_class)
    # Capacity check deliberately overestimates tokenizer input; prices reserve full context.
    if len(json.dumps(messages, ensure_ascii=False).encode()) + 4096 > plan["context_limit"]:
        raise PolicyError("context_too_large")
    prices = {
        "prompt": money(plan["prompt_price"]) * 1000000,
        "completion": money(plan["completion_price"]) * 1000000,
        "request": money(plan["request_price"]),
    }
    if plan["kind"] == "free" and any(prices.values()):
        raise PolicyError("free_route_has_cost")
    payload = {
        "model": plan["model"],
        "messages": messages,
        "max_tokens": plan["max_tokens"],
        "stream": False,
        "provider": {
            "only": [plan["provider"]],
            "order": [plan["provider"]],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "zdr": True,
            "max_price": {key: float(value) for key, value in prices.items()},
        },
    }

    if plan.get("disable_reasoning"):
        payload["reasoning"] = {"enabled": False}
    return payload


class OpenRouter:
    def __init__(self, key: SecretStr, *, transport=None):
        self.client = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + key.get_secret_value()},
            timeout=httpx.Timeout(60, connect=10),
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            transport=transport,
        )

    async def close(self):
        await self.client.aclose()

    async def _json(self, method: str, path: str, payload=None):
        inference = method == "POST"
        if not (
            (
                method == "GET"
                and (
                    path == "/endpoints/zdr"
                    or (path.startswith("/models/") and path.endswith("/endpoints"))
                )
            )
            or (inference and path == "/chat/completions")
        ):
            raise PolicyError("endpoint_blocked")
        try:
            async with asyncio.timeout(80 if inference else 30):
                async with self.client.stream(method, BASE + path, json=payload) as response:
                    if response.status_code != 200:
                        known_rejection = response.status_code in {
                            400,
                            401,
                            402,
                            403,
                            404,
                            422,
                            429,
                        }
                        raise RouterError(
                            "request_rejected" if known_rejection else "http_error",
                            uncertain=inference and not known_rejection,
                            http_status=response.status_code,
                        )
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > (1024 * 1024 if inference else 8 * 1024 * 1024):
                            raise RouterError("response_too_large", uncertain=inference)
                    result = json.loads(body, parse_float=Decimal)
                    if not isinstance(result, dict) or "error" in result:
                        raise RouterError("invalid_response", uncertain=inference)
                    return result
        except RouterError:
            raise
        except (TimeoutError, httpx.HTTPError, ValueError, UnicodeError):
            # Even connect errors consume an authorized attempt. No POST retry here.
            raise RouterError("transport_or_format_error", uncertain=inference) from None

    async def plan(self, config: AssistantConfig, kind: str) -> dict:
        route = config.free_route if kind == "free" else config.premium_route
        if route is None or (kind == "premium" and not config.premium_enabled):
            raise PolicyError("premium_disabled")
        zdr = await self._json("GET", "/endpoints/zdr")
        data = zdr.get("data")
        if not isinstance(data, list):
            raise PolicyError("unknown_privacy")
        matching = [
            e for e in data if e.get("model_id") == route.model and e.get("tag") == route.provider
        ]
        if len(matching) != 1:
            raise PolicyError("zdr_not_verified")
        catalog = await self._json("GET", f"/models/{route.model}/endpoints")
        endpoints = catalog.get("data", {}).get("endpoints", [])
        matches = [e for e in endpoints if e.get("tag") == route.provider]
        if len(matches) != 1:
            raise PolicyError("endpoint_unavailable")
        fresh = endpoint_plan(matches[0], route, config, kind)
        if fresh != endpoint_plan(matching[0], route, config, kind):
            raise PolicyError("catalog_changed")
        return fresh

    async def complete(self, plan: dict, messages: list[dict], data_class="private") -> Completion:
        payload = request_payload(plan, messages, data_class)
        result = await self._json("POST", "/chat/completions", payload)
        try:
            if (
                str(result.get("model", "")).removesuffix(":free")
                != plan["model"].removesuffix(":free")
                or result.get("provider") != plan["provider_name"]
            ):
                raise ValueError
            choice = result["choices"][0]
            message, usage = choice["message"], result["usage"]
            content = message["content"]
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content) > 16000
                or message.get("tool_calls")
                or choice.get("finish_reason") not in {"stop", "length"}
            ):
                raise ValueError
            cost = money(usage["cost"])
            prompt_tokens, output_tokens = usage["prompt_tokens"], usage["completion_tokens"]
            if any(type(n) is not int or n < 0 for n in (prompt_tokens, output_tokens)):
                raise ValueError
            if (
                cost > money(plan["reserve_usd"])
                or prompt_tokens > plan["context_limit"]
                or output_tokens > plan["max_tokens"]
            ):
                raise RouterError("policy_violation", uncertain=True)
            return Completion(content, cost, prompt_tokens, output_tokens)
        except RouterError:
            raise
        except (KeyError, ValueError, TypeError, IndexError, PolicyError):
            raise RouterError("unverifiable_response", uncertain=True) from None
