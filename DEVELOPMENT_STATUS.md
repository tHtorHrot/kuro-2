# KURO — status 10 Oktober 2026 (menggantikan snapshot 5 Okt di bawah)

Release: **PILOT / operasi lokal**. Schema `0017_task_role_documents`, package
`personal-jarvis` 0.4.0. Gate native **701 passed / 0 failed** (XML 790,
subtests 89), ruff clean, source `238318534cbe3cad09985b59e7e73b8f3a28b3e26d8e26bb7b8fc151b7286788`,
bukti `docs/evidence/native-candidate/run/verification.json` (11 Okt,
`native_integration: tested`, `verdict: passed`, live Google/Telegram `not_run`).
Stage 7 slice Research fase indeks lokal SELESAI (bukti
`docs/evidence/stage7/research-local.md`): riset atas dokumen sendiri
bersitasi, tanpa fetch/LLM/kredensial; provider eksternal menyusul.
Pelajaran AO #1 SELESAI (bukti `docs/evidence/stage7/ao-lesson-1-nudge.md`):
sinyal macet + pengingat approval 1x anti-spam.
Pelajaran AO #2–#3 SELESAI (bukti
`docs/evidence/stage7/ao-lesson-2-3-gate-skills.md`): verdict gate
3-state + pindai rahasia + direktori skills + capabilities.
Pelajaran AO #4 SELESAI (bukti
`docs/evidence/stage7/ao-lesson-4-baseline.md`): baseline 1 aktif +
2 standby, tanpa fallback otomatis.
Pelajaran AO #5 SELESAI (bukti
`docs/evidence/stage7/ao-lesson-5-review.md`): `complete(succeeded)`
menolak artifact pending/failed/asing/hantu (422), workspace/sandbox
sudah ada + teruji.
Stage 7 slice Documents fase artifact store SELESAI (bukti
`docs/evidence/stage7/documents-local.md`): tulis deterministik
berversi dari payload eksplisit, tanpa LLM/filesystem/kredensial.
`/task` kini tampilkan anak + kutipan riset (format murni + wiring,
teruji native via bot-transport).
Sejak 5 Okt: Stage 4 delta live hijau, Stage 5 pilot-lengkap (backup
terenkripsi + offsite microsd + restore drill03/04 + retrieval dingin hijau),
UX kalender Fase A–C + tombol inline + kata waktu Indonesia + salvage +
kontrak konfirmasi (`docs/UX_CONFIRMATION_CONTRACT.md`), Stage 6 slice 1–3
SELESAI (memory bertipe/precedence/tombstone + konteks selektif project-aware
+ evaluasi bounded + registry proyek + RLS 28 tabel + restore probe projects),
fix 2B observability (ledger actual-vs-held + unreconciled + kuota harian +
5 terminal terakhir di `assistant-status`, `checked_at_utc` di
`assistant-catalog`; policy retry/fallback tidak dilonggarkan).
Sisa: hosting (ditunda), specialist/voice (Stage 7), RPO/RTO penuh + live
Google/Telegram (acceptance Stage 4/5). Fix 2B live 10 Okt ~15:00 UTC:
api+telegram restart ok, `/ask` smoke dijawab live via rute gratis
(apodex via novita), status hold 0 / unreconciled 0 / `daily 3/15`.

# KURO — kandidat Stage 4h / fondasi Stage 5 (5 Oktober 2026)

Status release: **CANDIDATE / acceptance pending**. Stage 4 belum FROZEN; Stage 5–8 belum selesai. Schema baru `0009_calendar_tasks`; package tetap `personal-jarvis` 0.4.0, namespace jarvis. Source/delivery akhir berada di root proyek; status yang dipakai sesi berikutnya adalah `CHECKPOINT.json`, matriks `docs/WORK_MATRIX.md`, dan bukti `docs/evidence/stage-4h/`.

Pengguna menyatakan seluruh write acceptance sebelumnya berhasil: OAuth write/aktivasi, create, restart scheduler sebelum dispatch, cancel deletion menjaga event, dan approved delete. Read/agenda juga diterima sebelumnya. Bukti dicatat **user_reported**, bukan dijalankan ulang oleh asisten. Tidak ada action ID/grant/image digest/timestamp pengujian yang ditebak. Log `calendar-test.log` pada baseline memang memuat 444 passed / 28.50s; pemetaan hash revisi pengujian itu tidak tersedia dan tidak dialihkan ke source baru. Hasil helper 43 tes adalah bukti historis terpisah.

## Perubahan nyata

