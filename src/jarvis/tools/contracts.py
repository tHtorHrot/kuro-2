"""Typed contracts for Stage 4 tool execution. No model-owned authorization state."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ToolEffect(StrEnum):
    READ = "read"
    REVERSIBLE_WRITE = "reversible_write"
    EXTERNAL_SEND = "external_send"
    DESTRUCTIVE = "destructive"
    HIGH_IMPACT = "high_impact"


class AuthorizationDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    agent: str
    required_scopes: frozenset[str]
    effect: ToolEffect
    timeout_seconds: int = 30
    network_targets: tuple[str, ...] = ()
    idempotent: bool = False
    argument_keys: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self):
        if not self.name or len(self.name) > 80 or not self.name.replace("_", "").isalnum():
            raise ValueError("invalid tool name")
        if not self.agent or len(self.agent) > 80:
            raise ValueError("invalid agent name")
        if not self.description or len(self.description) > 240:
            raise ValueError("invalid tool description")
        if not 1 <= self.timeout_seconds <= 120:
            raise ValueError("tool timeout must be 1..120 seconds")
        if not self.required_scopes:
            raise ValueError("tool requires at least one scope")
        if any(not scope or len(scope) > 80 for scope in self.required_scopes):
            raise ValueError("invalid tool scope")
        if any(
            not target or len(target) > 255 or "://" in target for target in self.network_targets
        ):
            raise ValueError("network targets must be hostnames, not URLs")


@dataclass(frozen=True)
class ToolProposal:
    """Untrusted proposal. An agent may create this, but it carries no authority."""

    tool_name: str
    arguments: Mapping[str, Any] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True)
class AuthorizationContext:
    """Trusted context created by KURO Core, never by a specialist agent or tool output."""

    granted_scopes: frozenset[str]
    explicit_user_instruction: bool = False
    standing_permission: bool = False
    approval_granted: bool = False


@dataclass(frozen=True)
class AuthorizationResult:
    decision: AuthorizationDecision
    reason: str
