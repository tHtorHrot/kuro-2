# Sambungkan Google Calendar dengan akses baca

Pembaruan 4 Oktober 2026: OAuth, grant baca dan scheduler pada instalasi pengguna
sudah berhasil; hasil jadwal bot dilaporkan cocok. Langkah 1–3 di bawah adalah panduan
setup awal, bukan langkah yang perlu diulang pada instalasi aktif. Patch tampilan
agenda sudah diterima pengguna. Berikutnya ikuti `docs/STAGE4_WRITE_ACCEPTANCE.md`
untuk kandidat akses tulis terpisah dan smoke terarah; jangan mengulang setup baca.

Untuk instalasi aktif `A:\Kuro2\kuro-main`, project Docker `personal-jarvis`, schema
`0008_executor_binding`. Pengguna sudah melaporkan 444 tes Docker lulus, migrasi dan
doctor sukses, serta assistant sehat. Routing Calendar sudah merespons bahwa koneksi
belum aktif. Tidak perlu setup database, migrasi atau rebuild runtime untuk helper ini.

Helper baru `scripts/setup_calendar.py` memakai standard library Python. Jalankan pada
Windows yang memiliki browser. Login dilakukan ke Google; callback hanya mendengarkan
127.0.0.1 pada port acak, memakai state dan PKCE S256. Token tidak dicetak, tidak masuk
chat/LLM, dan tidak dikirim ke server proyek lain. Endpoint token tetap milik Google;
endpoint yang tercantum di JSON tidak digunakan sebagai tujuan HTTP.

## 1. Siapkan aplikasi OAuth milik sendiri

1. Buka https://console.cloud.google.com/ dan buat/pilih project khusus `KURO Personal`.
2. Aktifkan **Google Calendar API** melalui **APIs & Services > Library**.
3. Buka **Google Auth platform > Branding**, isi nama `KURO Personal`, email dukungan,
   dan email kontak. Untuk akun Gmail pribadi pilih **External** pada Audience.
   Biarkan status Testing untuk percobaan dan tambahkan akun Google yang akan digunakan
   sebagai **Test user**. Internal hanya untuk organisasi Workspace yang sesuai.
4. Pada **Data Access**, tambahkan satu scope ini:

   `https://www.googleapis.com/auth/calendar.events.owned.readonly`

   Scope ini membaca event kalender yang dimiliki akun. Kalender bersama milik orang
   lain tidak termasuk. Izin tulis dan kirim undangan belum diminta.
5. Buka **Clients > Create client > Desktop app**, beri nama `KURO Local Calendar`,
   buat client, dan unduh JSON. Jangan memilih Web application atau service account.
6. Simpan JSON sebagai:

   `A:\Kuro2\kuro-main\.secrets\google_oauth_client.json`

Gunakan folder lokal privat, bukan folder yang dibagikan/sinkronisasi publik. Pada
Windows, perlindungan akses mengikuti ACL NTFS direktori `.secrets` yang sudah ada;
helper ini tidak mengubah ACL Windows. File bukan otomatis terenkripsi oleh Docker.
Jangan kirim JSON, client secret, refresh token, atau URL callback ke percakapan ini.

## 2. Jalankan login lokal

```powershell
cd A:\Kuro2\kuro-main
python .\scripts\setup_calendar.py
```

Browser membuka Google. Pilih akun pemilik kalender yang memang hendak dihubungkan,
pastikan aplikasi dan akses baca sesuai, lalu beri persetujuan. Periksa hasil akhir
di PowerShell; pesan callback di browser hanya menyatakan respons login sudah diterima.
Sukses menghasilkan `calendar_credentials_saved: true` dan tiga file:

- `.secrets/google_client_id`
- `.secrets/google_client_secret`
- `.secrets/google_refresh_token`

Tidak ada nilai credential dicetak. Helper belum menjalankan Calendar API, grant atau
scheduler. File yang sudah ada tidak ditimpa; ini setup pertama, bukan rotasi otomatis.
Jika proses gagal, jangan menjalankan aktivasi di bawah. Laporkan kode error saja.
Ketika izin ditolak atau callback tidak sah, helper tidak menyimpan credential.

