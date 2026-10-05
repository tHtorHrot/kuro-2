KURO Stage 4 Write Acceptance — 4 Oktober 2026

Ekstrak isi ZIP langsung ke A:\Kuro2\kuro-main, gabungkan folder dan timpa file patch.
Mulai dari docs/STAGE4_WRITE_ACCEPTANCE.md.

Read Calendar dan format agenda sudah diterima pengguna. Patch ini menyediakan
OAuth kandidat tulis terpisah dan panduan satu uji create/restart/cancel/delete approval.
Jalankan python .\scripts\setup_calendar.py --access write setelah menambahkan scope
https://www.googleapis.com/auth/calendar.events.owned pada Data Access aplikasi Google.
Token disimpan di .secrets/calendar_write, credential baca existing tidak ditimpa.
Login saja belum mengganti grant atau menjalankan scheduler.
Aktivasi/pemeriksaan antrean dan langkah uji tersedia lengkap dalam panduan.

Tidak memerlukan build image atau migrasi ulang. Tidak ada secret di dalam paket.
43 tes helper lulus. OAuth write/smoke Windows belum dijalankan pengguna/asisten.
Stage 4 masih OPEN; lihat docs/STAGE4_REMAINING.md. Stage 5–8 belum selesai.
