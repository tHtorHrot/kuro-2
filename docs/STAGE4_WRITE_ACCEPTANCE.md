# Stage 4 — uji tulis, antrean dan persetujuan

Checkpoint 4 Oktober 2026: pengguna telah menerima Calendar read dan format agenda
di bot. Assistant healthy/config_matches/worker_recent true. Image yang sudah ada
memiliki implementasi create, delete, approval dan scheduler. Patch ini mengubah helper
OAuth lokal serta menambah overlay kandidat; tidak memerlukan build image atau migrasi.

## 1. Siapkan izin tulis sebagai kandidat terpisah

Ekstrak isi `KURO-Stage4-Write-Acceptance.zip` ke `A:\Kuro2\kuro-main`, gabungkan folder
dan timpa file patch bernama sama. Jalankan dari direktori itu.

Pada project Google yang sudah dipakai, buka **Google Auth platform > Data Access**.
Tambahkan scope `https://www.googleapis.com/auth/calendar.events.owned`. Ini mengizinkan
baca, buat, ubah dan hapus acara pada kalender yang dimiliki akun. Login berikut harus
menggunakan akun pemilik kalender yang sama seperti uji baca.

```powershell
cd A:\Kuro2\kuro-main
python .\scripts\setup_calendar.py --access write
```

Helper membuka persetujuan Google yang baru. Baca akses yang ditampilkan, lalu setujui
bila sesuai. Hasil yang diharapkan: `calendar_credentials_saved: true`,
`candidate_only: true`, `directory: .secrets/calendar_write`, dengan scope owned di atas.
Tiga credential disimpan terpisah di `.secrets/calendar_write`; credential sebelumnya
di `.secrets` tetap tersedia. Tidak ada grant, scheduler atau Calendar API yang
dijalankan oleh helper. Jangan menghapus file existing bila helper menolak overwrite.

Kandidat belum dipakai sampai langkah aktivasi berikut. Scope Google ini lebih luas
daripada baca saja; batas izin internal tetap diperiksa sebelum setiap aksi.

## 2. Aktifkan kandidat setelah antrean kosong

Jangan kirim permintaan bot selama pergantian ini. Jalankan blok sekali setelah login
berhasil. Blok memeriksa antrean sebelum dan sesudah menghentikan scheduler. Jika ada
queued/claimed/dispatching/awaiting_approval/uncertain, ia berhenti sebelum mengganti
grant. Selesaikan atau rekonsiliasi tindakan tersebut dahulu; jangan mereset database.

