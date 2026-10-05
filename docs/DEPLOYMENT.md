# Rencana deployment dan runbook

## Jalur penerapan

| Langkah | Tindakan | Kriteria selesai |
|---|---|---|
| 1. Komputer lokal | Jalankan unit + Compose test dengan data contoh | Unit, RLS, integrasi auth/pairing, migrasi ulang lulus |
| 2. Smoke runtime | Build image runtime, generate secrets, start API | `doctor` dan readiness lulus, container non-root |
| 3. Pilih VPS | Bandingkan harga akhir, pajak, lokasi, RAM/disk, backup | Pengguna menyetujui total sesuai target sekitar Rp100 ribu |
| 4. Pasang fondasi | SSH key, firewall, Docker, secrets baru khusus server | API localhost, port database tertutup, tidak ada secret dari laptop dipublikasikan |
| 5. Terima operasional | Backup terenkripsi di luar host, uji restore, monitoring | Bukti restore dan restart, ruang disk cukup, checklist security selesai |
| 6. Tambah kemampuan | Telegram/model, lalu ingestion/tools | Setiap tahap lolos acceptance tests sebelum data nyata |

Tahap 1 belum memilih/membayar VPS dan belum mempublikasikan aplikasi. Diagram dan dokumen
menetapkan arah produksi; penerimaan produksi menunggu pemeriksaan yang belum dijalankan.

## Kapasitas dan biaya awal

Mulai dari satu vCPU dan sekitar 2 GB RAM untuk API/PostgreSQL fondasi, kemudian ukur
pemakaian. Compose membatasi API 384 MiB dan PostgreSQL 512 MiB; migrator/CLI sementara
juga memiliki batas 384 MiB. OS, filesystem cache, Docker, dan proses build memakai RAM
tambahan. Batas container adalah plafon, bukan janji ukuran server atau pemakaian aktual.

Gunakan build di komputer/CI jika VPS terlalu kecil untuk build. Jangan menaikkan replika,
menyalakan embedding, atau memasang seluruh observability stack sekaligus pada mesin kecil.
Qdrant/embedding nanti memerlukan pengukuran sendiri. Target ini tidak menjanjikan HA/SLA;
satu mesin merupakan titik kegagalan tunggal. Model cloud tidak memerlukan GPU di VPS.

Harga server belum dikunci. Periksa biaya termasuk pajak, backup, storage, bandwidth,
domain bila nanti perlu, dan kurs bila penagihan valas. Model premium tidak berjalan tanpa
persetujuan. Free tier dapat terbatas atau hilang. Nilai konfigurasi target biaya bukan
alat pemotong tagihan provider.

## Layout Docker

- `postgres`: cluster persisten, port host tidak dibuka, database `jarvis`.
- `migrate`: proses satu kali dengan secret migrator saja; selesai sebelum API.
- `api`: UID/GID 10001, filesystem read-only, `/tmp` kecil, capabilities dilepas, satu worker.
- `ops`: profile manual untuk CLI. Memiliki hak aplikasi, bukan administrator database.
- Network `database` bersifat internal; PostgreSQL, migrator, dan CLI hanya memakai network
  ini. API juga bergabung ke bridge `api_access` yang non-internal agar publikasi port host
  berfungsi. Port API secara eksplisit terikat ke `127.0.0.1`; network tambahan ini tidak
  mempublikasikan PostgreSQL dan tidak membuat API tersedia di internet.
- Bridge `api_access` memungkinkan koneksi keluar dari proses API. Jadi API tidak lagi
  terisolasi dari internet pada lapisan jaringan. Tahap 1 belum memiliki integrasi yang
  mengirim dokumen/prompt ke provider. Sebelum tahap AI/tool, terapkan kontrol tujuan
  jaringan dan kebijakan pengiriman data; bind localhost hanya membatasi akses masuk.
- Log Docker dibatasi tiga file, masing-masing 5 MB per container. Itu pembatas ukuran,
  bukan kebijakan retensi berdasarkan hari.

## Konfigurasi

