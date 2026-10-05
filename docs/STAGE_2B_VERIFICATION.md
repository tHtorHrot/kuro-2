# Bukti dan batas verifikasi Tahap 2B

## Pembaruan 29 September 2026

Pemilik melaporkan **207 passed**, exit 0 dan coverage 75% pada Docker native untuk
v0.3.0, lalu doctor/readiness/Telegram berhasil. AI sudah aktif tetapi satu permintaan
gagal. Penyebab inference belum terkonfirmasi dari status tersebut.

Hotfix `2b-diagnostics-1`: **195 passed, 41 skipped** secara lokal; gate Docker setelah
hotfix menargetkan **236 passed**. Rincian pemasangan, bukti, dan batas verifikasi
ada di [HOTFIX_ASSISTANT_DIAGNOSTICS.md](HOTFIX_ASSISTANT_DIAGNOSTICS.md).
Bagian berikut merupakan catatan historis saat paket v0.3.0 pertama dibuat,
bukan status penerimaan hotfix.

## Catatan historis rilis awal

Paket v0.3.0. Status ini membedakan kode yang disediakan, pengujian aktual di lingkungan
pengembangan, dan gate yang masih harus dijalankan pemilik pada Docker Windows.

## Sudah dijalankan

- Ruff lint dan format seluruh sumber/test/script: lulus.
- Unit tests: **166 passed**. Semua HTTP provider/Telegram pada suite dimock; tidak ada
  API key pengguna, data pengguna, biaya, atau pesan Telegram nyata dari pengujian ini.
- Suite keseluruhan di lingkungan ini: **166 passed, 41 skipped**. Seluruh skip adalah
  integrasi PostgreSQL native karena server/daemon Docker tidak tersedia di lingkungan ini.
- SQL Alembic 0001 -> 0002 -> 0003 diterapkan pada PGlite PostgreSQL WASM: **54 checks passed**,
  termasuk RLS 12 tabel, grants, satu request aktif per owner, uniqueness attempt, biaya
  nonnegatif dan larangan menghapus ledger. Ini bukan test PostgreSQL 16 native/driver/pool/
  concurrency dan tidak boleh menggantikan gate Docker.
- Audit runtime Python: **53 dependencies, 0 known vulnerabilities** pada saat pemeriksaan.
  Bukan jaminan bebas celah, dan belum mencakup OS/image/container/cloud configuration.
- Validasi Compose terhadap JSON schema resmi: base, Telegram, assistant, test dan gabungan
  statis lulus; audit secret/network separation lulus. Ini bukan runtime Compose merge.
- Wheel/sdist dibuat menggunakan dependency lock. Tidak ada secret pengguna di paket.
- Katalog model/ZDR publik dibaca tanpa inference. Listing Qwen gratis ditemukan tetapi
  status nonzero ditolak oleh gate ini. Dua kandidat teks gratis Ling muncul pada snapshot;
  wizard selalu membaca ulang katalog dan meminta pengguna memilih. Tidak menjamin model,
  kuota, kebijakan endpoint, atau harga tetap tersedia saat pengguna melakukan setup.

Bukti mesin ada di `docs/evidence/stage-2b/`. Snapshot 2A dan Tahap 1 dipertahankan sebagai
sejarah, bukan bukti pengujian kode 2B. Total coverage lokal rendah karena business-domain
DB diuji dalam suite native yang belum bisa dijalankan di sini; lihat angka aktual di
coverage.json, jangan menganggap coverage 75% milik 2A berlaku untuk 2B.

## Gate pada komputer pemilik

1. `docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests`:
   target **207 passed**, 0 skipped/failed, exit 0. File test yang hilang tidak boleh di-skip.
2. Backup lokal sebelum migrasi; doctor/RLS/revision 2b, readiness, bearer 401/200 masih benar.
3. Telegram tetap paired, akun asing tidak mendapat respons, restart tidak menduplikasi aksi.
4. Setup model tersembunyi, metadata gratis USD0/no-training/ZDR diverifikasi, `/ask` nyata
   pertama dengan data nonsensitif dan ledger dicek. Pengujian live ini belum dilakukan di sini.
5. Memory/new/forget/clear dan restart dicoba. Jika memilih premium kemudian, uji expiry,
   cancel, satu approval satu attempt dan ledger; setiap panggilan nyata tetap membutuhkan
   persetujuan pengguna. Tidak ada premium call disetujui/dijalankan dalam sesi pengembangan.

## Batas penerimaan produksi

Native Docker belum dijalankan untuk 2B; jangan langsung mengaktifkan AI sebelum gate.
Belum ada encrypted offsite backup, full restore drill, VPS hardening/deployment, monitoring
24/7 atau high availability. Tidak ada rekonsiliasi billing otomatis. Kasus uncertain
mempertahankan hold; kasus hasil/biaya tak terverifikasi membekukan AI sampai diagnosis
operator. Shared app DB credential dan host/database admin adalah trust boundary.

Keamanan tidak disimpulkan dari satu healthcheck atau angka tes. Rancangan stage bertujuan
memiliki kontrol yang dapat diverifikasi, dengan batas nyata dicatat di sini.
