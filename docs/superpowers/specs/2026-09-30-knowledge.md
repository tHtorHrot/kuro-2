# Tahap 3 — dokumen privat, OCR, dan jawaban bersumber

## Brief yang disepakati

Pemilik menerima Tahap 2B: 236 tes Docker lulus, semua tes Telegram berhasil, Ling/Novita gratis aktif, biaya/hold nol. Pemilik meminta ZIP pembaruan untuk digabung ke A:\jarvis-stage-1, mendukung PDF/Word serta scan/foto dengan OCR sejak tahap ini. Kode tidak membawa .env, .secrets, data atau backup pemilik. Premium tetap mengikuti persetujuan per panggilan yang sudah ada.

## Keputusan implementasi

Versi 0.4.0, migrasi 0004_knowledge. Upload privat dari komputer melalui scripts/documents.py yang mengalirkan file ke CLI Docker, bukan melalui Telegram atau URL arbitrer. Telegram menambah /docs, /doc UUID, /askdoc UUID pertanyaan, /deldoc UUID. /ask tetap percakapan biasa; dokumen tidak diam-diam dimasukkan ke /ask. Word .doc harus dikonversi menjadi .docx.

Komponen: PostgreSQL/FORCE RLS menyimpan dokumen, chunk, antrean/status dan heartbeat. File privat berada pada volume terpisah. Worker knowledge tunggal per owner mengambil pekerjaan durable; parser berjalan pada container tanpa secret, database, atau egress. Parser memakai subprocess terbatas dengan Poppler dan Tesseract eng+ind; PDF teks diekstrak per halaman, halaman bergambar diproses OCR bila diperlukan. --ocr always dapat dipakai ketika text layer buruk; --ocr never untuk ekstraksi teks saja. DOCX diekstrak dari XML setelah validasi ZIP; gambar tertanam tidak diproses pada versi ini. JPG/PNG diproses OCR. Embedding lokal FastEmbed multilingual MiniLM, cache model disiapkan oleh perintah eksplisit terpisah. Worker runtime tidak mengunduh model dan tidak mempunyai egress internet. Qdrant privat menyimpan vector dan ID saja, teks tetap di PostgreSQL.

Alternatif upload Telegram menambah jalur pemrosesan pihak ketiga dan belum dipilih; jalur lokal memenuhi kontrak privasi lama. Alternatif OCR cloud memerlukan kebijakan/biaya baru; dipilih OCR lokal. Qdrant terpisah mempertahankan roadmap dan membatasi akses indeks hanya ke worker knowledge.

## Batas dan kontrak

- Maksimum file 20 MiB; 200 halaman PDF; 50 halaman OCR; 500.000 karakter; 1.500 chunk; 200 dokumen aktif/owner; 2 GiB sumber aktif/owner.
- Parser deadline 180 detik, child memory 768 MiB, output maksimal 4 MiB; container readonly dengan tmpfs, satu parsing aktif.
- Nama file hanya metadata yang disanitasi; filesystem menggunakan UUID owner/document; symlink dan traversal ditolak.
- Idempotensi owner + hash sumber + versi pipeline; perubahan class/OCR pada hash sama ditolak untuk menghindari downgrade diam-diam.
- Restricted dapat disimpan/dicari lokal tetapi /askdoc diblokir sebelum inference. Private merupakan deklarasi pemilik; filter secret tambahan bukan classifier sempurna.
- Ingestion: queued → processing → ready; gagal → failed dengan kode tetap, retry operator eksplisit; crash processing dapat direbut setelah lease habis. Maksimum 3 attempts. Status deleting mengalahkan publish ready, dan cleanup diulang sampai lengkap.
- Query dipersiapkan worker knowledge tanpa panggilan LLM. Maksimum 4 chunk dari satu dokumen; validasi ulang owner/doc/status di PostgreSQL setelah hasil Qdrant. Tidak ada sumber → pesan lokal tanpa inference. Assistant mengambil snapshot immutable; revalidasi dokumen saat dispatch dan finish. Dokumen/query tidak mengubah izin, instruksi sistem atau consent.
- Jawaban dokumen harus menggunakan [S1] dst. Aplikasi menolak label tidak sah/tanpa citation, lalu menambahkan sumber resmi dari metadata tersimpan. Ini verifikasi referensi, bukan jaminan kebenaran/entailment jawaban.
- Jawaban dokumen tidak dicampurkan ke conversation memory umum. Penghapusan segera mengeluarkan dokumen dari pencarian, membatalkan request terkait, menghapus snapshot/reply lokal terkait, kemudian file/chunk/vector; ledger biaya tanpa isi tetap ada. Salinan Telegram/backup mengikuti batas retensinya sendiri.
- Qdrant/parser tidak menerbitkan port host, masing-masing jaringan internal terpisah; parser tidak bergabung jaringan database. Worker/ops memegang kredensial runtime yang sudah ada, hanya satu owner konfigurasi.

## Penerimaan

Tes nyata ekstraksi PDF/DOCX dan OCR fixture, malformed/oversized/traversal/ZIP bomb, chunk locator, citation invalid, no-source, restricted, RLS lintas-owner, duplicate upload, restart/lease, delete selama index/query/inference, consent lama, regresi 2B. HTTP eksternal model dimock. Catat native PostgreSQL/Docker, model embedding, atau OCR yang tidak tersedia sebagai belum diverifikasi, bukan lulus. ZIP berisi tests, migrasi, lock, README/panduan Windows, hasil aktual, checksum/manifest. Pemilik menjalankan gate Docker sebelum memperbarui runtime; backup sebelum migrasi dan volume produksi dipertahankan.
