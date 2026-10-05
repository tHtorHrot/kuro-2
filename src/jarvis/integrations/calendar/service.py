"""KURO-facing Calendar application service.

Every operation is persisted before it reaches the credential-owning scheduler.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jarvis.integrations.calendar.activation import CalendarActivation
from jarvis.tools.contracts import AuthorizationContext, ToolProposal


@dataclass(frozen=True)
class CalendarCommandResult:
    kind: str
    value: Any


class CalendarService:
    def __init__(self, activation: CalendarActivation, scopes: frozenset[str]):
        self.activation = activation
        self.scopes = scopes

    @property
    def owner_id(self):
        return self.activation.journal.owner

    async def list_events(self, *, time_min: str, time_max: str) -> CalendarCommandResult:
        proposal = ToolProposal(
            "calendar_list_events", {"time_min": time_min, "time_max": time_max}
        )
        context = AuthorizationContext(granted_scopes=self.scopes)
        row = await self.activation.journal.create(proposal, context)
        return CalendarCommandResult(
            "queued", {"action_id": str(row.id), "fingerprint": row.action_fingerprint}
        )

    async def submit_write(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        explicit_user_instruction: bool,
        due_at=None,
        due_timezone="UTC",
        source_key=None,
        request_id=None,
    ) -> CalendarCommandResult:
        proposal = ToolProposal(tool_name, arguments)
        context = AuthorizationContext(
            granted_scopes=self.scopes,
            explicit_user_instruction=explicit_user_instruction,
        )
        row = await self.activation.journal.create(
            proposal,
            context,
            due_at=due_at,
            due_timezone=due_timezone,
            source_key=source_key,
            request_id=request_id,
        )
        # Awaiting approval is intentionally not auto-approved here. UI code must
        # present the exact action and bind approval to row.action_fingerprint.
        return CalendarCommandResult(
            "approval_required" if row.status == "awaiting_approval" else "queued",
            {"action_id": str(row.id), "fingerprint": row.action_fingerprint},
        )
