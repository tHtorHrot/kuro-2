# Stage 4F — Trusted Intent Routing

Stage 4F separates semantic planning from authorization.

## Boundary

- `TrustedIngressEnvelope` is created only after channel authentication/pairing and private-channel checks.
- `IntentProposal` is untrusted and intentionally has no authorization field.
- `TrustedIntentBinder` maps a bounded intent to a registered Calendar tool and revalidates exact argument keys.
- `explicit_user_instruction` is derived conservatively from the original authenticated user text, never from planner/LLM output.
- Hedged language (`mungkin`, `maybe`, etc.) cannot authorize a write.
- External-send/destructive effects remain approval-gated by the Stage 4A policy even when the request is explicit.
- `CalendarIntentGateway` binds before handing off to `CalendarService`; reads return directly, writes remain journal-first.

## Deliberate non-goal

This patch does not yet give the Telegram container Calendar OAuth secrets and does not let free-form Telegram text execute tools. The next activation slice can connect the existing paired/private Telegram ingress to this boundary without moving provider credentials into the chat-facing process.
