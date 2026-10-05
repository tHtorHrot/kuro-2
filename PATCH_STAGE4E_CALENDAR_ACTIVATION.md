# KURO Stage 4E — Calendar OAuth & Activation Boundary

Adds the production credential boundary and composition layer for the Stage 4D Calendar specialist.

## Added
- Google OAuth refresh-token provider with in-memory access-token cache.
- Deployment-only secret loader (`*_FILE` compatible).
- Closed Calendar activation factory wiring registry, agent, runtime, journal, broker and scheduler.
- KURO-facing CalendarService: read-only direct results; all writes durable-first.
- Opt-in `compose.calendar.yaml` mounting three Google credentials as Docker secrets.
- Activation/security documentation and regression tests.

## Important invariant
Natural-language text is not treated as authorization. Interface routing may propose a tool later, but trusted KURO Core supplies `explicit_user_instruction` and approvals. Credentials are never tool arguments.

## No migration
Stage 4E reuses migration `0005_tool_actions`.
