# Decision Log — KURO Ultimate (evolutionary)

Keputusan arsitektur dari audit: **evolve KURO; adopsi reliability primitives
AO; pertahankan personal authority dan knowledge KURO; bangun workforce
secara bounded.**

## 0001 — Modular monolith, bukan microservice
- Satu codebase Python, satu PostgreSQL authoritative, bounded workers.
- LangGraph existing tetap untuk alur lokal, bukan dependency wajib tiap komponen.
- Tanpa rewrite Go, migrasi SQLite, Kubernetes, atau message broker pada fase awal.

## 0002 — Lima tabel task dulu
- `tasks`, `task_dependencies`, `task_runs`, `artifacts`, `task_events`
  (0010). Root task memuat goal + `plan_json`/`plan_revision`.
- `task_run_id` nullable pada `tool_actions`/`llm_calls` (0011); LLM call
  milik chat request ATAU task run, tanpa fake Telegram request.
- Automation definitions/runs opsional (0012) setelah one-shot stabil.

## 0003 — Authority terpisah dari model
- `ToolProposal` tidak membawa hak akses; broker menentukan principal dari
  capability, bukan `owner_id` kiriman worker.
- Worker scopes = irisan user grant, task grant, role allowlist, tool reqs.
- Approval exact fingerprint + TTL + grant/spec/config revision.

## 0004 — Guardrails awal (tuning, bukan benchmark)
- Maks 20 task/plan, depth 2, 2 worker aktif, 1 repair pass default.
- Agent tidak boleh mengubah limitnya sendiri.

## 0005 — Sandbox sebelum arbitrary code
- Tiga kelas: trusted read (in-process), credentialed side-effect (journal),
  untrusted code (sandbox default-deny network, nonroot, read-only rootfs).
- Worktree != sandbox; `network_targets` tanpa enforcement bukan firewall.
- Launcher menerima image/profile operator, bukan argumen Docker dari model.

## 0006 — Event dan recovery tanpa overengineering
- `task_events` satu transaksi dengan state; polling cursor untuk satu-host.
- Satu task-state writer awal agar cursor monoton; snapshot bila offline lama.
- `uncertain` tidak masuk automatic retry; butuh reconcile/operator.

## 0007 — Evaluasi sebelum klaim selesai
- Deterministik dulu (build/tests/schema/numeric/citation/fingerprint),
  model/human review hanya untuk yang material.
- Succeeded wajib artifact committed + checks passed.