| Variabel | Default/kewajiban | Efek |
|---|---|---|
| `JARVIS_DATABASE_URL_FILE` | Wajib untuk Compose runtime | URL `postgresql+psycopg` milik `jarvis_app` |
| `JARVIS_TOKEN_PEPPER_FILE` | Wajib | Secret acak untuk HMAC token |
| `JARVIS_MIGRATION_DATABASE_URL_FILE` | Proses migrator saja | Kredensial `jarvis_migrator` |
| `JARVIS_ENVIRONMENT` | `production` di Compose | Melarang debug dan docs publik |
| `JARVIS_ALLOWED_HOSTS` | `localhost`, `127.0.0.1` di Compose | Daftar host eksplisit dalam JSON |
| `JARVIS_DB_POOL_SIZE` | 3 | Koneksi dasar per proses |
| `JARVIS_DB_MAX_OVERFLOW` | 2 | Tambahan koneksi per proses |
| `JARVIS_DB_STATEMENT_TIMEOUT_MS` | 5000 | Timeout query per transaksi |
| `JARVIS_MAX_REQUEST_BYTES` | 65536 | Batas body HTTP fondasi |
| `JARVIS_BODY_TIMEOUT_SECONDS` | 10 | Batas waktu membaca body |
| `JARVIS_REQUESTS_PER_MINUTE` | 120 | Limiter IP proses-lokal |
| `JARVIS_RATE_LIMIT_MAX_CLIENTS` | 2048 | Batas memori daftar limiter |
| `JARVIS_DEFAULT_TIMEZONE` | `Asia/Jakarta` | Nilai konfigurasi zona waktu default |
| `JARVIS_LOG_LEVEL` | `INFO` | Tidak boleh DEBUG dalam production |
| `JARVIS_DOCS_ENABLED` | false | Hanya boleh true di development/test |
| `JARVIS_INFRASTRUCTURE_TARGET_IDR` | 100000 | Informasi target biaya, bukan billing cap |
| `JARVIS_PREMIUM_MODE` | `confirm_each_use` | Nilai lain ditolak |
| `JARVIS_CLOUD_PRIVACY` | `no_training_zdr` | Nilai lain ditolak |
| `JARVIS_HTTP_PORT` | 8000 | Variabel Compose untuk port localhost host |

Untuk eksekusi native, secret dapat diberikan melalui variabel langsung tanpa `_FILE`.
Memberikan keduanya sekaligus ditolak. `.env` tidak dibaca oleh Settings aplikasi secara
otomatis; `.env` pada Compose hanya untuk substitusi konfigurasi non-secret.

## Secret file dan akses host

Jalankan generator sebagai pemilik direktori proyek, bukan di folder bersama. Pada Linux,
`.secrets` bermode 0700. File individual bermode 0444 agar UID 10001 di container dapat
membaca bind mount secret; akses pengguna host lain tetap dibatasi oleh direktori induk.
Jangan menyalin file individual ke direktori publik atau mengubah induk menjadi 0755.
Di Windows/NTFS, mode POSIX tidak cukup: gunakan folder privat dengan ACL sesuai akun
pengguna atau filesystem Linux WSL2. File secret tidak dienkripsi otomatis oleh Compose.

Jangan commit `.secrets`, `.env` berisi rahasia, output token CLI, atau database dump.
Ignore Git/Docker sudah disediakan, tetapi administrator tetap perlu memeriksa artefak.
Pemegang akses Docker/root dapat membaca secret container; jangan membagikan akses itu.

## Akses server tanpa domain

Di komputer pengguna, gunakan SSH forwarding ke server yang dikelola sendiri:

```bash
ssh -N -L 8000:127.0.0.1:8000 USER@SERVER
```

Kemudian akses `http://127.0.0.1:8000` dari komputer yang membuat tunnel. Ganti USER/SERVER
sesuai instalasi. Jangan mengubah bind ke `0.0.0.0` untuk mengakses bearer API melalui
internet tanpa HTTPS. Interface web publik nanti membutuhkan TLS, reverse proxy,
konfigurasi trusted proxy, dan kontrol browser tersendiri.

