# Fresh-context whole-branch review

Reviewer: gpt-6-astra (read-only, no delegated reviewers).
Range: fd1da92..2aec00ded5ca8f669f69ca03517e2fb3aec7c843.
Reviewed spec, plan, rulings, runtime code, migrations, Compose, tests and Windows guide.

Critical: none found. Important: remove Ubuntu apt-get from windows-latest CI job.
Minor: none raised. The implementation author independently identified the same CI defect.

Strengths: authoritative PostgreSQL owner/document revalidation; deletion invalidates
requests/snapshots under the owner-state lock; immutable consent/cost integration;
lease/status guards before publishing; parser process and container resource bounds;
binary host upload and child exit-code propagation; additive RLS schema and unchanged
route configuration; explicit differentiation of native and secondary evidence.

Assessment: suitable for a development ZIP after the CI fix, contingent on native
Docker/PostgreSQL and Windows/Telegram gates. No additional concrete release-blocking
issue found in the inspected code. This is not production approval.

Coverage limitation: malformed/expansion/OCR/subprocess extraction tests exist, but
there is no deliberately stalled-parser test directly proving deadline/process-group
termination. Limits are enforced in code and require continued adversarial validation.

Declined to judge / author dispositions:

1. Native PostgreSQL concurrency/advisory-lock recovery/pooling/migration: remains
   native acceptance gate; no claim from WASM or skipped tests.
2. Actual Docker startup/ownership/image/resource behavior: mandatory Windows guide gate.
3. Actual PowerShell/Docker byte streaming: implementation and mock boundary tests checked;
   Windows CI and local upload acceptance still required.
4. Live Telegram and Ling/Novita: no real send or inference performed; user runs fixtures.
5. Real-document retrieval quality/entailment: no general quality claim from synthetic test;
   four-chunk context and label-only citation checks disclosed.
6. Backup/restore, ACL/encryption/capacity: production operational gate; original source
   files retained and DB-only backup limitation documented.
7. ZIP contents/manifests/checksum: verified separately during packaging, outside code review.

Fix pass: CI platform check observed RED with Linux apt-get in Windows job. Removed the
single step, retained Ubuntu OCR setup, observed GREEN. No implementation-mirroring unit
test added for this reversible workflow edit; full suite rerun after fix.
Final suite with native Qdrant enabled: **229 passed, 53 skipped**, exit 0.
Only unavailable native PostgreSQL tests remain skipped. Ruff lint/format pass.
No second review dispatched. No deferred minor findings.
