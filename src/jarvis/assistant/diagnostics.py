"""Content-free diagnostics: fixed local codes and numeric HTTP status only."""

import logging

from jarvis.assistant.policy import PolicyError
from jarvis.assistant.router import RouterError

DIAGNOSTICS_VERSION = "2b-diagnostics-1"

POLICY_CODES = frozenset(
    {
        "attempt_already_used",
        "authorization_changed",
        "catalog_changed",
        "context_blocked",
        "context_changed",
        "context_too_large",
        "daily_free_limit",
        "endpoint_blocked",
        "endpoint_unavailable",
        "free_route_has_cost",
        "fresh_consent_required",
        "invalid_price",
        "monthly_budget_exceeded",
        "output_limit_unsupported",
        "per_call_budget_exceeded",
        "premium_disabled",
        "restricted_profile",
        "unknown_context_limit",
        "unknown_pricing",
        "unknown_privacy",
        "unknown_route_kind",
        "unsupported_pricing",
        "zdr_not_verified",
    }
)
ROUTER_CODES = frozenset(
    {
        "http_error",
        "invalid_response",
        "local_policy_error",
        "policy_violation",
        "request_rejected",
        "response_too_large",
        "transport_or_format_error",
        "unverifiable_response",
    }
)
log = logging.getLogger(__name__)


def error_code(error: Exception) -> str:
    if isinstance(error, PolicyError):
        code = str(error)
        return code if code in POLICY_CODES else "policy_blocked"
    if isinstance(error, RouterError):
        code = error.kind if error.kind in ROUTER_CODES else "unavailable"
        if code in {"http_error", "request_rejected"} and error.http_status is not None:
            return f"openrouter_http_{error.http_status}"
        return "openrouter_" + code
    return "unexpected_error"


def report_error(error: Exception, *, phase: str, kind: str, request_id=None) -> str:
    """Never log exceptions, response bodies, headers, URLs, prompts or config."""
    code = error_code(error)
    phase = (
        phase
        if phase in {"guard", "plan", "dispatch", "complete", "offer", "catalog"}
        else "unknown"
    )
    kind = kind if kind in {"free", "premium"} else "unknown"
    log.warning(
        "assistant_operation_failed",
        extra={
            "event": "assistant." + phase,
            "route": kind,
            "request_id": str(request_id) if request_id is not None else None,
            "error_type": code,
            "status": error.http_status if isinstance(error, RouterError) else None,
        },
    )
    return code