Untuk fondasi, firewall host hanya memerlukan SSH yang dibatasi sesuai akses operator.
Verifikasi dari mesin lain bahwa port 5432 dan 8000 tidak dapat diakses publik. Jangan
mengandalkan firewall host saja saat mempublikasikan port Docker; mapping localhost adalah
pengamanan eksplisit paket ini.

## Pemeriksaan operasi

```bash
docker compose ps
docker compose --profile ops run --rm --no-deps ops doctor
docker compose port api 8000
curl --fail http://127.0.0.1:8000/health/ready
docker compose logs --tail=100 api
docker compose logs --tail=100 migrate
docker compose restart api
```

`/health/live` hanya menyatakan proses hidup; gunakan `/health/ready` untuk menerima trafik.
`docker compose port api 8000` harus menampilkan `127.0.0.1:8000`, atau port lokal yang
dipilih lewat `JARVIS_HTTP_PORT`. Status container `healthy` berasal dari pemeriksaan
di dalam container dan belum membuktikan bahwa host dapat mengakses published port.
Docker healthcheck menandai unhealthy tetapi restart policy tidak otomatis memperbaiki
semua kondisi unhealthy. Operator/monitor perlu memberi peringatan dan memeriksa penyebab.
`/metrics` hanya counter request; disk, RAM, backup, dan provider health belum dimonitor penuh.

## Backup, pemulihan, dan upgrade

Backup produksi belum diotomatisasi pada Tahap 1. Sebelum data nyata dipakai, tetapkan
backup PostgreSQL konsisten, enkripsi sebelum disimpan di luar host, kunci pemulihan terpisah,
retensi, dan uji restore ke lingkungan terisolasi. Target awal yang diusulkan: RPO 24 jam,
RTO 4 jam, retensi 7 harian + 4 mingguan; ini target yang harus dibuktikan, bukan SLA.
Kelak backup dokumen dan Qdrant perlu manifest/revisi yang konsisten dengan PostgreSQL.

Pepper diperlukan agar token lama dapat diverifikasi setelah restore. Simpan secara aman
terpisah dari dump. Jika sengaja merotasi pepper, semua token/pairing lama menjadi tidak
valid dan operator harus menerbitkan pengganti. Rotasi password database memerlukan
perubahan role dan file koneksi secara terkoordinasi; generator tidak melakukan rotasi.

Sebelum upgrade: simpan backup yang bisa dipulihkan, baca migrasi, jalankan semua test,
build image baru, jalankan migrasi satu kali, lalu ganti API dan periksa readiness.
Jangan mengedit migrasi yang sudah diterapkan. Downgrade destruktif dinonaktifkan;
rollback schema memakai backup yang diuji atau migrasi perbaikan maju. Rollback binary
hanya aman bila binary lama kompatibel dengan revisi schema yang sedang digunakan.

## Troubleshooting

| Gejala | Pemeriksaan dan tindakan |
|---|---|
| Generator menolak `.secrets` | Perilaku sengaja; gunakan kredensial lama atau rencana rotasi |
| API tidak mulai | Periksa status `postgres` dan exit `migrate`; jangan menjalankan API dengan kredensial admin |
| Role/secret salah pada volume lama | Bootstrap hanya berjalan pada volume kosong; perubahan file tidak merotasi role yang sudah ada |
| `doctor` gagal / readiness 503 | Periksa kredensial, revisi Alembic, role membership/ownership, dan FORCE RLS |
| API healthy tetapi host menolak koneksi; `ps` hanya `8000/tcp` | Pemetaan host belum aktif. Gunakan network `api_access` untuk API, pertahankan `database` internal; lihat `HOTFIX_LOCALHOST.md` |
| Token 401 | Cek masa berlaku, revoked/suspended, pepper; terbitkan token melalui operator bila perlu |
| HTTP 403 | Scope tidak cukup; jangan memperlebar akses semua token untuk satu kebutuhan |
| HTTP 429 | Limiter satu proses aktif; tunggu jendela berikutnya, tinjau klien/proxy |
| HTTP 413/408 | Body terlalu besar/lambat; fondasi belum memiliki endpoint upload dokumen |
| Secret tidak terbaca UID 10001 | Periksa mode file dan mount; jangan mencetak isinya ke log |
| Image build OOM | Build pada komputer/CI dengan RAM cukup; evaluasi batas server sebelum upgrade berbiaya |

