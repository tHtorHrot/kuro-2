# Stage 4 — Tools and Scheduling verification

Stage 4 is **not yet complete**. Docker regression and migration to
`0008_executor_binding` are necessary but insufficient. The product gates in
`STAGE_4_8_ACCEPTANCE.md` must also pass on the exact release being considered.
The current Stage 4G candidate has the evidence listed in
`../DEVELOPMENT_STATUS.md`; no full Docker or real-provider pass is claimed.

Calendar activation commands below are operator reference for a later accepted
build. Do not use them as a shortcut around the open authorization, result-delivery
and recovery gates described in `AUDIT_KURO_2026-10-02.md`.

## Security invariants
- Tool and agent registries are closed; model output only proposes a registered tool and exact arguments.
- Trusted ingress, not an LLM/sub-agent, supplies authorization context.
- External-send/destructive/high-impact actions require approval bound to the immutable action fingerprint.
- PostgreSQL is authoritative for queue state; RLS is enabled and forced.
- `claimed` may recover before dispatch; a crash/failure after `dispatching` becomes `uncertain` and is never blindly retried.
- Scheduled actions persist both UTC `due_at` and the validated IANA source timezone.
- Google OAuth secrets are mounted only into the scheduler execution boundary. They are not tools, prompts, action payloads, or audit metadata.
- Google provider uses a fixed HTTPS API origin; no caller-controlled network target exists.

## Authoritative gate

```powershell
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
$testExitCode = $LASTEXITCODE
Write-Output "TEST_EXIT_CODE=$testExitCode"
docker compose -f compose.test.yaml down --volumes
```

Expected: all tests pass and exit code is 0.

## Production migration

```powershell
docker compose -f compose.yaml -f compose.assistant.yaml -f compose.knowledge.yaml build
docker compose -f compose.yaml -f compose.assistant.yaml -f compose.knowledge.yaml run --rm migrate alembic heads
docker compose -f compose.yaml -f compose.assistant.yaml -f compose.knowledge.yaml run --rm migrate
docker compose -f compose.yaml -f compose.assistant.yaml -f compose.knowledge.yaml run --rm migrate alembic current
docker compose -f compose.yaml -f compose.assistant.yaml -f compose.knowledge.yaml run --rm api jarvis doctor
```

Expected head/current: `0008_executor_binding`; doctor reports stage 4 and forced RLS.

## Calendar activation
For the complete grant/activation procedure, use `STAGE_4G_CALENDAR_CHAT.md`.
An explicit persisted grant is now required; starting the scheduler alone grants no access.
Create these local secret files (never commit them): `.secrets/google_client_id`, `.secrets/google_client_secret`, `.secrets/google_refresh_token`. Set `JARVIS_OWNER_ID` to the UUID printed when the owner was created. Start the scheduler only after credentials are provisioned:

```powershell
$env:JARVIS_OWNER_ID = '<owner UUID>'
docker compose -f compose.yaml -f compose.calendar.yaml up -d scheduler
docker compose -f compose.yaml -f compose.calendar.yaml run --rm scheduler scheduler-once --owner-id $env:JARVIS_OWNER_ID
```

Operator approval/cancel does not require Google credentials:

```powershell
docker compose -f compose.yaml run --rm api jarvis tools-status --owner-id <owner UUID>
docker compose -f compose.yaml run --rm api jarvis tools-approve --owner-id <owner UUID> --action-id <UUID> --fingerprint <SHA256>
docker compose -f compose.yaml run --rm api jarvis tools-cancel --owner-id <owner UUID> --action-id <UUID>
```

Do not auto-retry `uncertain` actions. Reconcile against the external provider first.
