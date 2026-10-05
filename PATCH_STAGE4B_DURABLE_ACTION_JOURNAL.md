# KURO Stage 4B — Durable Action & Scheduler Journal

Prerequisite: Stage 4A patch applied and the 297-test gate passing.

## What this patch adds

- PostgreSQL migration `0005_tool_actions`.
- Owner-scoped `tool_actions` journal with forced RLS.
- Immutable action payload at the PostgreSQL trigger layer.
- Exact action fingerprint bound to owner + tool + canonical JSON arguments.
- Approval expiry and exact-fingerprint approval binding.
- Scheduled `due_at` queue.
- `FOR UPDATE SKIP LOCKED` claims and 90-second leases.
- Explicit `claimed -> dispatching` boundary.
- Safe recovery: expired pre-dispatch claims requeue up to three attempts; expired post-dispatch work becomes `uncertain` and is never automatically replayed.
- Stale lease rejection.
- Safe audit events containing no tool arguments/provider response bodies.
- Native PostgreSQL integration tests for approval binding, scheduling, lease recovery, payload immutability and owner isolation.

## Deliberately not included yet

No real Calendar/Email credentials, provider calls, LLM tool calling, or autonomous scheduler worker are enabled by this patch. Stage 4B establishes the durable execution boundary before external side effects are connected.

## Validation

Run the authoritative isolated suite:

```powershell
docker compose -f compose.test.yaml up `
  --build `
  --abort-on-container-exit `
  --exit-code-from tests

$testExitCode = $LASTEXITCODE
Write-Output "TEST_EXIT_CODE=$testExitCode"
```

Expected after Stage 4A + 4B: 304 tests collected/passed and exit code 0.

Then:

```powershell
docker compose -f compose.test.yaml down --volumes
```

Do not run production migration until the test gate is green. After it is green, back up PostgreSQL and run the existing production migration command/wrapper, then verify `jarvis doctor` reports ready.
