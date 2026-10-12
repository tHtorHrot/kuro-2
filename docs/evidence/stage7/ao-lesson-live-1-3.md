# Bukti live pelajaran AO #1–#3 (11 Okt 2026, produksi)

Tanpa credential baru. Image `personal-jarvis:0.4.0` rebuild + recreate
(assistant, telegram, knowledge, scheduler, task-worker).

* doctor: `ready`, RLS `enabled_and_forced`, stage 4.
* `scan_secrets.py --root .`: `secret_scan: clean`, exit 0.
* `discover_skills()`: `['knowledge', 'planner', 'research']`.
* `require_capability(['research'], 'read_only')`: ok.
* `require_capability(['coding'], 'read_only')`:
  `ValueError: capability_denied:read_only:coding` (gerbang bekerja).
* Tes nudge live 10 menit: opsional, belum dijalankan (native hijau).
