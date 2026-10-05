import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from starlette.responses import JSONResponse

from jarvis.api.dependencies import CurrentPrincipal, TenantSession
from jarvis.api.schemas import AuditView, TokenView, UserView
from jarvis.core.errors import ApplicationError
from jarvis.identity.service import audit
from jarvis.storage.models import ApiToken, AuditEvent, User

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/health/live", include_in_schema=False)
async def live():
    return {"status": "alive"}


@router.get("/health/ready", include_in_schema=False)
async def ready(request: Request):
    try:
        healthy = await request.app.state.database.ready()
    except Exception as exc:
        log.warning("readiness_failed", extra={"error_type": type(exc).__name__})
        healthy = False
    return JSONResponse({"status": "ready" if healthy else "not_ready"}, 200 if healthy else 503)


@router.get("/api/v1/me", response_model=UserView)
async def me(actor: CurrentPrincipal, session: TenantSession):
    actor.require("profile:read")
    user = await session.get(User, actor.owner_id)
    if user is None:
        raise ApplicationError(404, "not_found", "Akun tidak ditemukan.")
    return UserView.model_validate(user)


@router.get("/api/v1/auth/tokens", response_model=list[TokenView])
async def tokens(actor: CurrentPrincipal, session: TenantSession):
    actor.require("tokens:read")
    rows = (
        await session.scalars(
            select(ApiToken)
            .where(ApiToken.owner_id == actor.owner_id)
            .order_by(ApiToken.created_at.desc())
            .limit(100)
        )
    ).all()
    return [TokenView.model_validate(row) for row in rows]


@router.post("/api/v1/auth/tokens/{token_id}/revoke", status_code=204)
async def revoke(token_id: UUID, request: Request, actor: CurrentPrincipal, session: TenantSession):
    actor.require("tokens:revoke")
    token = await session.scalar(
        select(ApiToken)
        .where(ApiToken.id == token_id, ApiToken.owner_id == actor.owner_id)
        .with_for_update()
    )
    if token is None:
        raise ApplicationError(404, "not_found", "Token tidak ditemukan.")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        audit(
            session,
            actor.owner_id,
            "token.revoked",
            token.id,
            actor.token_id,
            request.state.request_id,
        )
        # Ensure DB errors happen before a successful HTTP response is emitted.
        await session.flush()
    return Response(status_code=204)


@router.get("/api/v1/policy")
async def policy(request: Request, actor: CurrentPrincipal):
    actor.require("policy:read")
    settings = request.app.state.settings
    return {
        "stage": "3",
        "document_access": "owner_only",
        "cloud_privacy": settings.cloud_privacy,
        "premium_mode": settings.premium_mode,
        "infrastructure_target_idr": settings.infrastructure_target_idr,
        "infrastructure_target_is_billing_cap": False,
        "llm_integration_active": None,
        "llm_adapter_available": True,
        "llm_status_source": "assistant-status (per owner)",
        "telegram_adapter_available": True,
        "telegram_runtime_status": "check_telegram_status_cli",
    }


@router.get("/api/v1/audit", response_model=list[AuditView])
async def audit_events(
    actor: CurrentPrincipal, session: TenantSession, limit: int = Query(default=25, ge=1, le=100)
):
    actor.require("audit:read")
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.owner_id == actor.owner_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        )
    ).all()
    return [AuditView.model_validate(row) for row in events]


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request, actor: CurrentPrincipal):
    actor.require("ops:metrics")
    return Response(
        generate_latest(request.app.state.metrics_registry),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )
