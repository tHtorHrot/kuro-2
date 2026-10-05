# Calendar chat — kandidat vertical slice

Status: diimplementasikan dan unit-tested; gate native/final deployment masih terbuka.
Baca DEVELOPMENT_STATUS.md terlebih dahulu. Contoh di bawah hanya untuk staging
setelah gate teknis lulus. Tidak ada aktivasi akun nyata yang dilakukan oleh paket.

## Jalur runtime

Telegram private/pairing → AssistantRequest → deterministic proposal + trusted
binder → ActionJournal → scheduler dengan secret Google → result tersimpan →
assistant heartbeat → Telegram receipt/outbox. Assistant tidak membaca OAuth secret.
Tidak ada panggilan LLM pada perintah Calendar yang dikenali.

Contoh yang dikenali:

```text
apa jadwalku besok?
jadwalku 2026-10-05
buat rapat "Review" pada 2026-10-05 jam 10:00 sampai 11:00 zona Asia/Jakarta
buat rapat "Review" pada 2026-10-05 jam 10:00 sampai 11:00 zona Asia/Jakarta undang a@example.com
hapus acara ID_EVENT
```

Read memakai zona owner dan waktu pesan semula, sehingga restart melewati tengah
malam tidak mengubah arti “besok”. Solo create lengkap memiliki authority langsung
dari teks yang cocok. Undangan dan penghapusan selalu memerlukan persetujuan exact
action. “buat rapat besok jam 10” meminta detail; belum ada dialog slot-filling
multi-turn. Update Calendar tersedia pada service tetapi belum memiliki grammar chat.

`/toolapprove ID FINGERPRINT` menyetujui proposal Calendar. `/approve KODE` hanya
premium inference. `/cancel` menghentikan pekerjaan pre-dispatch. `/toolstatus ID`
melaporkan status owner-scoped. Belum ada daftar tugas/dashboard umum.

## Gate pada komputer atau CI terisolasi

Jalankan dari direktori kandidat yang terpisah dari instalasi produksi:

```powershell
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
$testExitCode = $LASTEXITCODE
docker compose -f compose.test.yaml logs --no-color tests | Out-File -Encoding utf8 calendar-test.log
docker compose -f compose.test.yaml down --volumes
if ($testExitCode -ne 0) { throw 'Gate gagal; jangan rollout' }
```

`--volumes` hanya digunakan pada project test disposable yang terpisah. Jangan
menambahkan file Compose produksi ke perintah test ini. Tes provider memakai mock;
PostgreSQL/Qdrant/OCR nyata berjalan di container. Native final belum dijalankan oleh
sesi ini karena pembatasan lingkungan, bukan karena tes dilewati lalu dihitung lulus.

## Aktivasi staging setelah gate lulus

Gunakan owner dan pairing yang sudah ada, bukan menjalankan setup ulang. Pasang
Google client ID/secret/refresh token melalui secret files yang disebut pada
STAGE_4E_CALENDAR_ACTIVATION.md. Pilih kalender uji dan OAuth scope minimum. Atur
`JARVIS_GOOGLE_CALENDAR_ID` pada overlay staging ke kalender uji; jangan mengubah akun
saat queue lama aktif tanpa rekonsiliasi.

Setelah migration dan runtime siap, atur grant eksplisit dengan secret scheduler:

```powershell
$env:JARVIS_OWNER_ID = '<UUID owner staging yang sudah ada>'
docker compose -f compose.yaml -f compose.calendar.yaml run --rm --no-deps scheduler tools-grant --owner-id $env:JARVIS_OWNER_ID --scope calendar:read --scope calendar:write
docker compose -f compose.yaml -f compose.telegram.yaml -f compose.assistant.yaml -f compose.calendar.yaml up -d telegram assistant scheduler
```

Grant tersebut belum memberikan `calendar:send`. Tambahkan scope itu hanya ketika
fitur undangan memang hendak diterima. Scope tidak menggantikan persetujuan setiap
undangan. Mengubah grant selalu menaikkan revisi; action berizin lama tidak hidup
kembali ketika scope kemudian diberikan lagi.

```powershell
docker compose -f compose.yaml -f compose.calendar.yaml exec scheduler jarvis tools-status --owner-id $env:JARVIS_OWNER_ID
docker compose -f compose.yaml -f compose.calendar.yaml exec scheduler jarvis scheduler-health --owner-id $env:JARVIS_OWNER_ID
docker compose -f compose.yaml -f compose.calendar.yaml run --rm --no-deps scheduler tools-grant --owner-id $env:JARVIS_OWNER_ID --disable
```

Menonaktifkan grant mencegah dispatch berikutnya. Eksekusi yang telah mengirim request
ke provider tetap dapat menghasilkan efek. Healthcheck menunjukkan heartbeat, bukan
bukti OAuth valid atau semua pekerjaan sukses. Status failed/uncertain dan umur
antrean harus diamati terpisah.

## Recovery

Source key mengikat request/step dan ID provider create memakai `kuro` + UUID action
hex. Hal ini bukan klaim exactly-once universal. Timeout, ID conflict, atau proses
mati setelah dispatch tetap uncertain dan tidak diulang otomatis.

Solo create dapat diperiksa dengan operasi GET saja:

```powershell
docker compose -f compose.yaml -f compose.calendar.yaml run --rm --no-deps scheduler tools-reconcile --owner-id $env:JARVIS_OWNER_ID --action-id '<UUID aksi uncertain>'
```

Rekonsiliasi hanya berhasil jika ID, judul dan instant waktu cocok serta event tidak
cancelled. Tidak ditemukan/mismatch tetap uncertain. Invite/update/delete belum
memiliki reconciliation otomatis. Jangan membuat ulang aksi uncertain tanpa lebih
dulu memeriksa kemungkinan efek eksternal yang telah terjadi.

## Batas yang masih terbuka

- Belum ada smoke Google nyata; credential, target dan approval penerima belum tersedia.
- Interface jadwal eksekusi `due_at` lewat percakapan belum lengkap. Jangan menyamakan
  tanggal event dengan waktu scheduler harus menjalankan tindakan.
- Journal action/result terpisah dari `/clear`; redaksi/retensi perlu diselesaikan.
- Provider error pra-POST tertentu masih diperlakukan konservatif sebagai uncertain.
- Restore, encrypted offsite backup, alert eksternal dan rollback belum diterima.
- Network bridge bukan firewall domain; batas origin HTTP berada pada client aplikasi.

Referensi implementasi ID event dan pagination: dokumentasi resmi Google Calendar
[Events.insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)
dan [Events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list),
diperiksa selama pengembangan. ID stabil harus tetap disertai journal dan reconciliation.
