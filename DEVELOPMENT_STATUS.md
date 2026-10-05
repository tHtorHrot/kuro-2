# KURO — checkpoint pengembangan 4 Oktober 2026

## Pembaruan setelah pengujian pada komputer pengguna

Pengguna telah melaporkan **444 tes Docker lulus dalam 28,50 detik**, exit code 0,
kemudian backup PostgreSQL, migrasi dan doctor berhasil pada instalasi lama yang
dilanjutkan dari `A:\Kuro2\kuro-main`. Assistant sekarang enabled, tidak frozen,
config cocok dan heartbeat terbaru. Pada 4 Oktober 2026 pengguna berhasil melakukan
OAuth baca, mengaktifkan grant `calendar:read` revisi 2, dan menjalankan scheduler
healthy. Balasan bot untuk `apa jadwalku besok?` dilaporkan sesuai Google Calendar.
Bukti ini berupa keluaran terminal dan laporan pengguna; full test log belum diunggah.

Hambatan native yang dijelaskan di bagian historis di bawah telah diselesaikan
melalui komputer pengguna untuk kandidat runtime yang sama. Tidak perlu mengulang
444 tes atau migrasi tersebut. Helper OAuth lokal sebelumnya lulus 35 tes. Pengguna
menemukan dan memperbaiki pemisahan `tmpfs` oleh koma pada YAML flow list: bentuk scalar
`/tmp:size=16m,mode=1777` sudah berhasil digunakan dan sekarang disamakan pada source.

Patch terbaru merapikan hasil baca menjadi tanggal/zona sekali, jam mulai–selesai dan
judul setiap acara. ID tetap pada journal; data provider tidak diubah. Acara sepanjang
hari, lintas tanggal, perbedaan zona/DST, data waktu tidak lengkap dan batas Telegram
ditangani. 16 tes terarah lulus; lint/format bersih. Assertion integrasi read diperbarui
untuk memeriksa judul/zona dan ID yang tetap tersimpan; PostgreSQL/Docker tidak dijalankan
ulang oleh asisten untuk patch tampilan ini. Pada 4 Oktober 2026 21:01 WIB pengguna
melaporkan build berhasil, assistant healthy, dan format bot sesuai. Tampilan diterima.

Read Calendar E2E dan UI diterima berdasarkan laporan pengguna. Kandidat berikut
menambahkan `setup_calendar.py --access write`, yang menyimpan credential terpisah di
`.secrets/calendar_write`, serta overlay `compose.calendar.write.yaml`. Scope hanya
owned events; Google consent baru tetap diperlukan. Helper kini lulus 43 tes. Patch
ini tidak mengubah modul runtime atau schema, sehingga tidak memerlukan build image.
Aktivasi memeriksa antrean, mengganti binding/grant secara eksplisit, dan recreate
scheduler. Panduan lengkap `docs/STAGE4_WRITE_ACCEPTANCE.md` menggabungkan satu create
uji dengan restart pre-dispatch, cancel dan delete approval. Aktivasi/tes write belum
dilakukan pengguna atau asisten; calendar:send tetap tidak diberikan oleh panduan.

Audit sisa gate ada di `docs/STAGE4_REMAINING.md`. Klarifikasi bertahap dan penjadwalan
eksekusi tertunda dari chat masih terbatas; satu regresi konsolidasi juga masih menjadi
gate akhir. Natural chat LLM belum dilaporkan. Stage 4 masih OPEN, Stage 5–8 belum selesai.
Stage 3 pada assistant-status adalah label lama, bukan schema aktual.

## Catatan historis saat paket kandidat runtime dibuat

**Stage 4 masih OPEN. Stage 5–8 belum selesai. Paket ini belum diterima untuk produksi.**
Schema kandidat: `0008_executor_binding`. Target akhir tetap Stage 8; tidak ada stage
atau penerimaan produksi yang ditandai selesai hanya karena dokumentasinya tersedia.
Tidak ada akun Telegram/Google/LLM nyata yang dipanggil atau server pengguna yang diubah.

## Pemulihan sesi

Baseline berasal dari `kuro-main (2).zip` dan catatan proyek pengguna. Ekstraksi, audit
kode, perbaikan natural chat, serta batas otorisasi tidak diulang dari awal. Regresi
native sempat berhasil pada revisi sebelum sambungan Calendar baru: **389 tes dan
81 subtes lulus**, termasuk PostgreSQL 16.15, RLS, Qdrant 1.19.1, OCR, upgrade data
lama, dan migrasi dua kali. Log serta XML-nya disimpan di `docs/evidence/stage-4g/`.

Iterasi awal migrasi 0007 juga selesai dengan exit code 0 menurut catatan runner,
tetapi log rinci di `/tmp` tidak bertahan saat sesi berganti. Hasil itu tidak dipakai
sebagai bukti penerimaan kandidat akhir. Yang terputus kemudian adalah regresi unit
terakhir, penyimpanan bukti dan paket akhir; semuanya dilanjutkan dari file yang ada.

## Implementasi yang sekarang tersedia

- Natural chat tetap melalui pairing, privacy filter, queue dan premium consent
  yang sama dengan `/ask`; pesan yang diawali email atau `@handle` tidak hilang.
