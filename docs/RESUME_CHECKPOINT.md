# Titik lanjut yang dapat diverifikasi

Tanggal pembaruan: 4 Oktober 2026. Sumber aktif berada pada root paket `kuro-main/`.
`CHECKPOINT.json` pada root ZIP memuat SHA-256 setiap file paket.

## Titik lanjut terbaru — Calendar read sudah berhasil

444 tes Docker telah dilaporkan lulus (exit 0). Backup PostgreSQL dan migrasi produksi
lokal selesai; doctor menunjukkan ready/RLS forced/stage 4. Assistant sudah sehat
dan enabled. OAuth Desktop read-only telah berhasil pada Windows pengguna. Grant
`calendar:read` aktif revisi 2 dan scheduler healthy/worker_recent true. Hasil nyata bot
untuk `apa jadwalku besok?` dilaporkan cocok dengan Google Calendar. Jangan ulangi
ekstraksi baseline, 444 tes, backup upgrade, migrasi, setup OAuth atau tools-grant.
Log lengkap belum diunggah; hasil ini dilaporkan pengguna melalui terminal/chat.

Kegagalan aktivasi pertama terjadi sebelum container CLI dibuat: YAML tmpfs flow list
memisahkan `mode=1777` menjadi lokasi mount. Pengguna telah memperbaikinya menjadi satu
scalar dan membuktikan scheduler berjalan. Source sekarang mengikuti perbaikan tersebut.

Formatter agenda sudah dibuat dan lulus 16 tes terarah. Pada 4 Oktober 2026 21:01 WIB,
pengguna melaporkan build berhasil, assistant healthy, config_matches/worker_recent true
dan hasil bot sesuai format baru. Tahap tampilan selesai; jangan ulangi build/recreate
assistant untuk patch helper berikutnya.

Scope aktif pengguna masih baca saja. Helper sekarang mendukung `--access write` ke
folder kandidat `.secrets/calendar_write` dan overlay `compose.calendar.write.yaml`.
43 tes helper lulus, Ruff bersih; tidak ada modul runtime/schema yang berubah pada
patch ini. OAuth kandidat, aktivasi grant dan smoke write belum dilakukan pengguna.
Lanjutkan dari `docs/STAGE4_WRITE_ACCEPTANCE.md`; jangan timpa credential baca, jangan
berikan calendar:send, dan jangan pindah binding saat ada tindakan pending/uncertain.

Audit gate lengkap ada di `docs/STAGE4_REMAINING.md`. Setelah smoke write, selesaikan
batas klarifikasi/penjadwalan percakapan dan regresi konsolidasi sebelum freeze.
Stage 5–8 tetap target selanjutnya. Panduan OAuth awal ada di `GOOGLE_CALENDAR_WINDOWS.md`.
Bagian historis di bawah bukan alasan mengulang gate native yang telah diterima.

## Sudah selesai; jangan diulang

- Ekstraksi aman ZIP input dan pembacaan catatan kondisi proyek.
- Audit perbedaan klaim dokumentasi dengan jalur runtime nyata.
- Perbaikan parser email/@handle, shared commands, trusted intent grounding,
  owner/scope checks dan pengujian regresi ingress.
- Instalasi dependency frozen sesuai `uv.lock` dan pemulihan gate native awal.
- Regresi native awal 389/81, dengan PostgreSQL 16.15/Qdrant 1.19.1 nyata.
- Perbaikan lint lama. Formatting tambahan terpisah dari perubahan perilaku pada
  daftar perubahan; migrasi 0001–0006 tidak mendapat perubahan skema.
- Implementasi kandidat Calendar chat, grants, result, approval, recovery,
  executor binding, health dan tes baru yang dijelaskan di DEVELOPMENT_STATUS.md.

## Langkah terakhir yang benar-benar berhasil

366 unit/offline dan 83 subtes lulus pada source akhir sebelum pengemasan; Ruff
lint/format bersih. SQL Alembic offline sampai `0008_executor_binding` dibuat.
78 tes integrasi dapat dikoleksi. Hasil native 389/81 sebelumnya disimpan sebagai
bukti revisi lama, tidak dijumlahkan dengan unit kandidat terbaru.

`docs/evidence/stage-4g/verification-final.json` memuat hasil dan hash source yang
diverifikasi. `source-changes.json` membandingkan kandidat dengan ZIP input;
perbedaan AST dibedakan dari perubahan yang hanya memengaruhi komentar/format.
XML unit memuat 449 hasil karena 83 subtes tercatat terpisah dari 366 tes.

## Langkah yang terputus atau terblokir

Regresi unit sebelumnya terputus tanpa hasil final; sesi ini menyelesaikannya.
Penerimaan native untuk sambungan Calendar baru dan migrasi 0008 belum selesai.
Lingkungan terbaru hanya menyediakan UID root dan tidak menyediakan Docker.
Eskalasi ditolak konfigurasi approval otomatis. Jangan menghapus guard non-root
PostgreSQL atau mengganti test DB dengan mock untuk memberi label native pass.

## Urutan pekerjaan berikutnya

1. Jalankan `compose.test.yaml` pada lingkungan disposable yang mendukung Docker.
   Gate akan bootstrap role nonprivileged, menguji upgrade data lama, migrate dua
   kali, dan menjalankan seluruh pytest, termasuk 12 kasus Calendar chat baru.
2. Tinjau kegagalan native secara khusus: transaksi source/action, scope revocation,
   dedup concurrency, approval replay, fencing, durable result/outbox, recovery.
3. Build runtime final dan smoke pada kalender Google uji. Jangan mengirim undangan
   ke pihak lain tanpa persetujuan terpisah untuk penerima dan isi konkretnya.
4. Selesaikan slot clarification/follow-up dan UI scheduled execution; uji gate S4.
5. Stage 5 backup/restore/rollback dan deployment privat. Baru lakukan freeze ketika
   hasil operasional benar-benar terukur, kemudian lanjut Stage 6–8 sesuai acceptance.

## Migrasi dan kompatibilitas

0007 menambah grants, source-step dedup dan result. Antrean legacy tanpa grant
terverifikasi dibatalkan; dispatch legacy menjadi uncertain. 0008 menambah executor
binding dan heartbeat. Ini memungkinkan checkpoint 0007 diteruskan tanpa mengedit
migrasi yang sudah diterapkan. Grants lama tanpa binding tidak mengizinkan Calendar
production worker sampai operator mengatur ulang grant. Rekam dan rekonsiliasi
aksi pending sebelum upgrade; tidak ada downgrade destruktif otomatis.

Paket ini tidak berisi secret produksi, runtime dependency cache, binary test server,
atau tiga nested ZIP historis. Tidak ada Git remote, hosting target atau credential
provider baru yang ditambahkan.