`$access = 'write'` memilih kandidat. Untuk kembali ke credential baca lama, gunakan
blok yang sama dengan `$access = 'read'`, setelah antrean kembali kosong.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'A:\Kuro2\kuro-main'
    $access = 'write'
    if ($access -notin @('read', 'write')) { throw 'Pilihan akses tidak dikenal.' }
    $config = Get-Content -Raw '.\.secrets\telegram_config.json' | ConvertFrom-Json
    $env:JARVIS_OWNER_ID = ([guid]$config.owner_id).ToString()
    $kuroAccessArgs = @(
        '-p', 'personal-jarvis',
        '-f', 'compose.yaml',
        '-f', 'compose.telegram.yaml',
        '-f', 'compose.assistant.yaml',
        '-f', 'compose.knowledge.yaml',
        '-f', 'compose.calendar.yaml'
    )
    if ($access -eq 'write') {
        $kuroAccessArgs += @('-f', 'compose.calendar.write.yaml')
    }
    function Invoke-KuroAccess {
        & docker compose @kuroAccessArgs @args
        if ($LASTEXITCODE -ne 0) { throw 'Langkah aktivasi gagal; periksa error di atas.' }
    }
    function Assert-KuroCalendarIdle {
        $raw = Invoke-KuroAccess run --rm --no-deps scheduler tools-status --owner-id $env:JARVIS_OWNER_ID
        $state = ($raw -join "`n") | ConvertFrom-Json
        if ($null -eq $state.actions) { throw 'Status antrean tidak dapat diverifikasi.' }
        foreach ($name in @('queued', 'claimed', 'dispatching', 'awaiting_approval', 'uncertain')) {
            if ($state.actions.$name -gt 0) {
                throw "Masih ada tindakan $name. Selesaikan dahulu sebelum pergantian akses."
            }
        }
    }
    Invoke-KuroAccess config --quiet
    Assert-KuroCalendarIdle
    Invoke-KuroAccess stop scheduler
    Assert-KuroCalendarIdle
    $grantArgs = @(
        'run', '--rm', '--no-deps', 'scheduler', 'tools-grant',
        '--owner-id', $env:JARVIS_OWNER_ID, '--scope', 'calendar:read'
    )
    if ($access -eq 'write') { $grantArgs += @('--scope', 'calendar:write') }
    Invoke-KuroAccess @grantArgs
    Invoke-KuroAccess up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 scheduler
    Invoke-KuroAccess exec -T scheduler jarvis tools-status --owner-id $env:JARVIS_OWNER_ID
}
```

Hasil yang diharapkan: grant scopes `calendar:read` dan `calendar:write`, scheduler
healthy, calendar_enabled/worker_recent true. `calendar:send` tidak diberikan; undangan
ke pihak lain tetap tidak diaktifkan. Grant baru sengaja menaikkan revisi dan mengikat
token kandidat. Jangan mengulang blok bila sudah berhasil.

Jika berhenti pada pemeriksaan kedua, scheduler lama sudah berhenti dan grant belum
diganti oleh blok. `docker start personal-jarvis-scheduler-1` melanjutkan container itu.
Jika grant sudah berubah tetapi startup gagal, periksa status/error dahulu. Jangan
memaksa rollback saat ada tindakan uncertain atau mengganti grant berulang kali.

Setelah akses write aktif, **sertakan `-f compose.calendar.write.yaml` setelah overlay
Calendar pada perintah Compose berikutnya yang recreate scheduler**. Restart Docker
biasa memakai mount yang sudah disimpan pada container. Membuat ulang scheduler dengan
credential lain tanpa grant yang cocok akan ditolak binding executor.

## 3. Satu acara uji: antrean -> restart -> hasil

1. Hentikan hanya scheduler, tunggu command selesai dengan exit 0:

   ```powershell
   docker stop personal-jarvis-scheduler-1
   if ($LASTEXITCODE -ne 0) { throw 'Scheduler belum berhasil dihentikan.' }
   ```

2. Kirim **sekali** di chat privat bot (sesuaikan tanggal bila menjalankan panduan ini
   setelah 4 Oktober 2026):

   ```text
   buat acara "UJI KURO S4 - boleh dihapus" pada 2026-10-05 jam 09:00 sampai 09:05 zona Asia/Jakarta
   ```

   Scheduler berhenti, sehingga acara belum boleh muncul di Google Calendar.
   Tunggu sekitar 10 detik agar assistant sempat menyimpan permintaan ke antrean.
   Jangan mengirim ulang teks create sebagai pesan baru; pesan baru merupakan instruksi baru.

3. Hidupkan kembali container yang sama:

   ```powershell
   docker start personal-jarvis-scheduler-1
   if ($LASTEXITCODE -ne 0) { throw 'Scheduler belum berhasil dijalankan.' }
   ```

   Bot seharusnya mengonfirmasi create dengan ID event. Periksa Google Calendar: tepat
   satu acara, judul dan jam sesuai. Catat **ID event** dari balasan create untuk langkah
   berikutnya. ID ini berbeda dari ID tindakan pada perintah `/toolapprove`.

## 4. Buktikan cancel dan approval penghapusan

1. Kirim `hapus acara ID_EVENT_UJI`, ganti placeholder dengan ID hasil create di atas.
   Bot harus mengirim proposal persetujuan. Sebelum disetujui, acara masih ada.
2. Kirim `/cancel`. Pastikan acara tetap ada; pembatalan proposal bukan penghapusan acara.
3. Kirim `hapus acara ID_EVENT_UJI` lagi. Dari proposal baru, salin persis perintah
   `/toolapprove ID_TINDAKAN FINGERPRINT` yang diberikan bot.
4. Setelah persetujuan, bot mengonfirmasi penghapusan. Periksa bahwa hanya acara uji
   tersebut yang terhapus. Jangan menggunakan ID acara pribadi lain untuk tes ini.

Kirim ringkasan hasil: satu acara dibuat setelah restart, cancel mempertahankan acara,
delete menunggu approval lalu berhasil. Kirim status/error saja bila ada masalah;
jangan unggah credential atau JSON OAuth. Bila hasil dinyatakan uncertain, jangan
mengulang create: gunakan pemeriksaan/reconciliation yang sudah tersedia terlebih dahulu.

## Batas bukti dan langkah berikutnya

- Helper kini lulus 43 tes lokal, termasuk kandidat terpisah, scope minimum, penolakan
  scope berlebih, non-overwrite, symlink/lock, denial dan callback. Tidak ada panggilan
  Google/Calendar nyata dilakukan asisten pada tahap persiapan ini.
- Uji stop/start di atas membuktikan pemulihan antrean **sebelum dispatch**. Ia tidak
  menguji putus koneksi setelah Google menerima write. Kasus itu memiliki tes integrasi
  journal/reconciliation dengan provider mock; jangan mengklaim live fault injection.
- Full regression akhir pada source yang dipaketkan tetap gate sebelum freeze. Jangan
  menjalankan ulang 444 tes untuk setiap langkah kecil; lakukan satu gate konsolidasi.
- Klarifikasi bertahap, perintah chat penjadwalan eksekusi tertunda dan acceptance lengkap
  tetap ditinjau sebelum freeze sesuai `STAGE4_REMAINING.md`.
- Koneksi Google External/Testing masih mengikuti lifecycle token Google; solusi operasi
  tetap bagian Stage 5. Mengganti scope tidak menjadikannya koneksi produksi permanen.

Rujukan: https://developers.google.com/workspace/calendar/api/auth dan
https://developers.google.com/identity/protocols/oauth2/native-app.
