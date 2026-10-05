# Stage 4C — Execution Broker + Scheduler Engine

This patch extends the validated Stage 4B durable action journal. It does not add provider credentials or activate a new Compose daemon.

## Security semantics

- Only a `ClaimedAction` issued by the PostgreSQL-backed journal reaches the execution broker.
- Agent/model proposals cannot invoke handlers through the broker directly.
- Broker revalidates agent ownership, effect class, argument schema, and owner-bound action fingerprint against the current closed registry before dispatch.
- Registry drift or a missing handler fails while the action is still `claimed`; no external call is made.
- `begin_dispatch` is persisted before invoking a handler.
- Timeout or unexpected provider/transport exceptions after dispatch are `uncertain`, not automatically retried.
- Scheduler runs bounded passes and performs expired-lease recovery before claiming new work.

## Deployment scope

No always-on scheduler service is enabled yet. The engine is intentionally kept library-level until the first real reference tool exists; this avoids a privileged idle daemon and lets Stage 4D prove the boundary with a concrete integration.

## Validation

Added 7 unit tests. Expected full Docker suite after Stage 4B: **311 passed**.
