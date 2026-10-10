# Matriks kerja kandidat — satu snapshot kondisi, bukti dan langkah berikut

Klasifikasi: IMPLEMENTED (source), TESTED_LOCAL (offline/host test), TESTED_INTEGRATION (native PG), USER_REPORTED (penerimaan lama), BLOCKED/NOT_RUN. Snapshot ini tidak menandai freeze.

| Item | Kondisi baseline → kandidat | Bukti aktual / acceptance | File terdampak / dependency | Langkah berikut |
|---|---|---|---|---|
| Read/agenda/write acceptance lama | Existing → preserved | USER_REPORTED; log 444 historis tersedia, hash revisi unknown | user-acceptance.json; formatter/provider existing | Jangan ulang setup/smoke lama |
| Clarification | HELP terminal → durable slots/task | IMPLEMENTED + TESTED_LOCAL; native restart/replay NOT_RUN | calendar_slots.py, calendar_tasks.py, 0009, models | Native + delta restart |
| Provenance/authority | Grammar teks tunggal → slot sources + final approval | TESTED_LOCAL grammar/negasi/quoted input; native pairing/scope NOT_RUN | tasks, journal, trusted binder preserved | Native owner/config/grant race |
| Scheduled execution | Journal due tersedia, chat belum → explicit due parser | TESTED_LOCAL relative/DST/offset/past/midnight | slots, journal, broker, 0009 | No-early/due-order/cancel/lease native |
| Approval compatibility | v1 arguments → v2 payload/due/zona/window, v1 preserved | TESTED_LOCAL fingerprints; immutable trigger SQL generated | journal, execution, 0009 | Native trigger + old approval/supersede |
| Conversation/job separation | dispatching blocks ACTIVE → handed_off task | IMPLEMENTED, 13 new native cases collected | assistant/telegram routing, tasks | Native future job + read/chat |
| Completion delivery | Receipt-only → independent notification identities | IMPLEMENTED; native uncertain/send/reconcile cases NOT_RUN | telegram notifications/repository, tasks | Native + live acknowledgement/completion |
| Cancel/new/clear/expiry | ACTIVE turns only → draft+detached queued jobs | IMPLEMENTED; native field/identity/clear cases NOT_RUN | assistant repo, task routing, commands | Native + targeted acceptance |
| Post-effect recovery | stable ID/GET existing → explicit after-accept crash mock | Provider/unit existing passes; new native crash test NOT_RUN | test_calendar_tasks.py, recovery preserved | Native count one POST/GET |
| Schema/upgrade | 0008 → 0009 additive; earlier migrations unchanged | Offline SQL generation; native populated fixture NOT_RUN; WASM blocked | models/database/0009/upgrade/schema checks | Run consolidated gate |
| Complete encrypted backup | DB-only plaintext legacy → cold volumes + CMS | TESTED_LOCAL + real capture 9–10 Okt (425 MB CMS schema 0014, writers pause/resume, offsite microsd MATCH) | ops_backup/common, volume_archive, compose.operations | Jadwal harian + verifikasi offsite mingguan |
| Restore | none → standalone empty-target quarantine | Drill02/03/04 counts identik, executor/transports absent; retrieval dingin hijau 10 Okt (6 points, search 1.0) | ops_restore, compose.restore | Pending-job-after-restore + RTO penuh |
| Monitoring/rollback/retention | partial health → owner-safe snapshot/local dedup/guards | TESTED_LOCAL alarm/recovery/guard; external/host-failure/load NOT_RUN | monitor, ops_watch, rollback_guard, retention | Local worker drill then channel decision |
| Release/packaging | stale hashes/missing checkpoint/NUL → delta preflight+manifest+runner | TESTED_LOCAL patch/idempotence, lint/format/offline; Docker/Windows NOT_RUN | release_gate/run_release_gate/apply/build/docs | Host gate, build/migrate/recreate |

Semua angka final kandidat harus diambil dari `evidence/stage-4h/release-dacl-fix/verification.json`; jangan menjumlahkan targeted run/historical/subtests. Tidak ada dependency/provider/budget/namespace overhaul. Hosting/offsite/key custody/alert receiver adalah keputusan berikut, default nonaktif. Stage 6–8 tetap dependency roadmap, bukan diimplementasikan oleh registry/prompt.
