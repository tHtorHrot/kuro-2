# Tahap 2B — upgrade Windows dari Telegram yang sudah berjalan

Untuk instalasi `A:\jarvis-stage-1` dengan owner dan pairing yang sudah ada.
Versi 0.3.0 mencakup seluruh hotfix Windows CRLF, localhost dan COPY bootstrap test.
Jangan jalankan setup_local, owner-create atau pairing ulang. Jangan hapus volume produksi.

## 1. Salin kode lalu tes di database terpisah

Simpan ZIP 2B di Downloads. Tutup editor yang mengunci file, lalu ekstrak **isi ZIP** ke
`A:\jarvis-stage-1` (file compose.yaml harus langsung di folder tersebut). Timpa file kode.
Paket tidak membawa `.secrets`, `.env`, backup atau volume database; pertahankan milikmu.
Container lama masih memakai image lama sampai langkah rebuild.

```powershell
cd A:\jarvis-stage-1
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

Target paket ini: **207 passed**, tanpa FAILED dan tanpa SKIPPED, exit code 0.
Tulisan “Aborting on container exit” setelah tests exit 0 adalah cara Compose test selesai.
Jika ada kegagalan: berhenti sebelum migrasi, kirim bagian traceback/FAILED yang sudah
menghapus kredensial. Ringkasan TOTAL coverage saja tidak menunjukkan penyebab kegagalan.

Sesudah suite lulus, bersihkan **project test saja**:

```powershell
docker compose -f compose.test.yaml down --volumes
```

Jangan menghilangkan `-f compose.test.yaml` dari perintah cleanup tersebut.

## 2. Hentikan worker, backup, upgrade

```powershell
$tg = @('-f', 'compose.yaml', '-f', 'compose.telegram.yaml')
docker compose @tg --profile telegram stop telegram
python scripts/backup_local.py
```

Harus ada hasil `backup` dengan file `.dump`. Backup ini lokal dan belum terenkripsi;
simpan privat. Header valid bukan bukti restore penuh; uji restore diperlukan sebelum VPS.
Jika backup gagal, berhenti. API masih aktif, jadi jangan melakukan operasi tulis melalui
API selama backup/upgrade. Telegram sudah dihentikan untuk menjaga perubahan transport.

```powershell
docker compose up -d --build --wait --wait-timeout 180 api
docker compose --profile ops run --rm --no-deps ops doctor
curl.exe --noproxy "*" --connect-timeout 5 --max-time 10 --fail http://127.0.0.1:8000/health/ready
docker compose @tg --profile telegram up -d --no-build --wait --wait-timeout 180 telegram
docker compose @tg --profile telegram-ops run --rm --no-deps telegram-ops telegram-status
```

Doctor harus menunjukkan `stage: "2b"` dan RLS `enabled_and_forced`. Readiness `ready`.
Telegram tetap paired dan membalas `/status`. `/ai` menjelaskan bahwa AI belum disiapkan.
Bearer API dan token Telegram lama yang masih sah tetap digunakan. Test kembali `/me`
dengan cara lokal aman yang sudah kamu pakai; jangan kirim bearer ke percakapan ini.

## 3. Konfigurasi OpenRouter tanpa panggilan model

Buat API key khusus Jarvis di akun OpenRouter, simpan privat. Periksa pengaturan data akun:
nonaktifkan input/output logging dan training opt-in, aktifkan ZDR untuk kelompok model
terkait. Jika ada pembatas pengeluaran pada API key, gunakan batas sekecil yang diperlukan.
Tidak perlu membeli model premium untuk menjalankan wizard.

```powershell
python scripts/setup_assistant.py
```

Wizard membaca owner dari konfigurasi Telegram, meminta konfirmasi pengaturan akun,
menerima key dengan input tersembunyi, lalu membaca katalog **metadata saja**. Pilih rute
teks gratis yang ditampilkan. Qwen/DeepSeek/Llama diprioritaskan jika memenuhi syarat;
model gratis dan status provider bisa berubah. Ketik Enter hanya jika pilihan pertama
memang kamu inginkan. Jika tidak ada kandidat, wizard berhenti tanpa beralih berbayar.

File baru: `.secrets/openrouter_key` dan `.secrets/assistant_config.json`.
File existing tidak ditimpa. Default: premium_route=null, budget bulanan/per-call USD0,
15 percobaan gratis/hari UTC, output maksimum 512 token. Setup tidak menjalankan inference.
Lolos metadata belum membuktikan key benar, kuota tersedia, atau provider akan menjawab.

## 4. Jalankan worker, cek gate, aktifkan

```powershell
$ai = @('-f', 'compose.yaml', '-f', 'compose.telegram.yaml', '-f', 'compose.assistant.yaml')
docker compose @ai --profile assistant up -d --no-build --wait --wait-timeout 180 assistant
docker compose @ai --profile assistant-ops run --rm --no-deps assistant-catalog
docker compose @ai --profile assistant-ops run --rm --no-deps assistant-ops assistant-status
docker compose @ai --profile assistant-ops run --rm --no-deps assistant-ops assistant-enable
```

`assistant-catalog` melakukan GET metadata dan harus menampilkan `reserve_usd` bernilai nol
(bisa tertulis `"0E-10"` atau `"0.0000000000"`),
`kind: "free"`, `inference_sent: false`. Jika gate gagal, jangan melonggarkan ZDR atau harga.
`assistant-status` sebelum enable boleh `enabled: false`, tetapi worker_recent dan
config_matches harus true. Tidak ada konfigurasi paid yang aktif otomatis.

## 5. Validasi bot dengan data tidak sensitif

Kirim satu per satu, tunggu balasannya:

```text
/ai
/ask Jawab satu kalimat: apa fungsi asisten pribadi?
/remember nama Pemilik
/ask Siapa nama yang kusimpan?
/memory
/new
/forget nama
/clear
```

Balasan AI bisa menunggu sekitar 20–100 detik karena polling dan provider. Satu permintaan
berjalan per owner. `/cancel` membatalkan yang tertunda. Tidak ada auto-retry inferensi.
Teks biasa tanpa `/ask`, lampiran, URL dokumen, voice, dan tool belum menjadi input AI.
Model bisa salah dan tidak memiliki akses pencarian internet pada tahap ini.

```powershell
docker compose @ai --profile assistant-ops run --rm --no-deps assistant-ops assistant-status
docker compose @ai --profile assistant restart assistant
docker compose @tg --profile telegram restart telegram
```

Sesudah restart, cek `/ai` dan pertanyaan baru. Coba `/ask` dari akun Telegram lain:
seharusnya tidak dibalas atau disimpan. Uji ini perlu dilakukan pemilik; belum terkonfirmasi
oleh log yang dibagikan. Jangan membagikan token bot ke akun lain untuk pengujian.

Default budget USD0 berarti `month_spent_or_held_usd` tetap nol saat hanya rute gratis.
Ini ledger aplikasi, bukan pengganti halaman billing provider atau pembatas akun.

## 6. Premium opsional, tetap persetujuan per panggilan

Tidak perlu diaktifkan untuk gate awal. Jika nanti ingin mengaktifkan, pilih model dan
provider dari katalog endpoint resmi yang memenuhi ZDR, tentukan budget USD per-call dan
bulanan sesuai kemampuan. Perubahan konfigurasi **tidak memberikan izin panggilan**.
Rute premium boleh berupa model open-weight berbayar yang murah; istilah premium berarti
rute yang berpotensi berbiaya, bukan otomatis model paling mahal.

Hentikan assistant terlebih dahulu. Edit hanya `assistant_config.json` lokal (bukan file
key); contoh bagian yang diganti, gunakan model/provider yang benar-benar tersedia:

```json
{
  "premium_route": {"model": "AUTHOR/MODEL", "provider": "EXACT_PROVIDER_TAG"},
  "per_call_budget_usd": "0.01",
  "monthly_budget_usd": "0.10"
}
```

Contoh anggaran di atas hanyalah format, bukan anggaran yang sudah diterapkan. Pertahankan
owner, free_route, privacy, premium_mode dan field lain. File awal read-only; buka atribut
read-only khusus konfigurasi saat mengedit dan tutup kembali sesudahnya. Contoh PowerShell:

```powershell
docker compose @ai --profile assistant stop assistant
attrib -R .secrets\assistant_config.json
notepad .secrets\assistant_config.json
attrib +R .secrets\assistant_config.json
docker compose @ai --profile assistant up -d --no-deps --force-recreate --wait --wait-timeout 180 assistant
docker compose @ai --profile assistant-ops run --rm --no-deps assistant-ops assistant-enable
```

Config berubah -> request/consent lama dibatalkan dan AI nonaktif sampai enable ulang.
Jika gratis gagal secara pasti/metadata ditolak, bot menawarkan rute premium dan batas
reservasinya. Kirim `/approve KODE` yang ditampilkan untuk **satu percobaan**, berlaku
5 menit, atau `/cancel`. Tidak menyetujui berarti tidak ada panggilan premium. Persetujuan
ulang diperlukan untuk pertanyaan berikutnya atau percobaan berikutnya.

Reservasi memakai kapasitas input endpoint penuh, bukan tebakan token aktual, sehingga
bisa lebih tinggi daripada biaya pertanyaan pendek. Bila melebihi budget, tawaran diblokir.
Timeout/crash menahan reservasi; jangan mengurangi angka ledger agar budget terlihat kosong.
Rekonsiliasi kasus tersebut dengan billing OpenRouter sebelum memperbaiki ledger secara
operator. Paket ini tidak mempunyai tombol otomatis untuk menghapus hold/unfreeze: route/
biaya tidak dapat diverifikasi memerlukan diagnosis dan perbaikan yang ditinjau.

## Operasi dan troubleshooting

- Stop AI sementara: `docker compose @ai --profile assistant-ops run --rm --no-deps assistant-ops assistant-disable`.
  Perintah memory/clear masih tersedia; dispatch berikutnya diblokir.
- `worker_recent: false`: cek `docker compose @ai logs --tail 50 assistant`.
  Log hanya event/kode, bukan prompt/key. Jangan membagikan dump konfigurasi/lingkungan.
- `premium_disabled`: rute gratis gagal, premium memang belum aktif. Cek katalog/kuota;
  bukan alasan untuk menambah top-up tanpa keputusanmu.
- `catalog_changed`, `zdr_not_verified`, `endpoint_unavailable`: tunggu atau pilih endpoint
  lain secara eksplisit. Jangan memakai router acak untuk melewati gate.
- `context_too_large`: gunakan `/new`; hapus fakta panjang yang tidak diperlukan.
- `frozen: true`: respons model/provider/harga tidak cocok atau biaya tak terverifikasi.
  AI berhenti; review metadata/billing, jangan mengaktifkan ulang dengan meniadakan pemeriksaan.
- `uncertain`: bisa sudah diproses provider. Tidak dikirim ulang; request baru adalah aksi
  baru, dan setiap paid attempt tetap memerlukan persetujuan baru.
- Rollback migrasi destruktif tidak disediakan. Untuk kembali ke versi lama perlu restore
  backup pada volume **baru**, validasi, lalu pergantian terencana. Jangan arahkan kode 2A ke
  schema 2B karena readiness sengaja menolak revisi yang berbeda.

## Batas privasi

Isi chat AI/profil/snapshot disimpan dalam PostgreSQL privat, belum enkripsi per kolom.
Lindungi komputer/volume dan backup dengan enkripsi disk serta akses OS. `/clear` menghapus
salinan aktif lokal, tidak menghapus pesan yang sudah dikirim ke Telegram atau salinan
backup. Profil dihapus dengan `/forget kunci`. Panggilan yang sudah committed sebagai
dispatch mungkin sedang berlangsung saat clear/disable; hasil lama dibuang tetapi data
terkirim tidak bisa ditarik. ZDR/no-training adalah pembatas provider, bukan pemrosesan
lokal; caching sementara dalam memori dapat tetap kompatibel dengan kebijakan ZDR.
