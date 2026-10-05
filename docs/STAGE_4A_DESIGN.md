# Stage 4A — Agent and Tool Runtime Foundation

Stage 4A extends the Stage 4 roadmap without replacing the existing assistant journal or
LangGraph workflow. KURO remains the user-facing supervisor and authority. Specialist agents
are internal workers; they may propose tool calls but cannot grant scopes, mark a user request
as explicit, approve sensitive effects, register arbitrary tools, or execute shell/SQL.

## UX and authorization invariant

Security uses minimum necessary friction. A scoped read is allowed without confirmation.
A reversible low-impact write may run without a second confirmation only when trusted KURO
Core records that the current user instruction explicitly requested that action, or an existing
standing permission covers it. External sends, destructive operations and high-impact actions
require approval bound by the application to the proposed action. Missing scopes always deny.
Agent-to-agent delegation alone never creates a user confirmation.

`AuthorizationContext` is therefore trusted application state, not model output. Tool proposals
contain only a registered tool name and arguments. `ToolRuntime` resolves the closed registry,
checks exact argument keys, re-runs authorization immediately before dispatch, applies a bounded
timeout and fails closed when a handler is unavailable.

## Registry invariant

Every tool declares an owner agent, required scopes, effect class, timeout, network hostname
allowlist, idempotency property and accepted argument keys. URLs are not accepted as network
allowlist entries. Dynamic tool installation is out of scope. An `AgentRegistry` prevents a
specialist from claiming tools owned by another specialist.

## Intentionally not in 4A

4A does not yet expose tools to the LLM and does not change the Stage 3 system prompt. It does
not create calendar/email credentials, make external requests, or add autonomous loops. The
next slice adds the durable PostgreSQL action/job journal and approval binding before the first
real connector is enabled. This ordering keeps Stage 3 behavior unchanged while the new
security boundary is tested independently.
