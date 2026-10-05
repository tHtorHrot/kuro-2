import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from jarvis.api.dependencies import TenantSession, principal
from jarvis.api.middleware import BoundaryMiddleware, RateLimiter
from jarvis.identity.service import Principal


def authorize(app, scopes):
    app.dependency_overrides[principal] = lambda: Principal(uuid4(), uuid4(), frozenset(scopes))


async def test_health_headers_and_readiness(client, app):
    response = await client.get("/health/live")
    assert response.status_code == 200
    UUID(response.headers["x-request-id"])
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert (await client.get("/health/ready")).status_code == 200
    app.state.database.healthy = False
    assert (await client.get("/health/ready")).status_code == 503


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer broken", "Bearer jvt1.a.b.c"])
async def test_protected_api_denies_invalid_credentials(client, header):
    headers = {"Authorization": header} if header else {}
    for route in ("/api/v1/me", "/api/v1/auth/tokens", "/api/v1/audit", "/metrics"):
        response = await client.get(route, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


async def test_policy_is_explicit_about_inactive_integrations(app, client):
    authorize(app, {"policy:read"})
    policy = (await client.get("/api/v1/policy")).json()
    assert policy["premium_mode"] == "confirm_each_use"
    assert not policy["infrastructure_target_is_billing_cap"]
    assert not policy["llm_integration_active"]
    assert policy["telegram_adapter_available"]
    assert policy["telegram_runtime_status"] == "check_telegram_status_cli"


async def test_metrics_scope_and_bounded_route_labels(app, client):
    authorize(app, {"profile:read"})
    assert (await client.get("/metrics")).status_code == 403
    await client.get("/private-document-name?token=DO-NOT-RETAIN")
    await client.request("UNUSUAL-SECRET-METHOD", "/absent")
    authorize(app, {"ops:metrics"})
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert 'route="unmatched"' in response.text
    assert 'method="OTHER"' in response.text
    for value in ("private-document-name", "DO-NOT-RETAIN", "UNUSUAL-SECRET-METHOD"):
        assert value not in response.text


async def test_host_injection_and_public_docs_denied(client):
    assert (await client.get("/health/live", headers={"Host": "evil.example"})).status_code == 400
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


async def test_body_limit_declared_and_streamed(client):
    response = await client.post("/absent", headers={"content-length": "9999999"})
    assert response.status_code == 413

    async def stream():
        yield b"a" * 40000
        yield b"b" * 40000

    assert (await client.post("/absent", content=stream())).status_code == 413
    assert (await client.post("/absent", headers={"content-length": "-1"})).status_code == 400


async def test_unexpected_error_is_private_and_keeps_security_headers(app, client):
    @app.get("/test-error")
    async def error():
        raise RuntimeError("SELECT private_document; password=confidential")

    response = await client.get("/test-error")
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert "confidential" not in response.text


async def test_commit_failure_never_returns_success(app, client):
    authorize(app, {"profile:read"})

    @asynccontextmanager
    async def failed_commit(owner):
        yield object()
        raise RuntimeError("simulated commit failure")

    app.state.database.tenant = failed_commit

    @app.post("/test-commit")
    async def mutation(session: TenantSession):
        return {"success": True}

    response = await client.post("/test-commit")
    assert response.status_code == 500
    assert "success" not in response.text


async def test_validation_errors_do_not_echo_input(app, client):
    @app.get("/test-validation/{number}")
    async def validate(number: int):
        return number

    response = await client.get("/test-validation/PRIVATE-CONTENT")
    assert response.status_code == 422
    assert "PRIVATE-CONTENT" not in response.text


async def test_lifespan_closes_database(app):
    async with app.router.lifespan_context(app):
        assert not app.state.database.closed
    assert app.state.database.closed


def test_rate_limiter_expires_and_bounds_memory():
    limiter = RateLimiter(limit=2, max_clients=2)
    assert limiter.allow("a", 0)
    assert limiter.allow("a", 1)
    assert not limiter.allow("a", 2)
    assert limiter.allow("a", 61)
    limiter.allow("b", 61)
    limiter.allow("c", 61)
    assert len(limiter.clients) == 2


async def test_forwarded_ip_does_not_bypass_rate_limit(settings):
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = BoundaryMiddleware(inner, settings.model_copy(update={"requests_per_minute": 1}))
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://testserver"
    ) as c:
        assert (await c.get("/", headers={"X-Forwarded-For": "1.1.1.1"})).status_code == 200
        response = await c.get("/", headers={"X-Forwarded-For": "2.2.2.2"})
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"


async def test_slow_body_times_out(settings):
    async def unreachable(scope, receive, send):
        pytest.fail("Request body timeout should occur first")

    middleware = BoundaryMiddleware(
        unreachable, settings.model_copy(update={"body_timeout_seconds": 0.01})
    )

    async def slow_receive():
        await asyncio.sleep(1)

    messages = []

    async def send(message):
        messages.append(message)

    await middleware(
        {"type": "http", "method": "POST", "headers": [], "client": ("a", 1)}, slow_receive, send
    )
    assert messages[0]["status"] == 408