- Draft Calendar owner/conversation/identity/bot scoped, anchor/timezone tetap, provenance per field, TTL/size/turn/job limits; follow-up/correction/expiry/target cancel. Teks unrelated tetap chat. Gabungan turn memerlukan approval proposal konkret; tidak memasukkan slot sintetis sebagai instruksi asli.
- Event time dan execution time terpisah; offset + zona IANA, UTC, DST gap/fold fail-closed, lintas tengah malam eksplisit, jadwal lampau ditolak dan late window 15 menit. Fingerprint v2 mengikat payload/due/zona/window; v1 action existing tetap kompatibel dan immutable.
- Job/task terpisah dari active turn; request `handed_off` bukan provider success. Unique active LLM index dipertahankan. Acknowledgement dan completion memiliki identitas delivery berbeda; recovery uncertain→succeeded menghasilkan event baru, bukan mengaktifkan ulang receipt.
- Migrasi 0009 menambah dua tabel tenant FORCE RLS/composite FK dan binding schedule immutable; 0001–0008/lock tidak diubah. Upgrade fixture mencakup owner/pairing/memory/dokumen dan status action pending/claimed/dispatching/uncertain.
- Backup cold lengkap dengan restart writer finally, OpenSSL CMS terenkripsi/pinned public certificate, safe volume archive, standalone quarantine restore, local dedup alarm, retention preview, rollback guard, preflight patch dan evidence-producing release runner. Offsite/key custody/external alarm belum dipilih/diaktifkan; retrieval/restore/kapasitas operasi belum diterima.

## Bukti dan batas

Lint/format, offline pytest, real OCR, enkripsi/dekripsi/tamper detection dan archive/monitor/rollback/patch preflight diuji lokal; hasil mesin final ada di `docs/evidence/stage-4h/release-dacl-fix/verification.json`. Hasil targeted development tidak dijumlahkan dengan suite final. 13 tes native baru telah dikoleksi, belum dijalankan. Native PG/Docker terblokir karena tidak tersedia dan UID hanya root; guard tidak di-bypass. Percobaan supplementary WASM terblokir pada GRANT database di engine sebelum migrasi; bukan native pass.

Belum: build Docker final, native regression 0009/RLS/Qdrant/concurrency/crash provider mock, Windows execution, live delta klarifikasi/scheduled/outbox, natural-chat LLM smoke jika belum ada bukti, encrypted Docker DB/volume restore + retrieval, measured RPO/RTO/capacity, deployment/offsite/external alert. Sesi ini tidak memanggil Google/Telegram/LLM nyata atau mengubah instalasi pengguna.

Instruksi install/rollback: `docs/KURO_CANDIDATE_UPGRADE.md`. Acceptance delta: `docs/KURO_DELTA_ACCEPTANCE.md`. Operasi: `docs/KURO_OPERATIONS.md`. Jangan setup awal/OAuth/pairing/grant ulang atau mengambil nested ZIP lama sebagai baseline. Stage 6 memory/privacy → Stage 7 enam specialist → Stage 8 durable multi-step tetap pekerjaan berikutnya setelah gate Stage 4/5 relevan terpenuhi.

Update runner 5 Oktober: pengguna melaporkan 64 payload file `already_current` setelah penimpaan manual, tanpa build/migrate/recreate. Run Windows awal berhenti pada `NativeCommandError` untuk progres `Image ... Building`; ini bukan native pass. Runner kini memakai `run_test_compose.py` untuk menangkap stdout/stderr dan menjaga exit code. Tes subprocess nyata (Linux), preflight kandidat sebelumnya, dan penyalinan metadata manifest lulus. Regresi final: 470 pytest items + 83 subtes, 0 failed/skipped, 91 native deselected. Runner revisi Windows/Docker masih NOT_RUN. Bukti lama dipertahankan; instruksi khusus: `docs/KURO_RUNNER_FIX.md`.

Pemeriksaan paket mengoreksi pengecualian operations agar hanya folder artefak di root yang dikecualikan. Dua file source monitoring yang terlewat pada ZIP awal kini disertakan. Gate akhir 470 items + 83 subtes; native/Windows corrected runner belum dijalankan.

Update Windows berikutnya: pengguna melaporkan 96 preflight checks berhasil, apply dan diagnosis gagal pada Set-Acl SeSecurityPrivilege sebelum penyalinan. Helper sekarang membaca/persist Access/DACL saja dan memverifikasi rule current-user; owner/group/audit tidak diubah. CLI menampilkan jenis/pesan error aktual. Regresi akhir 470 items + 83 subtes, 0 failed/skipped, 91 native deselected. Bridge Windows diuji mock, bukan native ACL pass. Native Windows dan Docker masih terbuka. Lanjut `KURO_WINDOWS_DACL_FIX.md`.
