# SDD ledger — plan: docs/superpowers/plans/2026-09-30-knowledge.md

User authorized building and delivering the ZIP twice after agreeing mixed PDF/DOCX/OCR scope and upgrade mechanism. Execute inline through packaging; no repeated implementation authorization needed. Archive baseline copied into isolated development directory, original preserved. Native Docker/PostgreSQL binaries initially unavailable; Tesseract and Poppler present.

Pre-flight: Task 1 Segment/Chunk feeds Task 2 stored chunks; Task 2 sources feeds Task 3 immutable assistant snapshot; Task 4 packages all. Interfaces match. Existing parser middleware 64 KiB API body limit is preserved by using trusted operator stdin upload instead of modifying the public API boundary.


## Implementation and verification record — 2026-10-01

Task 1: implementation complete. Parser/content tests first failed for absent modules,
then 14 passed including real OCR; after service tests, 20 passed. Recovery rerun also
passed those 20. Unicode citation-tail regression observed RED (did not raise), then
GREEN (9 content tests). Combined result now rejects a reply before Telegram can
truncate authoritative sources.

Task 2: implementation complete with native DB acceptance pending. Service boundaries
were observed RED before implementation and GREEN afterward. Malformed Qdrant responses,
parser error allowlist and tampered pinned model are covered. Native Qdrant 1.19.1
roundtrip passed (1 test) against a local process: owner/document filters, upsert and
scoped deletion. Initial separate-process invocation could not connect; launching the
server and test in the same executor invocation resolved the environment issue.
PGlite/PostgreSQL 18.3 WASM secondary schema/RLS/FK/delete checks: 72 passed.
Real pinned multilingual model download/checksum and offline embedding smoke passed;
3 vectors x 384, synthetic related similarity .6006 vs unrelated .0642.

Task 3: implementation complete with native DB acceptance pending. Twelve knowledge
integration cases are written; PostgreSQL unavailable here so those tests are skipped,
not claimed passing. Existing unit regressions pass. Document commands, immutable
snapshot, restricted/no-source rejection, deletion and cost ledger integrate with 2B.

Task 4: implementation complete pending one final review and packaging. Four host upload
wrapper tests observed RED for missing script, then GREEN; byte preservation and child
exit code propagation covered. Compose isolation static test passed. Windows guide and
native upgrade gate preserve existing owner/config/pairing. Full local suite:
228 passed, 54 skipped (53 native PostgreSQL, 1 Qdrant in default run); Qdrant separately
passed. Ruff lint and format pass; uv frozen sync and wheel build pass; model_manifest.json
and worker present in wheel. No real cloud inference, Telegram send, or production
migration was performed.

Ruling: Recovery uses one consolidated implementation commit from baseline fd1da92,
rather than per-task commits — execution filesystem rollback lost earlier transient
changes, which were reconstructed and retested — cost if wrong: less granular history,
not a replacement for review or native acceptance.

Ruling: Native PostgreSQL/Docker verification is an explicit installation gate rather
than a claimed local pass — those services cannot run in this execution environment;
WASM checks are supplementary only — cost if wrong: deployment/migration defects can
still be found by the owner's isolated test gate, which must pass before migration.

Ruling: Restricted documents are stored/indexed locally and blocked from /askdoc;
a user-facing local text search is deferred — source spec described local search but
this package exposes no local search UI and the guide says so — cost if wrong: owners
needing restricted answers must wait for a dedicated local interface.

Ruling: Use binary stdin from a trusted local operator, as specified, for upload — keeps
original files out of Telegram and avoids changing the public API upload boundary —
cost if wrong: importing requires access to the computer/Docker CLI.


## Final review and fix pass

Fresh-context whole-branch reviewer gpt-6-astra reviewed fd1da92..2aec00d read-only.
No critical findings and no deferred minors; one Important finding: Linux apt-get in
Windows CI. Re-grade: Important confirmed because the Windows gate otherwise never runs.
Final: fixed Windows CI platform command — one-off command compatibility check RED→GREEN,
Ubuntu OCR dependencies retained; full suite 229 passed/53 native PG skipped with real
Qdrant enabled. Ruff lint/format passed. Direct deliberately-stalled-parser termination
is not covered by a test; coverage limitation disclosed in review.md.

Final: Ruling: Native PostgreSQL concurrency, lock recovery, pooling and populated
migration execution — remain mandatory native gate before owner DB migration, not
inferred from supplementary WASM — cost if wrong: a native-only defect delays install.
Final: Ruling: Docker startup, volume ownership, image behavior and resource consumption
— retain explicit runtime checks in Windows guide — cost if wrong: deployment may require
an environment fix; current DB backup must be retained.
Final: Ruling: Actual PowerShell/Docker streaming — retain binary-handle tests plus Windows
CI and owner's upload check — cost if wrong: Windows-specific execution could block import.
Final: Ruling: Live Telegram/Ling inference — do not use real accounts from this workspace;
manual fixtures remain acceptance gate — cost if wrong: real provider or bot behavior may
need follow-up after installation despite isolated tests.
Final: Ruling: Retrieval quality and citation entailment — disclose four-chunk scope and
label-only validation; no benchmark claim — cost if wrong: users could trust an incomplete
or mistaken answer without checking the displayed sources.
Final: Ruling: Production backup/restore/ACL/encryption/capacity — keep as operational gate,
with DB-only backup warning and source retention — cost if wrong: treating the development
package as production-ready risks unrecoverable document data.
Final: Ruling: ZIP exclusion and checksum verification — perform independently at packaging
rather than treat code review as artifact review — cost if wrong: archive may contain wrong
files; packaging asserts entry inventory, paths, CRC and every manifest hash.

Completion choice: user explicitly selected an extract-and-merge ZIP; keep local branch
without remote push/merge and deliver archive. No new integration permission question.


## OCR hotfix 1 — owner native gate feedback

Owner reports 281 passed, 1 failed (real OCR fixture), exit 1. Full traceback was not
provided and container logs were removed by compose down. Source investigation and
Debian Bookworm package metadata establish a packaging defect: language data only
recommend the CLI, which --no-install-recommends omits in both test/parser images.
One-off dependency check observed RED on original Dockerfile, GREEN after adding
explicit tesseract-ocr to both stages and Ubuntu CI. Added build-time executable and
eng+ind assertions so a malformed image fails during build. Existing extraction suite
ran with real host OCR: 6 passed in 0.79s. Docker build/native gate after this hotfix is
pending owner rerun, not claimed passed. No new Python functionality or migration.
Guide now documents backup after file merge but before migration, and saving logs
before down. Delta ZIP will be checked by merging over the original delivered archive
and verifying every resulting manifest hash.
