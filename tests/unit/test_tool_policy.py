from jarvis.tools import (
    AuthorizationContext,
    AuthorizationDecision,
    ToolEffect,
    ToolSpec,
    authorize_tool,
)


def spec(effect):
    return ToolSpec(
        "calendar_change",
        "Change a calendar event",
        "calendar",
        frozenset({"calendar:write"}),
        effect,
    )


def test_read_only_has_no_confirmation_when_scope_is_present():
    read = ToolSpec(
        "calendar_read",
        "Read calendar",
        "calendar",
        frozenset({"calendar:read"}),
        ToolEffect.READ,
    )
    result = authorize_tool(read, AuthorizationContext(frozenset({"calendar:read"})))
    assert result.decision == AuthorizationDecision.ALLOW


def test_explicit_low_risk_write_does_not_double_confirm():
    context = AuthorizationContext(frozenset({"calendar:write"}), explicit_user_instruction=True)
    result = authorize_tool(spec(ToolEffect.REVERSIBLE_WRITE), context)
    assert result.decision == AuthorizationDecision.ALLOW
    assert result.reason == "already_authorized"


def test_implicit_write_requires_approval_and_missing_scope_denies():
    implicit = authorize_tool(
        spec(ToolEffect.REVERSIBLE_WRITE),
        AuthorizationContext(frozenset({"calendar:write"})),
    )
    missing = authorize_tool(
        spec(ToolEffect.REVERSIBLE_WRITE),
        AuthorizationContext(frozenset(), explicit_user_instruction=True),
    )
    assert implicit.decision == AuthorizationDecision.REQUIRE_APPROVAL
    assert missing.decision == AuthorizationDecision.DENY


def test_sensitive_effect_still_requires_approval_even_when_instruction_is_explicit():
    effects = (ToolEffect.EXTERNAL_SEND, ToolEffect.DESTRUCTIVE, ToolEffect.HIGH_IMPACT)
    for effect in effects:
        context = AuthorizationContext(
            frozenset({"calendar:write"}), explicit_user_instruction=True
        )
        result = authorize_tool(spec(effect), context)
        assert result.decision == AuthorizationDecision.REQUIRE_APPROVAL
        approved = authorize_tool(
            spec(effect),
            AuthorizationContext(frozenset({"calendar:write"}), approval_granted=True),
        )
        assert approved.decision == AuthorizationDecision.ALLOW
