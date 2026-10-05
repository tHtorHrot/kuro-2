# Hasil verifikasi Tahap 1 — v0.1.0

Tanggal: **28 September 2026**. Status: **fondasi siap ditinjau; penerimaan produksi masih
menunggu uji native/Docker dan pemeriksaan operasional**.

## Hasil yang benar-benar dijalankan

| Pemeriksaan | Hasil | Arti/batas |
|---|---|---|
| Ruff lint dan format | Lulus | Pemeriksaan statis kode Python |
| Pytest unit/HTTP/security boundary | **47 lulus** | Menguji konfigurasi, token, privacy/cost policy, scope/HTTP boundary dan commit failure dengan stub |
| Pytest PostgreSQL native | **11 skipped** | Server PostgreSQL native tidak tersedia di lingkungan pengerjaan; bukan 11 test lulus |
| Coverage lokal | **Sekitar 66%** termasuk branch | Coverage seluruh paket dari unit suite; jalur service/database/CLI belum seluruhnya dieksekusi |
| Migrasi Alembic offline | Lulus | SQL revision `0001_foundation` dihasilkan tanpa koneksi DB |
| DDL/RLS pada PGlite | **17 pengecekan lulus** | PostgreSQL 18.3 WASM melalui PGlite 0.5.8; bukan PostgreSQL 16 native |
| Dependency audit runtime Python | **23 dependensi; 0 advisory diketahui** | Snapshot hasil pip-audit saat pemeriksaan; bukan audit OS/image/pentest |
| Validasi kedua Compose terhadap schema resmi | Lulus | Struktur YAML valid; tidak membuktikan container berhasil dijalankan |
| Shell bootstrap syntax | Lulus | `sh -n` |
| Kompilasi Python dan build wheel/sdist | Lulus | Paket Python berhasil dibangun |

Bukti machine-readable disertakan di `docs/evidence/`: laporan pytest, coverage,
dependency audit, dan hasil pemeriksaan SQL tambahan.

## Cakupan keamanan yang telah diperiksa lokal

- Token mengikat owner/record dan tidak cocok bila secret/pepper diubah.
- Kredensial pairing tidak dapat dipakai sebagai bearer API.
- Konfigurasi runtime menolak user database selain `jarvis_app`, termasuk saat database belum tersedia.
- Training/retensi/harga yang tidak diketahui ditolak; premium memerlukan persetujuan.
- Input terlalu besar/lambat, spoofed forwarded IP, host tidak diizinkan, dan scope salah ditolak.
- Exception tidak membocorkan isi input/SQL/secret; header no-store tetap ada pada error.
- Kegagalan commit sebelum respons menghasilkan HTTP 500, bukan respons sukses.
- Pada engine SQL WASM: RLS tanpa konteks tidak menampilkan baris, owner lain tidak terlihat,
  insert lintas owner ditolak, update lintas owner tidak mengubah baris, audit tidak dapat
  diubah/dihapus oleh role aplikasi, CREATE dan SET ROLE migrator ditolak.

## Yang belum dibuktikan

Docker daemon dan PostgreSQL native tidak tersedia dalam lingkungan pengerjaan. Karena itu
image build/runtime, mount permissions UID 10001, bootstrap cluster official image,
autentikasi database native, psycopg async/pooling, transaksi konkuren pairing, dan restart
container belum diuji end-to-end di sini. PGlite tidak menggantikan pemeriksaan tersebut.

CI telah ditulis tetapi belum dieksekusi pada GitHub; tidak ada repository atau deployment
eksternal yang dibuat. Backup/restore, enkripsi storage, firewall mesin tujuan, capacity/load
test, dan pemindaian OS image juga menunggu lingkungan deployment.

## Cara menerima tahap ini

1. Ekstrak ZIP dan baca README.md; gunakan data contoh.
2. Jalankan cluster test terpisah:

   ```bash
   docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
   docker compose -f compose.test.yaml down --volumes
   ```

3. Hasil yang diharapkan: semua **58 test** lulus, tanpa skip integrasi. Kegagalan perlu
   diperiksa sebelum melanjutkan. `JARVIS_REQUIRE_INTEGRATION=1` dipasang oleh Compose test.
4. Jalankan instruksi README untuk runtime: generate secrets, build/start API, `doctor`,
   create owner, baca `/api/v1/me`, lalu cabut token dan pastikan akses menjadi 401.
5. Selesaikan syarat penerimaan SECURITY.md sebelum data sensitif/akses server digunakan.

Tidak ada model AI yang dipanggil, pengeluaran provider premium, publikasi dokumen,
atau pembelian server dalam pengerjaan Tahap 1. Tahap berikutnya menambahkan Telegram,
LangGraph, memory percakapan, dan routing model dengan konfirmasi premium.