Jika proses dimatikan paksa, lock kosong `.secrets/.calendar-setup.lock` dapat tertinggal.
Pastikan semua proses setup sudah ditutup sebelum menghapus hanya lock kosong tersebut.
Jangan menghapus token existing untuk mengatasi lock. Rotasi/perluasan scope harus
meninjau antrean, menghentikan scheduler dan memperbarui binding/grant secara terencana.

## 3. Aktifkan satu grant baca dan scheduler

Blok ini menggunakan kalender `primary` sesuai overlay yang telah dikirim. Ini hanya
membaca kalender utama akun yang dipilih. Jangan menjalankan grants berulang tanpa
alasan: setiap perubahan grant menaikkan revisi dan membatalkan authority antrean lama.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'A:\Kuro2\kuro-main'
    $config = Get-Content -Raw -LiteralPath '.\.secrets\telegram_config.json' | ConvertFrom-Json
    $env:JARVIS_OWNER_ID = ([guid]$config.owner_id).ToString()
    $kuroCalendarArgs = @(
        '-p', 'personal-jarvis',
        '-f', 'compose.yaml',
        '-f', 'compose.telegram.yaml',
        '-f', 'compose.assistant.yaml',
        '-f', 'compose.knowledge.yaml',
        '-f', 'compose.calendar.yaml'
    )
    function Invoke-KuroCalendar {
        & docker compose @kuroCalendarArgs @args
        if ($LASTEXITCODE -ne 0) { throw 'Langkah Calendar gagal; periksa error di atas.' }
    }
    Invoke-KuroCalendar config --quiet
    Invoke-KuroCalendar run --rm --no-deps scheduler tools-grant --owner-id $env:JARVIS_OWNER_ID --scope calendar:read
    Invoke-KuroCalendar up -d --no-deps --no-build --wait --wait-timeout 180 scheduler
    Invoke-KuroCalendar exec -T scheduler jarvis tools-status --owner-id $env:JARVIS_OWNER_ID
}
```

Status yang diharapkan: `calendar_enabled: true`, `worker_recent: true`. Heartbeat
hanya membuktikan worker berjalan; akses OAuth diuji dengan permintaan baca berikut.

## 4. Uji hasil nyata

Kirim `apa jadwalku besok?` di chat privat dengan bot. Hasil harus berupa daftar acara
atau keterangan tidak ada acara sesuai kalender utama akun yang dipilih. Bandingkan
dengan Google Calendar untuk tanggal dan zona waktu yang sama. Tindakan create, delete,
dan undangan belum diizinkan oleh grant maupun scope OAuth ini.

Hasil Calendar dikirim ke chat Telegram dan disimpan di journal action; saat ini
`/clear` belum meredaksi journal tersebut. Retensi action/result tetap gate terbuka.
Kirim status yang tidak berisi secret serta apakah hasil cocok. Judul acara pribadi
boleh disamarkan. Balasan Halo dari LLM belum dilaporkan pada checkpoint ini.

## Batas pengujian dan produksi

- Helper: 35 tes lokal termasuk loopback HTTP, PKCE, state, scope, token response,
  non-overwrite, kegagalan simpan, lock dan newline. Live OAuth/Windows browser belum
  dijalankan oleh asisten; keberhasilan ditentukan dari hasil pada komputer pengguna.
- Token untuk aplikasi External berstatus Testing dengan scope Calendar berlaku
  sekitar tujuh hari menurut kebijakan Google. Ini belum koneksi produksi permanen.
  Publikasi, verifikasi yang berlaku, pencabutan akses, rotasi dan recovery perlu
  diselesaikan sebagai penerimaan Stage 5; jangan menganggap status sehat menjamin token
  tidak akan dicabut atau kedaluwarsa.
- Peningkatan ke izin tulis dilakukan setelah read E2E diterima. Scope Google dan grant
  internal merupakan dua pemeriksaan terpisah. Undangan tetap memerlukan approval tiap aksi.
- Browser login, persetujuan akun dan kepatuhan kebijakan administrator dilakukan pengguna.
  Jangan mematikan pembatasan akun/admin untuk memaksa login.

Referensi resmi, diperiksa 4 Oktober 2026:

- https://developers.google.com/workspace/calendar/api/quickstart/python
- https://developers.google.com/workspace/guides/configure-oauth-consent
- https://developers.google.com/workspace/calendar/api/auth
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/identity/protocols/oauth2#expiration
