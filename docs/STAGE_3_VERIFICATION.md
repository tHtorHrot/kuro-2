# Bukti pengujian Tahap 3 — 0.4.0

Diperiksa 1 Oktober 2026. Ini kandidat development untuk upgrade dari 2B yang telah
diterima pemilik (236 tes Docker dan tes Telegram dilaporkan berhasil). Angka 236 adalah
bukti instalasi 2B pemilik, bukan hasil suite Tahap 3 berikut.

| Pemeriksaan pembuat paket | Hasil aktual |
|---|---|
| Suite akhir `pytest -q` dengan native Qdrant | **229 passed, 53 skipped**, exit 0 |
| Native Qdrant 1.19.1, tes terpisah | **1 passed**, exit 0: upsert, filter owner/dokumen, delete |
| SQL/RLS/FK dan penghapusan dengan PGlite | **72 checks passed**, PostgreSQL 18.3 WASM |
| Ekstraksi dan OCR nyata fixture | Lulus dalam suite lokal; Poppler/Tesseract, DOCX, malformed/bomb |
| Model multilingual yang dipatok | Lima file checksum cocok; pemuatan offline dan 3 vector 384 dimensi lulus |
| Lint / format | Lulus; pemeriksaan lint dan format final exit 0 |
| Dependency lock / wheel | `uv sync --frozen` dan `uv build --wheel` exit 0; manifest model masuk wheel |
| Review kode independen | Satu review independen; tidak ada Critical, satu Important CI Windows diperbaiki |

Bukti mentah ada di `docs/evidence/stage-3/`. Run awal tanpa service: 228 passed,
54 skipped (53 PostgreSQL + 1 Qdrant). Run akhir menyertakan Qdrant nyata: 229 passed,
53 skipped. Hanya tes PostgreSQL belum berjalan. Skipped bukan passed. Pemeriksaan WASM bukan koneksi PostgreSQL 16
native dan tidak membuktikan pooling, advisory lock atau race transaksi jaringan.

Model diuji dengan tiga teks sintetis: kemiripan pertanyaan–kutipan .6006 dan pertanyaan–
teks tidak terkait .0642. Ini smoke test, bukan benchmark kualitas retrieval. Tidak ada
file/pertanyaan nyata pemilik atau panggilan OpenRouter dalam pemeriksaan ini.

## Gate yang tetap harus dijalankan pemilik

1. `compose.test.yaml`: build image, PostgreSQL 16 native, Qdrant, populated upgrade 2B→3,
   suite tanpa kegagalan dan `TEST_EXIT_CODE=0` **sebelum migrasi database pemilik**.
2. Build runtime dan parser, migrasi, init/download model, status/health/check menggunakan
   Compose gabungan di KNOWLEDGE_WINDOWS.md. Tidak perlu mengganti konfigurasi Ling/Novita.
3. Tes Telegram dokumen DOCX/PDF/OCR, sumber, duplikat, restricted, delete/restart, akun
   asing dan regresi `/ask`/memory. Verifikasi biaya tetap sesuai konfigurasi Anda.
4. Sebelum dokumen sensitif/operasi produksi: backup/restore sumber+DB+indeks konsisten,
   ACL/akses host, enkripsi disk/backup sesuai kebutuhan, kapasitas RAM/disk dan image scan.

Docker Desktop/Windows, native PostgreSQL dan bot pemilik tidak tersedia di lingkungan
pembuat paket. Tidak ada klaim seluruh gate itu sudah lulus. CI diperbarui untuk gate
tersebut tetapi belum dijalankan sebagai GitHub Actions oleh pembuat paket.

## Batas fitur yang diserahkan

Upload dari komputer; PDF/DOCX/PNG/JPG; OCR lokal eng+ind. Maksimal empat kutipan satu
dokumen, bukan ringkasan seluruh buku. Label citation diverifikasi, kebenaran setiap klaim
AI tetap perlu diperiksa. Restricted belum punya UI pencarian/jawaban lokal. Gambar Word
tertanam, header/footer, komentar dan track changes tidak diekstrak; .doc perlu konversi.
Lampiran bot, pemilih model di Telegram, tools/jadwal dan deployment belum termasuk.

`backup_local.py` hanya mencadangkan PostgreSQL. File sumber dan indeks memerlukan
backup volume tambahan; prosedur otomatis lengkap/restore drill termasuk pekerjaan
operasional selanjutnya. Simpan file asli sampai backup dokumen diuji.


## Review dan keputusan pelaksanaan

Review lengkap ada di `docs/evidence/stage-3/review.md`; keputusan serta biaya/risikonya
ada di `progress.md` pada folder yang sama. Satu cacat CI Windows diperbaiki setelah
pemeriksaan platform RED→GREEN, kemudian seluruh suite yang tersedia dijalankan ulang.
Tidak ada temuan minor yang ditunda. Tes stalled-parser untuk memaksa deadline/kill
belum ada; uji batas/parser yang tersedia tidak membuktikan semua input adversarial.

Pemulihan lingkungan pengerjaan menyebabkan satu commit implementasi gabungan, dengan
pengujian ulang setelah pemulihan. Upload dipilih dari operator lokal, bukan bot. UI
pencarian restricted ditunda; penyimpanan/index lokal tetap ada dan pengiriman AI ditolak.
Pilihan ini tidak mengaktifkan biaya atau mengganti rute pengguna.

Pemeriksaan arsip terpisah mencocokkan CRC ZIP, daftar file, setiap checksum manifest,
layout root, dan pengecualian path secret/data/cache. Model weights tidak dibundel;
perintah download eksplisit mengambil revisi dan checksum yang dipatok.


## Pembaruan OCR-1 berdasarkan tes Docker pemilik

Pemilik melaporkan **281 passed, 1 failed**, exit 1, pada
`test_real_image_ocr_and_scanned_pdf`. Jadi suite 0.4.0 awal belum memenuhi gate.
Pemeriksaan menemukan bahwa Dockerfile hanya memasang data bahasa OCR dengan
`--no-install-recommends`, tanpa executable `tesseract-ocr`. Hotfix menambah mesin
secara eksplisit di image tests/parser dan pemeriksaan executable/bahasa saat build.
CI Ubuntu juga menyebut mesin secara eksplisit.

Tes lokal sebelumnya memakai Tesseract yang sudah tersedia pada host, sehingga tidak
mendeteksi dependency image yang hilang. Detail di HOTFIX_OCR_1.md dan evidence
`ocr-hotfix-1`. Gate Docker setelah hotfix masih harus dijalankan; laporan sebelum
hotfix tidak diperlakukan sebagai penerimaan penuh atau klaim bahwa hotfix sudah lulus.
