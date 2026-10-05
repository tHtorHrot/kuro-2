import asyncio
import json
import logging
import time
from collections import OrderedDict, deque
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from jarvis.core.config import Settings

log = logging.getLogger(__name__)


class RequestBodyTimeout(Exception):
    pass


class RateLimiter:
    """Bounded in-process limiter for the explicitly single-process deployment."""

    def __init__(self, limit: int, max_clients: int):
        self.limit = limit
        self.max_clients = max_clients
        self.clients: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, key: str, now: float) -> bool:
        history = self.clients.pop(key, deque())
        while history and history[0] <= now - 60:
            history.popleft()
        accepted = len(history) < self.limit
        if accepted:
            history.append(now)
        self.clients[key] = history
        while len(self.clients) > self.max_clients:
            self.clients.popitem(last=False)
        return accepted


class BoundaryMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.limiter = RateLimiter(settings.requests_per_minute, settings.rate_limit_max_clients)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        headers = dict(scope["headers"])
        try:
            supplied = headers.get(b"x-request-id", b"").decode("ascii")
            request_id = str(UUID(supplied))
        except (ValueError, UnicodeError):
            pass
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.monotonic()
        status = 500
        response_started = False
        method = scope["method"]
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"}:
            method = "OTHER"

        async def wrapped_send(message: Message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        async def reject(code: int, name: str):
            body = json.dumps(
                {
                    "type": "about:blank",
                    "title": name,
                    "status": code,
                    "code": name,
                    "request_id": request_id,
                }
            ).encode()
            extra = [(b"retry-after", b"60")] if code == 429 else []
            await wrapped_send(
                {
                    "type": "http.response.start",
                    "status": code,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode()),
                        *extra,
                    ],
                }
            )
            await wrapped_send({"type": "http.response.body", "body": body})

        try:
            # Ignore forwarded IP headers. Uvicorn proxy headers are disabled in this release.
            client = scope.get("client")
            client_key = client[0] if client else "unknown"
            if not self.limiter.allow(client_key, start):
                return await reject(429, "rate_limited")
            try:
                length = int(headers.get(b"content-length", b"0"))
                if length < 0:
                    raise ValueError
            except ValueError:
                return await reject(400, "invalid_content_length")
            if length > self.settings.max_request_bytes:
                return await reject(413, "request_too_large")
            chunks = bytearray()
            try:
                async with asyncio.timeout(self.settings.body_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body = message.get("body", b"")
                        if len(chunks) + len(body) > self.settings.max_request_bytes:
                            return await reject(413, "request_too_large")
                        chunks.extend(body)
                        if not message.get("more_body", False):
                            break
            except TimeoutError as exc:
                raise RequestBodyTimeout from exc
            delivered = False

            async def replay_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(chunks), "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, wrapped_send)
        except RequestBodyTimeout:
            if response_started:
                raise
            await reject(408, "request_timeout")
        except Exception as exc:
            log.error(
                "unhandled_error",
                extra={"request_id": request_id, "error_type": type(exc).__name__},
            )
            if response_started:
                raise
            await reject(500, "internal_error")
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            log.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "route": route,
                    "method": method,
                    "status": status,
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                },
            )
            app = scope.get("app")
            if app and hasattr(app.state, "http_requests"):
                app.state.http_requests.labels(method=method, route=route, status=str(status)).inc()
