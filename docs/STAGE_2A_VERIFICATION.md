# Hasil verifikasi Tahap 2A — v0.2.0

Tanggal 28 September 2026. **Siap diserahkan untuk validasi pada Docker pengguna.**
Belum diklaim lolos penerimaan produksi atau diuji dengan bot Telegram sungguhan.

## Hasil aktual di lingkungan pengerjaan

| Pemeriksaan | Hasil | Batas bukti |
|---|---|---|
| Ruff lint/format | Lulus | Pemeriksaan statis kode Python |
| Unit HTTP/auth/policy/Telegram/setup | **121 lulus** | Transport Telegram dan database unit memakai mock/stub; tidak memakai akun nyata |
| PostgreSQL native | **23 skipped** | Tidak ada Docker daemon/PostgreSQL native di lingkungan ini; bukan tes lulus |
| Coverage unit seluruh paket | **57,1%** termasuk branch | Jalur transaksi database/worker lifecycle belum seluruhnya dieksekusi; tidak dipakai sebagai klaim aman |
| Migrasi offline Alembic | Lulus | SQL 0001 → 0002 dihasilkan; tidak mengubah database pengguna |
| SQL/RLS tambahan PGlite | **31 pengecekan lulus** | PostgreSQL 18.3 WASM/PGlite 0.5.8; bukan PostgreSQL 16 native/driver/pooling/concurrency |
| Audit runtime Python | **26 dependensi, 0 advisory diketahui** | Snapshot pip-audit; bukan pemindaian OS/image atau pentest |
| Compose base/overlay/test dan gabungan statis | Lulus schema resmi serta cek pemetaan port/secret | Belum verifikasi merge/runtime oleh Docker Compose asli |
| Build wheel dan sdist v0.2.0 | Lulus | Build online setelah build offline gagal karena cache build dependency belum tersedia |
| Kompilasi Python dan syntax shell bootstrap | Lulus | Tidak membuktikan mount Windows/container runtime |

Bukti JSON/XML ada di `docs/evidence/stage-2a/`. Bukti di direktori induknya adalah snapshot
historis Tahap 1. Native tests lama tetap ada, ditambah 12 kasus/parameterisasi native
Telegram; total suite **144 tes**. Target pada Compose test adalah **144 passed**, tanpa
skip. Angka ini bukan hasil yang sudah dijalankan di sini.

## Kasus penting yang diperiksa

- Akun lain, grup/chat salah, bot, forward/delegated, edited update, date salah ditolak.
- Isi pesan/lampiran tidak masuk struktur command persisten; kode pairing disembunyikan dari repr.
- Redirect/proxy lingkungan dan method di luar allowlist ditolak, target HTTPS tetap.
- Connect failure dibedakan dari read/write timeout ambigu; send tidak retry otomatis untuk
  hasil yang mungkin sudah terkirim; 429 memiliki jeda tervalidasi.
- Respons terlalu besar, JSON rusak, ID/bot/webhook/chat balasan salah gagal tertutup.
- Setup menggunakan LF, exclusive file creation, rollback file parsial, hidden entry tanpa
  echo fallback, challenge ID numerik; file lama tidak ditimpa.
- Backup menggunakan aliran biner, menghapus file gagal, tidak menghapus database/volume.
- DDL/RLS WASM memeriksa dua tabel baru, cross-owner deny, status/template/attempt constraints,
  foreign key, izin DELETE receipt dan larangan DELETE state.

## Gate pengguna berikutnya

1. Seluruh 144 tes pada `compose.test.yaml` menggunakan PostgreSQL 16.15 native harus lulus.
2. Backup lokal berhasil, migrasi tambahan pada volume Tahap 1 berhasil; API/doctor/auth tetap benar.
3. Setup, pairing, `/status`, penolakan akun asing, disable/enable dan restart worker diuji.
4. Dokumen sensitif belum dimasukkan. Backup terenkripsi luar host, restore terisolasi,
   hardening host/ACL, kapasitas, monitoring, dan image scan diselesaikan sebelum produksi.

Lihat `TELEGRAM_WINDOWS.md` untuk langkah yang dapat langsung dijalankan. Tidak ada biaya
model, deployment publik, pembelian server, atau pesan Telegram sungguhan yang dilakukan
selama pengerjaan paket ini. Premium dan pengiriman data ke LLM tetap menunggu Tahap 2B.
