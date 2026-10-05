"""Pure Stage 4 authorization policy with minimum necessary user friction."""

from jarvis.tools.contracts import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationResult,
    ToolEffect,
    ToolSpec,
)


def authorize_tool(spec: ToolSpec, context: AuthorizationContext) -> AuthorizationResult:
    """Revalidate scopes and effect at dispatch time; agents cannot bypass this function."""
    if not spec.required_scopes.issubset(context.granted_scopes):
        return AuthorizationResult(AuthorizationDecision.DENY, "missing_scope")

    if spec.effect == ToolEffect.READ:
        return AuthorizationResult(AuthorizationDecision.ALLOW, "read_only")

    if context.approval_granted:
        return AuthorizationResult(AuthorizationDecision.ALLOW, "approved")

    if spec.effect == ToolEffect.REVERSIBLE_WRITE and (
        context.explicit_user_instruction or context.standing_permission
    ):
        return AuthorizationResult(AuthorizationDecision.ALLOW, "already_authorized")

    # Sending data outside KURO, destructive changes and high-impact operations always
    # require an approval token bound by the application to the exact proposed action.
    if spec.effect in {
        ToolEffect.EXTERNAL_SEND,
        ToolEffect.DESTRUCTIVE,
        ToolEffect.HIGH_IMPACT,
    }:
        return AuthorizationResult(AuthorizationDecision.REQUIRE_APPROVAL, "sensitive_effect")

    return AuthorizationResult(AuthorizationDecision.REQUIRE_APPROVAL, "write_not_authorized")
