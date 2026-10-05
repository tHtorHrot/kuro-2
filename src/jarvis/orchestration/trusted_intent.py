"""Trusted intent binding for KURO Core.

The planner/LLM may propose an intent and arguments, but it cannot assert that a
user authorized an action. Authority is derived from authenticated ingress plus
conservative checks over the original user-authored text.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from jarvis.core.calendar_directive import matches_solo_create
from jarvis.tools.contracts import AuthorizationContext, ToolProposal
from jarvis.tools.registry import ToolRegistry


class IntentBindingError(Exception):
    """Stable local routing error; never contains user text or tool arguments."""


class IntentKind(StrEnum):
    CALENDAR_LIST = "calendar_list"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_INVITE = "calendar_invite"
    CALENDAR_UPDATE = "calendar_update"
    CALENDAR_DELETE = "calendar_delete"


@dataclass(frozen=True)
class TrustedIngressEnvelope:
    """Created only after channel authentication/pairing checks succeed."""

    owner_id: str
    channel: str
    source_id: str
    user_text: str = field(repr=False)
    authenticated: bool
    private_channel: bool

    def __post_init__(self):
        if (
            not isinstance(self.owner_id, str)
            or not isinstance(self.source_id, str)
            or not 1 <= len(self.source_id) <= 200
        ):
            raise ValueError("invalid ingress identity")
        try:
            UUID(self.owner_id)
        except ValueError:
            raise ValueError("invalid ingress identity") from None
        if self.channel not in {"telegram", "local"}:
            raise ValueError("unsupported ingress channel")
        if (
            not isinstance(self.user_text, str)
            or not 1 <= len(self.user_text) <= 4096
            or not self.user_text.strip()
        ):
            raise ValueError("invalid ingress text")
        if type(self.authenticated) is not bool or type(self.private_channel) is not bool:
            raise ValueError("invalid ingress authentication flags")


@dataclass(frozen=True)
class IntentProposal:
    """Untrusted semantic proposal. Deliberately contains no authorization flag."""

    kind: IntentKind
    arguments: Mapping[str, Any] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


_INTENT_TO_TOOL = {
    IntentKind.CALENDAR_LIST: "calendar_list_events",
    IntentKind.CALENDAR_CREATE: "calendar_create_event",
    IntentKind.CALENDAR_INVITE: "calendar_create_invite",
    IntentKind.CALENDAR_UPDATE: "calendar_update_event",
    IntentKind.CALENDAR_DELETE: "calendar_delete_event",
}


@dataclass(frozen=True)
class BoundIntent:
    proposal: ToolProposal
    context: AuthorizationContext


class TrustedIntentBinder:
    """Bind an untrusted planner proposal to authority from trusted ingress."""

    def __init__(self, registry: ToolRegistry, granted_scopes: frozenset[str]):
        self.registry = registry
        self.granted_scopes = granted_scopes

    def bind(self, ingress: TrustedIngressEnvelope, intent: IntentProposal) -> BoundIntent:
        if ingress.authenticated is not True or ingress.private_channel is not True:
            raise IntentBindingError("untrusted_ingress")
        tool_name = _INTENT_TO_TOOL.get(intent.kind)
        if tool_name is None:
            raise IntentBindingError("unsupported_intent")
        try:
            spec = self.registry.get(tool_name)
        except KeyError:
            raise IntentBindingError("tool_unavailable") from None
        if spec.agent != "calendar":
            raise IntentBindingError("agent_mismatch")
        if set(intent.arguments) != set(spec.argument_keys):
            raise IntentBindingError("invalid_arguments")
        if not spec.required_scopes.issubset(self.granted_scopes):
            raise IntentBindingError("missing_scope")
        context = AuthorizationContext(
            granted_scopes=self.granted_scopes,
            explicit_user_instruction=(
                intent.kind == IntentKind.CALENDAR_CREATE
                and matches_solo_create(ingress.user_text, intent.arguments)
            ),
        )
        return BoundIntent(ToolProposal(tool_name, intent.arguments), context)


class CalendarIntentGateway:
    """KURO Core handoff: bind first, then invoke the bounded Calendar service."""

    def __init__(self, binder: TrustedIntentBinder, calendar_service):
        self.binder = binder
        self.calendar_service = calendar_service

    async def route(self, ingress: TrustedIngressEnvelope, intent: IntentProposal):
        if UUID(ingress.owner_id) != self.calendar_service.owner_id:
            raise IntentBindingError("owner_mismatch")
        bound = self.binder.bind(ingress, intent)
        if bound.proposal.tool_name == "calendar_list_events":
            return await self.calendar_service.list_events(
                time_min=str(bound.proposal.arguments["time_min"]),
                time_max=str(bound.proposal.arguments["time_max"]),
            )
        return await self.calendar_service.submit_write(
            bound.proposal.tool_name,
            bound.proposal.arguments,
            explicit_user_instruction=bound.context.explicit_user_instruction,
        )