`docker compose down` menghentikan layanan tanpa menghapus named volume. Opsi `--volumes`
menghapus volume dan hanya boleh digunakan untuk cluster test/disposable yang memang
ingin dibuang. Paket ini tidak melakukan penghapusan data produksi secara otomatis.

## Tambahan Tahap 2A

`compose.telegram.yaml` adalah overlay opsional; Compose dasar tidak memerlukan token bot.
Worker `telegram` berada pada jaringan database dan bridge `telegram_egress`, tanpa
published port, dengan plafon 256 MiB/0,5 CPU. `telegram-ops` berada hanya pada network
internal database. Operasi memakai `-f compose.yaml -f compose.telegram.yaml` berurutan.
Bridge egress bukan firewall domain: batas `api.telegram.org` diterapkan oleh client kode,
bukan jaminan bahwa proses yang sudah diretas tidak dapat keluar ke tujuan lain.

| Konfigurasi | Isi |
|---|---|
| `JARVIS_TELEGRAM_CONFIG_FILE` | JSON ≤4096 byte; owner_id UUID, sender_id/bot_id numerik positif |
| `JARVIS_TELEGRAM_BOT_TOKEN_FILE` | Secret token BotFather; prefix bot ID harus cocok config |
| config `poll_seconds` | Default 20, rentang 1–30 detik |
| config `updates_per_poll` | Default 20, rentang 1–100 |

Satu bot dan satu akun Telegram untuk owner ini. Migrasi/ganti identitas bot secara online
belum didukung. Tetap gunakan koneksi PostgreSQL langsung agar session lock bertahan.
Jangan menjalankan dua poller pada database berbeda untuk token bot yang sama.

Pembatas: maksimum 20 balasan yang diterima per menit, 100 balasan pending/sending,
5 percobaan per balasan, jeda pengiriman global minimal satu detik, umur balasan 10 menit.
429 memberi jeda global sesuai `retry_after` bahkan saat balasan sudah kehabisan percobaan.
Timeout yang mungkin sudah terkirim menjadi `uncertain`, bukan retry otomatis.
Receipt terminal dibersihkan setelah 48 jam, batch maksimum 1000, saat startup/poll pertama
lalu setiap 100 poll berhasil. Identitas, cursor dan audit tidak dihapus oleh cleanup ini.
Heartbeat baru berumur <120 detik dipakai healthcheck; ini indikator polling, bukan bukti
bahwa setiap balasan telah sampai. Restart policy dan batas resource perlu diukur di host.

Panduan Windows lengkap: `TELEGRAM_WINDOWS.md`. Script `backup_local.py` menyediakan dump
lokal sebelum upgrade; hasilnya belum dienkripsi dan belum membuktikan restore lengkap.
Tidak mengubah pepper atau bearer pengganti. Pemulihan schema lama memerlukan backup/
restore terisolasi atau roll-forward; downgrade destruktif tidak disediakan.

## Overlay 2B

`compose.assistant.yaml` menambah worker AI 384 MiB/0.5 CPU, tanpa published port;
`assistant-ops` hanya DB dan `assistant-catalog` dapat membaca metadata provider. Secret
baru tidak diperlukan oleh base/Telegram. Semua service memakai image v0.3.0 dan revisi
0003_assistant. Atur sumber daya server setelah mengukur penggunaan nyata; target
Rp100.000 bukan jaminan kapasitas. Tidak ada VPS dibeli atau port publik dibuka oleh paket.
Lihat ASSISTANT_WINDOWS.md untuk urutan test, backup, upgrade dan konfigurasi opt-in.