- Worker memanggil routing Calendar sebelum inference: read hari ini/besok/tanggal,
  solo create lengkap, proposal undangan dan penghapusan berdasarkan ID. Perintah
  yang belum lengkap meminta detail. Calendar yang dikenali tidak dikirim ke LLM.
- Read dan write Calendar masuk journal. Hanya scheduler memiliki secret Google.
  Eksekusi write melalui `ToolRuntime` langsung ditolak.
- Grant specialist tersimpan, owner/scope/revision/source diperiksa pada dispatch.
  Perubahan scope membatalkan authority lama; perubahan akun/refresh token/calendar
  membuat executor binding tidak cocok sampai operator mengatur grant baru.
- Source-step key unik mencegah antrean ganda. ID Google create berasal dari ID
  action yang stabil. Respons create harus merujuk ID yang sama.
- Result provider disimpan. Heartbeat assistant menerbitkan hasil ke outbox dari
  journal, tanpa mengulang eksekusi provider atau membuat klaim melalui LLM.
- `/toolapprove ID FINGERPRINT` terpisah dari `/approve` premium. Approval terikat
  action immutable, TTL, dan sekali pakai. Flag approval mentah ditolak journal.
- `/cancel` membatalkan action pre-dispatch; aksi in-flight tidak diklaim ditarik
  kembali. `/toolstatus ID` membaca status milik owner.
- Lease dispatch mencakup timeout; scheduler berhenti mengambil action baru saat
  shutdown. Dispatch ambigu menjadi uncertain dan tidak diulang otomatis.
- `tools-reconcile` memeriksa solo create uncertain lewat GET ID stabil, judul,
  serta instant mulai/selesai; tidak mengirim POST ulang. Invite/update/delete
  uncertain tetap memerlukan pemeriksaan manual.
- Validasi tipe, timestamp ber-offset, zona, durasi, ID dan attendee; pembatasan
  pagination/ukuran respons; HTTP client menolak redirect dan proxy environment.
- `tools-status` memuat hitungan status, umur antrean dan heartbeat; overlay
  Calendar memiliki healthcheck. Ini baru sebagian fondasi monitoring Stage 5.

## Hasil verifikasi kandidat akhir

| Pemeriksaan | Hasil dan batas |
|---|---|
| Unit + offline | 366 tes, 83 subtes lulus; tidak ada tes dilewati |
| Ruff lint + format | Lulus |
| Sintaks Python | Diperiksa ulang pada file final |
| Alembic SQL offline sampai head 0008 | Berhasil dihasilkan; bukan pengganti eksekusi native |
| Tes integrasi ditemukan | 78; termasuk 12 kasus Calendar chat baru |
| Regresi native lama | 389 tes/81 subtes lulus; bukti historis sebelum perubahan runtime terbaru |
| Regresi native kandidat akhir | BLOCKED oleh lingkungan; belum diterima |
| Google/Telegram nyata, Docker build final, restore, deploy | Belum dijalankan |

Lingkungan terbaru hanya memetakan UID 0. PostgreSQL menolak dijalankan sebagai root;
UID non-root tidak tersedia dan Docker tidak terpasang. Percobaan eskalasi ditolak
oleh kebijakan izin otomatis (`sandbox_approval: false`). Pemeriksaan PostgreSQL
non-root tidak dinonaktifkan dan database palsu tidak dipakai untuk mengklaim native
pass. Gate baru harus dijalankan pada lingkungan Docker/CI atau PostgreSQL uji yang
memang diizinkan sebelum penerimaan Stage 4.

## Yang masih harus diselesaikan

Stage 4: jalankan dan perbaiki gate native kandidat akhir; production smoke Calendar
pada kalender uji; clarification/follow-up yang lebih bebas; penjadwalan tertunda
melalui percakapan; verifikasi penerimaan seluruh skenario pada versi yang sama.
Bahasa yang didukung masih berupa vertical slice terbatas, bukan planner umum.

Stage 5: deploy target nyata, alert eksternal, backup lengkap terenkripsi, restore
terukur, rollback, secret rotation dan disaster recovery. Backup lokal legacy masih
hanya pg_dump tanpa enkripsi; jangan menganggapnya backup produksi lengkap.

Stage 6: memory proyek/preference/relevance/retention belum ditambahkan penuh. Profil
serta riwayat baseline tetap ada. Catatan tindakan Calendar tersimpan terpisah dari
`/clear`; kebijakan redaksi/retensinya masih merupakan gate terbuka.

Stage 7: keenam specialist belum selesai. Stage 8: DAG planner, durable multi-step,
natural follow-up lintas agent dan routing local/cloud belum selesai. Registry dan
checklist tidak dihitung sebagai implementasi specialist.

## Mulai sesi berikutnya dari sini

1. Baca `docs/RESUME_CHECKPOINT.md` dan `docs/STAGE_4G_CALENDAR_CHAT.md`.
2. Jalankan gate native kandidat ini pada lingkungan yang mendukung; jangan
   mengulang ekstraksi/audit baseline atau memakai nested ZIP lama sebagai baseline.
3. Simpan XML/log dan perbaiki kegagalan yang ditemukan. Bekukan Stage 4 hanya setelah
   acceptance nyata, kemudian lanjutkan operasi Stage 5 dan Stage 6–8.
4. Target hosting/provider specialist belum ditentukan. Secret dipasang melalui
   file privat pada lingkungan target, tidak ditempelkan ke percakapan.
