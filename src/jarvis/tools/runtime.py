"""Fail-closed dispatcher boundary for registered tools."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from jarvis.tools.contracts import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationResult,
    ToolEffect,
    ToolProposal,
)
from jarvis.tools.policy import authorize_tool
from jarvis.tools.registry import ToolRegistry

ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any]]


class ToolRuntimeError(Exception):
    """Fixed local error codes only; never include tool/provider response bodies."""


class ToolRuntime:
    def __init__(self, registry: ToolRegistry, handlers: Mapping[str, ToolHandler]):
        self.registry = registry
        self.handlers = dict(handlers)
        unknown = set(self.handlers) - set(registry.names())
        if unknown:
            raise ValueError("handler registered for unknown tool")

    def authorize(
        self, proposal: ToolProposal, context: AuthorizationContext
    ) -> AuthorizationResult:
        try:
            spec = self.registry.get(proposal.tool_name)
        except KeyError:
            return AuthorizationResult(AuthorizationDecision.DENY, "unknown_tool")
        if set(proposal.arguments) != set(spec.argument_keys):
            return AuthorizationResult(AuthorizationDecision.DENY, "invalid_arguments")
        return authorize_tool(spec, context)

    async def execute(self, proposal: ToolProposal, context: AuthorizationContext) -> Any:
        decision = self.authorize(proposal, context)
        if decision.decision != AuthorizationDecision.ALLOW:
            raise ToolRuntimeError(decision.reason)
        spec = self.registry.get(proposal.tool_name)
        if spec.effect != ToolEffect.READ:
            raise ToolRuntimeError("durable_journal_required")
        handler = self.handlers.get(spec.name)
        if handler is None:
            raise ToolRuntimeError("handler_unavailable")
        try:
            async with asyncio.timeout(spec.timeout_seconds):
                return await handler(proposal.arguments)
        except TimeoutError:
            raise ToolRuntimeError("tool_timeout") from None
