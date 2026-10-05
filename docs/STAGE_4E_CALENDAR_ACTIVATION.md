# Stage 4E — Google Calendar activation

Stage 4E wires the validated Calendar specialist to a Google OAuth refresh-token boundary.

## Security model

- Keep `client_id`, `client_secret`, and `refresh_token` in `.secrets/`; never commit them.
- Compose mounts them read-only under `/run/secrets`.
- OAuth refresh is not a registered KURO tool. Agents cannot request or inspect tokens.
- Access tokens are cached only in process memory and refreshed five minutes early.
- OAuth and Calendar HTTP origins are fixed; redirects are disabled by owned clients.
- Remote error bodies are never propagated into tool errors/logs.
- Calendar reads and writes are queued for the credential-owning scheduler.
- Every Calendar write is first persisted in the durable action journal. External-send and destructive effects remain approval-gated.

## Secret files

Create these local files (one value per file):

- `.secrets/google_client_id`
- `.secrets/google_client_secret`
- `.secrets/google_refresh_token`

Obtain the values through your own Google Cloud OAuth consent/client flow. Request only the Calendar scope needed by this installation. Do not paste these values into chat, source files, `.env`, or command history.

The opt-in overlay is `compose.calendar.yaml`. It adds the `scheduler` service;
Google secrets are mounted there, not into `assistant` or `telegram`.
A bounded conversational route is implemented in Stage 4G; its final native acceptance is still open.
See the current open gates in `STAGE_4_VERIFICATION.md` before enabling it.

## Deliberate boundary

This slice activates provider credentials and the KURO-facing Calendar application service. Free-form Telegram language is not parsed inside the credential-bearing provider process. The Stage 4G interface translates a bounded grammar into a normalized `ToolProposal`, while authorization remains trusted KURO Core state. This prevents an LLM-generated phrase from becoming an authorization token.

Current grant, health, testing and recovery procedure: `STAGE_4G_CALENDAR_CHAT.md`.
