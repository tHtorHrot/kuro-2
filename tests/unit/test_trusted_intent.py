from uuid import UUID

import pytest

from jarvis.integrations.calendar.agent import calendar_tool_specs
from jarvis.orchestration.trusted_intent import (
    CalendarIntentGateway,
    IntentBindingError,
    IntentKind,
    IntentProposal,
    TrustedIngressEnvelope,
    TrustedIntentBinder,
)
from jarvis.tools.registry import ToolRegistry

OWNER = UUID(int=1)
DIRECTIVE = 'KURO, buat rapat "Review" pada 2026-10-03 jam 10:00 sampai 11:00 zona Asia/Jakarta'
ARGUMENTS = {
    "title": "Review",
    "start": "2026-10-03T10:00:00+07:00",
    "end": "2026-10-03T11:00:00+07:00",
    "timezone": "Asia/Jakarta",
}


def binder():
    return TrustedIntentBinder(
        ToolRegistry(calendar_tool_specs()),
        frozenset({"calendar:read", "calendar:write", "calendar:send"}),
    )


def ingress(text, *, authenticated=True, private=True):
    return TrustedIngressEnvelope(
        owner_id=str(OWNER),
        channel="telegram",
        source_id="telegram:42",
        user_text=text,
        authenticated=authenticated,
        private_channel=private,
    )


def test_read_never_needs_explicit_authority():
    bound = binder().bind(
        ingress("KURO, besok ada jadwal apa?"),
        IntentProposal(
            IntentKind.CALENDAR_LIST,
            {"time_min": "2026-10-03T00:00:00+07:00", "time_max": "2026-10-04T00:00:00+07:00"},
        ),
    )
    assert bound.proposal.tool_name == "calendar_list_events"
    assert bound.context.explicit_user_instruction is False


def test_complete_create_matches_original_text_and_every_argument():
    bound = binder().bind(ingress(DIRECTIVE), IntentProposal(IntentKind.CALENDAR_CREATE, ARGUMENTS))
    assert bound.context.explicit_user_instruction is True


@pytest.mark.parametrize(
    "message",
    [
        "KURO, buat focus time di kalender besok jam 10",
        "KURO, mungkin besok saya perlu jadwal focus time",
        "Jangan buat rapat besok jam 10",
        "Bagaimana cara buat meeting?",
        DIRECTIVE + ". Jangan dilaksanakan.",
    ],
)
def test_incomplete_negated_or_quoted_instruction_cannot_grant_authority(message):
    bound = binder().bind(ingress(message), IntentProposal(IntentKind.CALENDAR_CREATE, ARGUMENTS))
    assert bound.context.explicit_user_instruction is False


def test_planner_cannot_substitute_arguments_of_an_explicit_instruction():
    bound = binder().bind(
        ingress(DIRECTIVE),
        IntentProposal(
            IntentKind.CALENDAR_CREATE,
            {**ARGUMENTS, "title": "Different meeting"},
        ),
    )
    assert bound.context.explicit_user_instruction is False


def test_planner_has_no_authority_field():
    with pytest.raises(TypeError):
        IntentProposal(IntentKind.CALENDAR_CREATE, {}, explicit_user_instruction=True)


def test_invite_is_always_a_proposal_for_sensitive_effect_policy():
    bound = binder().bind(
        ingress("KURO, undang Budi besok jam 10"),
        IntentProposal(
            IntentKind.CALENDAR_INVITE,
            {**ARGUMENTS, "attendees": ["b@example.com"]},
        ),
    )
    assert bound.context.explicit_user_instruction is False
    assert bound.proposal.tool_name == "calendar_create_invite"


def test_generic_delete_does_not_authorize_calendar_delete():
    bound = binder().bind(
        ingress("hapus itu"),
        IntentProposal(
            IntentKind.CALENDAR_DELETE,
            {"event_id": "evt"},
        ),
    )
    assert bound.context.explicit_user_instruction is False


@pytest.mark.parametrize("authenticated,private", [(False, True), (True, False), (False, False)])
def test_untrusted_ingress_is_rejected(authenticated, private):
    with pytest.raises(IntentBindingError, match="untrusted_ingress"):
        binder().bind(
            ingress(DIRECTIVE, authenticated=authenticated, private=private),
            IntentProposal(IntentKind.CALENDAR_CREATE, ARGUMENTS),
        )


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_truthy_non_boolean_is_not_authentication(flag):
    with pytest.raises(ValueError, match="authentication flags"):
        ingress(DIRECTIVE, authenticated=flag)


def test_argument_shape_is_revalidated_against_registry():
    with pytest.raises(IntentBindingError, match="invalid_arguments"):
        binder().bind(
            ingress(DIRECTIVE), IntentProposal(IntentKind.CALENDAR_CREATE, {"title": "x"})
        )


def test_scope_check_cannot_be_skipped_by_service_with_broader_scopes():
    restricted = TrustedIntentBinder(ToolRegistry(calendar_tool_specs()), frozenset())
    with pytest.raises(IntentBindingError, match="missing_scope"):
        restricted.bind(
            ingress("cek kalender"),
            IntentProposal(
                IntentKind.CALENDAR_LIST,
                {"time_min": "a", "time_max": "b"},
            ),
        )


def test_private_ingress_and_proposal_arguments_are_hidden_from_repr():
    assert "PRIVATE-CONTENT" not in repr(ingress("PRIVATE-CONTENT"))
    proposal = IntentProposal(IntentKind.CALENDAR_CREATE, {**ARGUMENTS, "title": "PRIVATE-CONTENT"})
    bound = binder().bind(ingress(DIRECTIVE), proposal)
    assert "PRIVATE-CONTENT" not in repr(proposal)
    assert "PRIVATE-CONTENT" not in repr(bound)


@pytest.mark.asyncio
async def test_gateway_passes_only_bound_authority_to_write():
    class Service:
        owner_id = OWNER

        async def submit_write(self, tool_name, arguments, *, explicit_user_instruction):
            return tool_name, dict(arguments), explicit_user_instruction

    gateway = CalendarIntentGateway(binder(), Service())
    result = await gateway.route(
        ingress(DIRECTIVE), IntentProposal(IntentKind.CALENDAR_CREATE, ARGUMENTS)
    )
    assert result == ("calendar_create_event", ARGUMENTS, True)


@pytest.mark.asyncio
async def test_gateway_routes_read_without_write_journal_path():
    class Service:
        owner_id = OWNER

        async def list_events(self, *, time_min, time_max):
            return time_min, time_max

        async def submit_write(self, *args, **kwargs):
            raise AssertionError("read must not enter write path")

    gateway = CalendarIntentGateway(binder(), Service())
    result = await gateway.route(
        ingress("KURO, cek jadwal kalender"),
        IntentProposal(
            IntentKind.CALENDAR_LIST,
            {"time_min": "a", "time_max": "b"},
        ),
    )
    assert result == ("a", "b")


@pytest.mark.asyncio
async def test_gateway_rejects_service_for_another_owner_before_provider_access():
    class Service:
        owner_id = UUID(int=2)

        async def list_events(self, **kwargs):
            raise AssertionError("cross-owner provider access")

    with pytest.raises(IntentBindingError, match="owner_mismatch"):
        await CalendarIntentGateway(binder(), Service()).route(
            ingress("cek kalender"),
            IntentProposal(IntentKind.CALENDAR_LIST, {"time_min": "a", "time_max": "b"}),
        )
