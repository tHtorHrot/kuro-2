# KURO Stage 4A patch

Overlay this archive into the repository root. This slice only adds new files; it does not
modify Stage 3 behavior, migrations, compose files, prompts, credentials, or external services.

Added:
- `src/jarvis/tools/`: closed registry, effect/risk contracts, authorization policy, dispatcher.
- `src/jarvis/agents/`: specialist-agent registry with tool ownership enforcement.
- four targeted unit-test files (9 tests).
- `docs/STAGE_4A_DESIGN.md`.

Validation performed in the build sandbox:
- targeted tests: 9 passed.
- Python compileall: passed.
- line-length static check for added Python files: passed.
- full baseline suite could not be collected in the sandbox because `langgraph` is not installed
  there. Run the repository's Docker test gate on the real project before acceptance.

Stage 4A intentionally does not expose tools to the LLM. Stage 4B should add the durable
PostgreSQL action/job journal, exact-action approval binding, lease/claim/retry/cancel semantics,
and RLS before enabling a real external connector.
