# Bukti pelajaran AO #2–#3: verdict gate + skills (11 Okt 2026)

## #2 verdict + secret scan (tanpa kredensial, tanpa dependensi baru)

* `scripts/scan_secrets.py` (stdlib): 7 pola bentuk realistis, lewati
  `.secrets/`, `backups/`, `docs/evidence/`, biner/zip; 1 allowlist
  eksplisit (header PEM palsu di 1 tes). Output hanya file:baris:aturan.
  Langkah pertama gate (offline + native).
* `release_gate.py`: langkah bernama + ringkasan `verdict:
  passed|app_failed|infra` + `failed_step`; exit code tak berubah.
  Bootstrap/migrate gagal bernada koneksi/docker = infra; sisanya app.
* Temuan: 20 hit semuanya di XML evidence lama (stdout tes) — repo
  bersih di luar itu.

## #3 skills + capabilities (tanpa migrasi, tanpa ubah perilaku)

* `src/jarvis/skills/`: `research`, `knowledge`, `planner` masing-masing
  SKILL.md kanonis (hanya perilaku nyata, tanpa vapor). Loader:
  discovery fail-closed, duplikat menang pertama, lazy-load
  SKILL.md + `commands/<x>.md`, tolak `..`.
* `RoleSpec` + `capabilities`/`skill` (default → kompatibel).
  Gerbang nyata: `run_read_only` menolak role tanpa `read_only`
  sebelum claim (`capability_denied:coding`).
* Event `research.completed` mengikat `skill + skill_sha256`.

## Tes + gate

* Unit: verdict 4 + skills 5. Native: research (asersi skill ditambah).
* Gate native 11 Okt: **677 passed / 0 failed** (XML 766, subtests 89),
  schema `0016_memory_projects`, source
  `63b33420d6cff39840323be433e7113d513e902281ed1afdc90a9eca8e159cd4`,
  `verdict: passed`, ruff bersih.
