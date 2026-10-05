# Upgrade Windows: Tahap 1 → Tahap 2A

Versi 0.2.0, 28 September 2026. Panduan ini untuk instalasi yang API-nya sudah ready,
owner sudah dibuat, bearer tanpa izin ditolak, dan bearer pengganti menghasilkan HTTP 200.
Tujuannya mengaktifkan **transport Telegram privat**, belum percakapan AI.

## 1. Ekstrak dan uji paket

Ekstrak isi ZIP langsung ke `A:\jarvis-stage-1`, sehingga `compose.yaml`, `src`, `scripts`,
dan `docs` berada pada tingkat yang sama seperti sebelumnya. Setujui penggantian file
**sumber** yang sama. Paket tidak berisi `.secrets`, `.env`, database, atau backup; pertahankan
semua file tersebut dari instalasi lama. Jangan ekstrak ke subfolder `jarvis-stage-2a`.
Nama proyek Compose tetap `personal-jarvis` agar volume lama tetap digunakan.

Buka PowerShell di direktori itu dan jalankan:

```powershell
cd A:\jarvis-stage-1
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

Ini menggunakan proyek **personal-jarvis-tests**, database `jarvis_test` sementara,
dan Telegram mock. Tidak memerlukan token Telegram dan tidak membaca `.secrets` produksi.
Hasil yang diperlukan: seluruh tes lulus, tanpa skip integrasi. Jumlah dan batas verifikasi
ada di `docs/STAGE_2A_VERIFICATION.md`. Bila gagal, berhenti di sini dan kirim ringkasan
error yang telah diperiksa tidak memuat secret. Tidak perlu menjalankan setup/migrasi dahulu.

Setelah hasil test berhasil, bersihkan **cluster test saja**:

```powershell
docker compose -f compose.test.yaml down --volumes
```

Jangan menghilangkan `-f compose.test.yaml` dari perintah pembersihan tersebut.

## 2. Backup lokal dan upgrade API

Pastikan PostgreSQL lama sedang berjalan. Simpan salinan kode versi lama jika ingin
memiliki referensi pemulihan. Jalankan backup sebelum migrasi:

```powershell
python scripts/backup_local.py
```

Harus menghasilkan JSON berisi lokasi file `.dump` dalam `backups`. Script memakai
`pg_dump` format custom melalui Python agar byte biner tidak diubah PowerShell. Backup
ini **belum dienkripsi** dan bukan backup luar host; simpan folder dengan ACL akun pribadi,
bukan folder sinkronisasi publik. Perlindungan BitLocker bila tersedia membantu melindungi
storage host. Bukti restore lengkap tetap menjadi gate deployment produksi.

Jika backup gagal, perbaiki sebelum melanjutkan. Jangan menjalankan ulang `setup_local.py`
untuk upgrade, membuat owner baru, mengubah pepper, atau menghapus volume database.
File `.secrets\windows_api_token.xml` yang sudah dibuat tetap dipertahankan.

Build dahulu agar downtime singkat, kemudian hentikan API lama dan terapkan migrasi:

```powershell
docker compose build api migrate
docker compose stop api
docker compose up -d --no-build --wait --wait-timeout 180 api
docker compose --profile ops run --rm --no-deps ops doctor
docker compose port api 8000
curl.exe --noproxy "*" --connect-timeout 5 --max-time 10 --fail http://127.0.0.1:8000/health/ready
```

`doctor` harus menampilkan database ready, RLS enabled_and_forced, stage `2a`.
Port harus `127.0.0.1:8000`; readiness `{"status":"ready"}`.
Migrasi menambah dua tabel dan indeks, tidak menghapus user/token/data lama.
Jika migrasi gagal, jangan menghapus volume. Gunakan `docker compose logs --tail=60 migrate`.
Jika migrasi sudah berhasil, binary Tahap 1 tidak boleh langsung digunakan untuk rollback:
readiness-nya mengharapkan revision lama. Gunakan perbaikan maju atau prosedur restore
terisolasi yang sudah diuji.

Uji `/api/v1/me` lagi menggunakan bearer pengganti melalui cara aman yang sudah dipakai.
Jangan menempelkan bearer pada perintah yang disimpan di history atau membagikan nilainya.
Tanpa bearer harus tetap 401. Token pengganti tetap memiliki masa berlaku semula.

## 3. Buat bot khusus dan konfigurasi tersembunyi

Pada Telegram, buka **@BotFather resmi**, jalankan `/newbot`, dan buat bot khusus Jarvis.
Gunakan pengaturan BotFather untuk menonaktifkan kemampuan masuk grup dan pertahankan
privacy mode aktif. Gate server tetap menolak grup, apa pun pengaturan bot.
Bot ini tidak boleh dipakai oleh aplikasi/poller lain atau memiliki webhook aktif.

Di PowerShell, tentukan UUID owner lama (ini ID, bukan token):

```powershell
$ownerId = Read-Host "Owner ID lama (UUID)"
python scripts/setup_telegram.py --owner-id $ownerId
```

Alur setup:

1. Masukkan token dari BotFather pada prompt **hidden**. Tidak ada karakter yang ditampilkan;
   ini normal. Token tidak dikirim ke chat bantuan ini, tidak dimasukkan pada argv/history.
2. Script memeriksa bot melalui API Telegram. Buka username bot yang ditampilkan.
3. Kirim challenge `/jarvis_setup ...` yang dicetak script ke **chat pribadi bot sendiri**.
4. Kembali ke PowerShell, tekan Enter, lalu ketik ulang ID Telegram numerik yang terdeteksi.
5. Script menyimpan dua file lokal: `.secrets\telegram_bot_token` dan
   `.secrets\telegram_config.json`. Kredensial database/pepper/API tidak diubah.

Challenge setup tidak mengaktifkan pairing dan bukan bearer API. ID numerik akun
Telegram menjadi allowlist; nama tampilan dan username tidak dipakai untuk otorisasi.
File yang sudah ada tidak ditimpa. Script menolak input token jika terminal tidak dapat
menyembunyikan ketikan. Jalankan dari terminal PowerShell interaktif biasa.

BotFather/Telegram sudah memproses pesan yang dikirim lewat layanannya. Jangan memakai
jalur ini untuk dokumen sensitif. Tidak ada panggilan model AI pada tahap ini.

## 4. Mulai worker dan pairing

Gunakan array argumen PowerShell agar overlay selalu konsisten pada operasi Telegram:

```powershell
$tg = @('-f', 'compose.yaml', '-f', 'compose.telegram.yaml')
docker compose @tg config --quiet
docker compose @tg --profile telegram up -d --no-build --wait --wait-timeout 180 telegram
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-status
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-pair
```

Worker tidak membuka port baru. `telegram-status` pertama dapat menunjukkan `paired:false`
sementara `worker_recently_polled:true`; itu normal sebelum pairing.
Perintah terakhir menampilkan `pairing_command`. Salin nilai `/pair ...` **sekali** ke chat
pribadi bot sendiri. Kode berlaku sepuluh menit, terikat ID yang dikonfigurasi, maksimum
lima percobaan. Kode ini sengaja ditampilkan sekali untuk pairing; jangan membagikan outputnya.

Setelah bot membalas “Pairing berhasil”, kirim `/status`, `/privacy`, lalu `/help`.
`/status` menjelaskan bahwa model AI dan dokumen belum aktif.
Perintah yang didukung: `/start`, `/help`, `/pair KODE`, `/status`, `/privacy`.
Teks biasa/file/voice belum diproses; file tidak diunduh oleh Jarvis.

Jika pairing sebenarnya sudah berhasil tetapi balasan hilang karena timeout, kirim
`/status` baru dan periksa CLI status. Jangan menggandakan owner atau mengulang setup.

## 5. Validasi penerimaan

| Uji | Hasil yang diharapkan |
|---|---|
| CLI `telegram-status` | owner_active, paired, identity_enabled, worker_recently_polled semuanya true; llm_active false |
| `/status` dari akun terikat | Balasan Tahap 2A |
| `/privacy` | Penjelasan batas privasi Telegram dan penyimpanan |
| Akun Telegram lain ke bot | Tidak ada balasan; tidak dapat pairing |
| Forward perintah / pesan grup | Tidak dilayani |
| Restart worker | Tidak perlu pairing ulang; `/status` baru berhasil |
| Bearer API lama yang dicabut | 401; bearer pengganti tetap 200 |
| `docker compose ps` | API hanya localhost, PostgreSQL tanpa published port; worker tanpa port masuk |

Uji restart:

```powershell
docker compose @tg restart telegram
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-status
```

Tunggu satu siklus polling jika heartbeat belum terbaru. Uji akun lain hanya bila tersedia;
jangan mengundang orang lain mengirim data pribadi untuk pengujian.

## Operasi dan penghentian

```powershell
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-status
docker compose @tg logs --tail=60 telegram
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-disable
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-enable
docker compose @tg stop telegram
```

Disable menghentikan otorisasi balasan berikutnya; pengiriman yang sudah berjalan mungkin
sudah diterima Telegram. Untuk insiden, hentikan worker dan cabut token bot melalui
BotFather. Jangan mengaktifkan kembali identitas sampai penyebabnya diperiksa.

Untuk berhenti sekaligus tanpa menghapus volume:

```powershell
docker compose @tg stop telegram api postgres
```

Komputer harus menyala, Docker berjalan, dan koneksi internet tersedia agar bot online.
Worker memakai kebijakan restart `on-failure:5`; periksa status dan start kembali bila
berhenti. Healthcheck yang unhealthy bukan jaminan Docker otomatis memperbaikinya.

## Troubleshooting aman

| Gejala | Tindakan |
|---|---|
| 401 / unauthorized saat setup atau worker | Periksa token secara lokal; jika dicabut, ganti melalui prosedur rotasi. Jangan kirim token untuk diagnosis |
| webhook_present / poller_conflict | Gunakan satu bot khusus dan satu poller; jangan otomatis menghapus webhook aplikasi lain |
| Matching identity/config error | Jangan mengganti ID pengirim/bot pada instalasi yang sudah dipasangkan; migrasi identitas belum didukung tahap ini |
| Rate limited | Tunggu `retry_after`; antrean tidak boleh dibypass dengan restart berulang |
| Delivery `uncertain` | Hasil kirim tidak diketahui. Tidak otomatis diulang; kirim perintah baru bila perlu |
| pending menjadi expired | Antrean balasan berumur lebih dari 10 menit tidak dikirim sebagai balasan basi |
| No recent successful poll | Periksa internet, DNS, jam host, database, dan log aman; tidak perlu mencetak secret |
| Tidak ada balasan setelah setup | Mulai worker, buat kode pairing, pastikan akun/chat sesuai allowlist |
| CLI status belum paired | Pairing belum committed; buat kode baru jika kedaluwarsa |

Rotasi token untuk **bot yang sama**: stop worker, revoke/generate token di BotFather,
ganti `.secrets\telegram_bot_token` melalui editor lokal privat dengan satu baris token,
bukan lewat argv/history. Pertahankan config/ID. File read-only mungkin perlu atribut
read-only dilepas sementara lalu dipasang kembali. Recreate worker dengan
`docker compose @tg --profile telegram up -d --no-build --force-recreate --wait telegram`.
Perubahan bot atau akun memerlukan migrasi identitas tersendiri; jangan mengedit database
secara coba-coba atau menghapus volume.

## Yang dikirim untuk validasi tahap ini

Cukup ringkasan tes, output `doctor`, output `telegram-status`, dan keterangan apakah
`/status`, penolakan akun lain, serta restart berhasil. Jangan sertakan token BotFather,
bearer, kode pairing, file `.secrets`, dump, atau isi dokumen.
