"""Execution broker for durable tool actions.

The broker accepts only actions claimed from :class:`ActionJournal`.  Agent/model
output cannot call handlers through this boundary directly.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from jarvis.tools.contracts import ToolProposal
from jarvis.tools.journal import ActionJournal, ClaimedAction, action_fingerprint
from jarvis.tools.registry import ToolRegistry

ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any]]
DISPATCH_ACTION_ID: ContextVar[UUID | None] = ContextVar("dispatch_action_id", default=None)


class ExecutionBrokerError(Exception):
    """Stable local error code. Never include arguments or provider output."""


@dataclass(frozen=True)
class ExecutionResult:
    action_id: UUID
    outcome: str
    code: str


class ExecutionBroker:
    """Revalidate and execute one already-authorized durable action.

    Unknown or changed tool definitions fail before ``dispatching``. Once a
    handler may have observed the request, ambiguous failures are recorded as
    ``uncertain`` and are never blindly retried.
    """

    def __init__(
        self,
        journal: ActionJournal,
        registry: ToolRegistry,
        handlers: Mapping[str, ToolHandler],
    ):
        self.journal = journal
        self.registry = registry
        self.handlers = dict(handlers)
        unknown = set(self.handlers) - set(registry.names())
        if unknown:
            raise ValueError("handler registered for unknown tool")

    async def execute_claimed(self, claimed: ClaimedAction) -> ExecutionResult:
        try:
            spec = self.registry.get(claimed.tool_name)
        except KeyError:
            await self.journal.reject_claim(claimed, "tool_definition_changed")
            return ExecutionResult(claimed.id, "failed", "tool_definition_changed")

        if (
            spec.agent != claimed.agent
            or spec.effect.value != claimed.effect
            or set(claimed.arguments) != set(spec.argument_keys)
        ):
            await self.journal.reject_claim(claimed, "tool_definition_changed")
            return ExecutionResult(claimed.id, "failed", "tool_definition_changed")

        proposal = ToolProposal(claimed.tool_name, claimed.arguments)
        fingerprint = (
            action_fingerprint(self.journal.owner, proposal)
            if claimed.fingerprint_version == 1
            else action_fingerprint(
                self.journal.owner,
                proposal,
                version=claimed.fingerprint_version,
                due_at=claimed.due_at,
                due_timezone=claimed.due_timezone,
                latest_dispatch_at=claimed.latest_dispatch_at,
            )
        )
        if fingerprint != claimed.action_fingerprint:
            await self.journal.reject_claim(claimed, "action_changed")
            return ExecutionResult(claimed.id, "failed", "action_changed")

        handler = self.handlers.get(spec.name)
        if handler is None:
            # No external call occurred; terminal failure is safe.
            await self.journal.reject_claim(claimed, "handler_unavailable")
            return ExecutionResult(claimed.id, "failed", "handler_unavailable")

        from jarvis.integrations.calendar.validation import KEYS, validate_arguments

        if spec.name in KEYS:
            try:
                validate_arguments(spec.name, claimed.arguments)
            except ValueError:
                await self.journal.reject_claim(claimed, "invalid_arguments")
                return ExecutionResult(claimed.id, "failed", "invalid_arguments")
        reason = await self.journal.begin_dispatch(claimed)
        if reason:
            return ExecutionResult(claimed.id, "failed", reason)
        token = DISPATCH_ACTION_ID.set(claimed.id)
        try:
            async with asyncio.timeout(spec.timeout_seconds):
                value = await handler(claimed.arguments)
            await self.journal.finish(claimed, outcome="succeeded", result=value)
        except TimeoutError:
            # Handler may have completed remotely after our timeout.
            await self.journal.finish(claimed, outcome="uncertain")
            return ExecutionResult(claimed.id, "uncertain", "tool_timeout")
        except Exception:
            # Generic provider/transport errors are ambiguous at this boundary.
            # Never leak provider details and never blindly retry a write.
            await self.journal.finish(claimed, outcome="uncertain")
            return ExecutionResult(claimed.id, "uncertain", "tool_execution_uncertain")
        finally:
            DISPATCH_ACTION_ID.reset(token)
        return ExecutionResult(claimed.id, "succeeded", "ok")
