# Rollout KURO Ultimate — schema 0014 (9 Okt 2026)

## Diterapkan
- Phase 1–4 MD sebagai evolusi additive di `kuro-main` (tanpa rewrite):
  `tasks`, `task_dependencies`, `task_runs`, `artifacts`, `task_events` (0010),
  `task_run_id` di `tool_actions`/`llm_calls` (0011), automation defs/runs (0012),
  grant sequence `task_events_id_seq` (0013),
  grant DELETE khusus event log turunan (0014).
- Kontrak, planner tervalidasi, Task Manager idempotent, Agent Manager (maks 2
  worker), capability HMAC, workspace/sandbox profiles, artifact + evaluator,
  memory tervalidasi, retrieval bertahap, routing policy, monitoring tasks.
- API `POST/GET /api/v1/tasks`, event feed polling/SSE, Telegram
  `/goal`/`/tasks`/`/task`, CLI `tasks-run-once` (intake jujur: record +
  provenance, bukan klaim hasil).

## Verifikasi
- Gate native hijau: 591 passed, 0 failed, schema `0014_task_event_retention`.
- Produksi: backup terenkripsi 425 MB (exit 0), migrasi 0009→0014,
  semua service image baru healthy, API `ready`.
- End-to-end: `/goal` → task tersimpan → receipt `sent` → `/tasks` daftar →
  `/task` status → `tasks-run-once` → `succeeded` + artifact.
- Restore drill terisolasi hijau: counts identik pre/post quarantine,
  tanpa executor/transports.

## Bug produksi yang ditemukan malam rollout
1. `0010` lupa `GRANT USAGE` ke `task_events_id_seq` → worker Telegram
   crash-loop pada `/goal` pertama. Fix forward-only: `0013`.
2. Helper `_reply` Telegram tidak set `delivery_status=pending` → task
   terbentuk tapi sunyi. Fix: delegasi ke `set_reply` asli.
3. Pelajaran: pin cert = hash FILE (`Get-FileHash`), bukan hash DER;
   `COMPOSE_PROFILES` wajib aktif untuk backup; `up migrate` tanpa
   `--force-recreate` memakai container lama.

## Belum dikerjakan
- Retrieval drill PENUH (query live): clone sudah terbukti byte-level —
  DB 0013 + 1 dokumen/6 chunks cocok produksi, koleksi Qdrant
  `jarvis_knowledge_v1` dan model embedding ada di volume. Query live
  (load model + search) belum dijalankan; butuh harness Qdrant di clone.
- Sandbox live HIJAU (image `kuro-sandbox:stable`, stage Dockerfile):
  komputasi OK, network default-deny, tulis di luar `/work` ditolak,
  tanpa secret, timeout kill terbukti. Tinggal wiring Coding/Data worker.
- Phase 4 wiring: memory/episodic dan routing model masih modul, belum
  dipakai alur assistant.
- 6 task duplikat percobaan sudah di-cancel (`operator_cleanup_dupes`).

## Worker intake otomatis (aktif)
- `tasks-loop` + service `task-worker` (profile `tasks`,
  `compose.tasks.yaml`): klaim task planner/research/knowledge → intake
  record → succeeded, tiap 30 dtk. Terverifikasi memproses otomatis di
  produksi.
- Phase 4 slice 1 LIVE: intake sukses → fakta memory `task:<id>`
  berprovenance, terlihat di `/memory`. Tanpa LLM call, tanpa sentuh
  jalur chat.
- Automation recurring LIVE (subset DAILY/WEEKLY stdlib, tanpa dep baru):
  `automation-create` + `automation-tick` → task terjadwal → worker →
  succeeded. `automation-ticker` service terjadwal tiap 5 menit, idempotent
  via occurrence_key.
- Planner LLM TERBUKTI live (route free, model apodex via novita):
  proposal → REJECTED depth → prompt diperbaiki → masih ditolak →
  repair 1x dengan kode error → ACCEPTED 5 task. Validator sebagai gerbang
  terbukti menangkap pelanggaran beneran.
- Auto-plan LIVE: `tasks-plan-auto` memanggil model beneran (ledger
  task-owned, free-only, 1 repair) → 4 subtasks dari 1 root dalam 1
  attempt; intake worker menindaklanjuti otomatis.

## Aturan operasi yang ditegakkan malam ini
- Kredensial/secret: operator yang menjalankan, tidak ditempel di chat.
- Migrasi produksi hanya setelah backup hijau + approval eksplisit.
- Forward-only: tidak ada downgrade, tidak ada edit migrasi terapan.
