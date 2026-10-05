# Tahapan implementasi dan validasi

| Tahap | Hasil yang dibuat | Gate sebelum tahap diterima |
|---|---|---|
| 1. Fondasi | FastAPI, auth/scopes, profil dasar, PostgreSQL/RLS, config, CLI, audit/logs, Docker/CI | Unit, PostgreSQL native, Docker runtime dan review privacy/security |
| 2A. Telegram | Long polling privat, pairing, durable receipt/outbox, retry/health/operasi | Native tests, akun asing ditolak, restart dan timeout/replay diuji |
| 2B. Percakapan | LangGraph, OpenRouter adapter, profile/conversation memory, konfirmasi premium, usage ledger | Tidak ada premium tanpa consent per call; biaya/privasi gagal tertutup; memory owner-isolated |
| 3. Pengetahuan | Qdrant, file store privat, ingestion durable, ekstraksi/OCR terbatas, embedding lokal, retrieval bersumber, penghapusan | Isolasi owner, parser limit, retry/idempotensi, sinkronisasi index, citation dan delete tests |
| 4. Tools dan jadwal | Registry tool berizin, job/scheduler PostgreSQL, lease/lock, retry terukur, tindakan sensitif dikonfirmasi | Batas tool dan SSRF, job sekali efektif, restart/timezone/cancel, audit tindakan |
| 5. Operasional | Deployment online pada server terpilih, backup/restore, monitoring, load test, update/incident runbook | Bukti restore, capacity/cost review, penutupan gate keamanan, penerimaan pemilik |
| 6. Interface tambahan | Web dashboard privat dan voice | Auth browser/CSRF/CORS/TLS, privasi audio, consent dan penghapusan |

Setiap tahap diserahkan sebagai kode yang dapat ditinjau beserta hasil test aktual.
Tidak mengaktifkan cloud/model berbayar hanya karena kode Tahap 2 mulai dikembangkan.
Kredensial dan keputusan deployment diselesaikan saat diperlukan, dengan estimasi biaya
konkret sebelum pengeluaran.

## Kontrak modul berikutnya

**Workflow agent.** State memuat owner/request ID, klasifikasi data, konteks terpilih,
status consent dan tool budget. Node awal memvalidasi otorisasi; node routing tidak bisa
melewati privacy/cost gate. Checkpoint durable di PostgreSQL. Instruksi dari dokumen atau
hasil tool diperlakukan sebagai data, tidak dapat mengubah izin atau prompt sistem.

**Memory.** Conversation dan profile memory milik owner yang sama; retrieval memasukkan
hanya bagian yang diperlukan. Pemilik dapat melihat, memperbaiki, dan menghapus memory.
Ekstraksi fakta otomatis harus memiliki sumber dan status validasi; jangan diam-diam
menyimpan semua dugaan model sebagai fakta profil.

**Ingestion.** Upload -> validasi tipe/ukuran -> file privat -> job durable -> parser
terisolasi -> chunk -> embedding lokal -> upsert Qdrant -> status siap. PostgreSQL menjadi
sumber kebenaran metadata; file hash + owner + pipeline version untuk idempotensi. Job
yang gagal dapat dilanjutkan tanpa menduplikasi atau mencampur owner.

**Tools.** Registry menyimpan schema input/output, kebutuhan scope, jenis efek, target
jaringan yang diizinkan, timeout, dan audit. Model hanya mengusulkan panggilan; dispatcher
memeriksa izin lagi. Tindakan berbiaya, pengiriman pesan, atau perubahan eksternal memerlukan
otorisasi sesuai pengguna. Tidak ada `eval`, arbitrary shell, atau SQL mentah dari LLM.

**Scheduler.** Job tersimpan dengan zona waktu pengguna, waktu eksekusi UTC, idempotency
key, lease owner/expiry, attempt limit, dan cancellation state. Gunakan lock/claim atomik;
restart tidak boleh menggandakan efek. Efek eksternal memerlukan idempotency/reconciliation
karena transaksi database saja tidak menjamin exactly-once pada jaringan.

## Validasi pengguna berikutnya

Tahap 1/2A dilanjutkan sampai penerimaan 2B oleh pemilik: **236 tes Docker lulus, exit 0**,
dan semua tes Telegram dilaporkan berhasil, termasuk `/ask`, `/remember`, `/forget`.
Ling/Novita gratis bekerja; premium nonaktif, budget dan biaya/hold nol. Tiga kegagalan
429 lama tetap merupakan riwayat, bukan bukti bahwa endpoint Qwen sudah pulih.

Tahap **3** tersedia sebagai paket development **0.4.0**. Jalankan
`KNOWLEDGE_WINDOWS.md` untuk gate native sebelum migrasi, lalu tes PDF/DOCX/OCR,
pertanyaan bersumber, penghapusan dan regresi Telegram. Tahap ini belum dinyatakan
diterima hanya dari pengujian lokal pembuat paket.

Tahap **4: tools dan jadwal** telah diimplementasikan; gate penerimaan aktual ada di `STAGE_4_VERIFICATION.md`.
Setelah gate Docker dan migrasi production `0006_tool_action_timezone` lulus, lanjutkan **Tahap 5: operasional/backup-restore/deployment**, kemudian interface tambahan.
Pemilih model dapat dirancang sebagai fitur tersendiri dengan kebijakan biaya tetap
ditegakkan; belum ada pemilih model di bot versi ini. Tidak ada pembelian server atau
panggilan premium otomatis.
