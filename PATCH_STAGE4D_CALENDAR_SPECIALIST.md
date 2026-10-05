# KURO Stage 4D — Calendar Reference Specialist

Adds the first provider-backed specialist on top of the Stage 4 controlled tool runtime.

## Capabilities
- `calendar_list_events`: read-only, no redundant confirmation.
- `calendar_create_event`: solo reversible write; explicit user instruction can execute directly.
- `calendar_create_invite`: external send; exact-action approval required.
- `calendar_update_event`: reversible write; explicit user instruction can execute directly.
- `calendar_delete_event`: destructive; approval required.

## Security boundaries
- Low-risk create cannot accept attendee arguments; invite is a separate tool/effect.
- Agent owns capabilities but never authorization.
- Google origin is fixed to `https://www.googleapis.com/calendar/v3`.
- OAuth access token is injected by a trusted token provider; it is never an action argument.
- Redirects are disabled for the owned HTTP client.
- Provider error bodies are not propagated.
- CI/unit tests use fake providers and never touch a real calendar.

## Deliberately not included yet
OAuth refresh-token persistence/deployment wiring and Telegram natural-language routing. Those belong to the next integration slice so credentials are not introduced before the provider/tool boundary is validated.
