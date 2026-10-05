# Tahap 2B — hotfix diagnostik 1

Tanggal: 29 September 2026. Basis: paket v0.3.0 / schema `0003_assistant`.
Penanda terpasang: `diagnostics_version: "2b-diagnostics-1"`.

## Masalah dan batas perbaikan

Kegagalan rute gratis sebelumnya diarahkan ke pemeriksaan rute premium meskipun
premium dinonaktifkan. Akibatnya, penyebab awal bisa tertutup oleh `premium_disabled`.
Selain itu, klien tidak membawa kode status HTTP dalam exception dan error pada
`assistant-catalog` hanya tampil sebagai error umum.

Hotfix mempertahankan kode policy/HTTP asli untuk rute gratis, menambahkan log dengan
fase kegagalan dan ID request, serta membuat kegagalan katalog terbaca. Ini memperbaiki
diagnostik; belum membuktikan penyebab kegagalan permintaan pada komputer pemilik.
Kode HTTP dari percobaan sebelum hotfix tidak dapat dipulihkan dari implementasi lama.

Allowlist membatasi keluaran pada kode tetap, ID request, fase, jenis rute, dan angka HTTP.
Body respons, pesan pengguna, riwayat, header, URL, kunci API dan konfigurasi tidak dicatat
oleh diagnostik ini. Pesan error mentah provider sengaja tidak ditampilkan.

Tidak ada perubahan dependency, konfigurasi Compose, credential, migrasi, schema,
retensi, kebijakan ZDR, batas harga, atau persetujuan premium. Image tetap menggunakan
tag `personal-jarvis:0.3.0`; marker diagnostik membedakan kode setelah hotfix.

## Memasang pada instalasi yang sudah berjalan

1. Ekstrak isi ZIP ke `A:\jarvis-stage-1`, timpa file kode/test/dokumen yang sama.
   Folder `src` di dalam ZIP harus bergabung dengan `A:\jarvis-stage-1\src`.
   Paket tidak berisi secret, backup database, Compose, atau migrasi.
2. Jalankan gate Docker terisolasi:

```powershell
cd A:\jarvis-stage-1
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

Target **236 passed**, 0 failed/skipped, exit 0. Pesan `Aborting on container exit`
setelah tests exit 0 merupakan penghentian normal cluster test.
Jika test gagal, kirim ringkasan kegagalan sebelum memperbarui container aplikasi.

3. Bangun ulang worker assistant saja; layanan API, PostgreSQL dan Telegram tetap berjalan:

```powershell
$ai = @('-f', 'compose.yaml', '-f', 'compose.telegram.yaml', '-f', 'compose.assistant.yaml')
docker compose @ai --profile assistant up -d --no-deps --build --force-recreate --wait --wait-timeout 180 assistant
docker compose @ai --profile assistant exec -T assistant jarvis assistant-status
```

Status harus memuat marker `2b-diagnostics-1`, `enabled: true`, `frozen: false`,
`worker_recent: true`, `config_matches: true`. Konfigurasi yang tidak berubah
mempertahankan aktivasi sebelumnya. Jangan menjalankan ulang setup credential/pairing.
Tidak diperlukan migrasi database.

4. Periksa metadata dari container yang sudah memakai hotfix:

```powershell
docker compose @ai --profile assistant exec -T assistant jarvis assistant-catalog
```

Perintah ini hanya membaca database dan melakukan GET metadata; tidak mengirim prompt
atau membuat inference. Hasil sukses memuat `inference_sent: false`, `kind: free` dan
reservasi numerik nol (`0E-10` juga nol). Kegagalan exit 2 sekarang menyertakan kode
penyebab yang aman untuk dibagikan. Katalog yang lolos belum membuktikan bahwa akun
bisa melakukan inference pada endpoint tersebut.

5. Jika katalog lolos dan worker siap, kirim tepat satu pesan uji Telegram:

```text
/ask Jawab satu kalimat: apa fungsi asisten pribadi?
```

Tunggu balasan, lalu ambil hasil status dan log:

```powershell
docker compose @ai --profile assistant exec -T assistant jarvis assistant-status
docker compose @ai --profile assistant logs --tail 40 assistant
```

Bagikan balasan bot lengkap, hasil katalog/status, dan log diagnostik. Jangan sertakan
file credential. Angka `requests.failed` lama tetap ada sebagai riwayat dan tidak di-reset.

## Membaca hasil

| Kode/fase | Makna pemeriksaan berikutnya |
| --- | --- |
| `endpoint_unavailable` | Endpoint terpilih tidak tersedia pada metadata saat pemeriksaan. |
| `zdr_not_verified` | Kecocokan model/provider pada daftar endpoint ZDR tidak dapat diverifikasi. |
| `catalog_changed` | Dua sumber metadata belum memberikan rencana rute/harga yang sama. |
| `daily_free_limit` | Batas lokal percobaan gratis harian tercapai; jangan menonaktifkan batas biaya. |
| `openrouter_http_401` | Periksa keabsahan/aktivasi kunci; jangan membagikan nilai kunci. |
| `openrouter_http_402` | Penolakan terkait kredit atau limit akun/kunci; kode ini sendiri tidak menentukan tindakan pembelian. |
| `openrouter_http_403` | Penolakan izin, guardrail atau moderasi; bukan bukti tunggal bahwa ZDR perlu diubah. |
| `openrouter_http_404` | Model/rute tidak ditemukan atau endpoint tidak cocok dengan persyaratan request. |
| `openrouter_http_429` | Batas laju/kuota; tidak diulang otomatis. |
| `assistant.catalog` / `assistant.plan` | Gagal ketika menyiapkan rute/metadata. |
| `assistant.dispatch` | Gate lokal menolak sebelum pengiriman inference. |
| `assistant.complete` | Gagal pada panggilan atau verifikasi hasil inference; lihat ledger untuk kepastian status/biaya. |

Rujukan resmi untuk kode HTTP dan filter routing:
- https://openrouter.ai/docs/api/reference/errors-and-debugging
- https://openrouter.ai/docs/guides/routing/provider-selection

## Verifikasi dan batas

- 74 test terfokus router/workflow/diagnostik lulus.
- Suite lokal: **195 passed, 41 skipped**. Skip seluruhnya memerlukan PostgreSQL native
  yang tidak tersedia di lingkungan pengembangan ini. Bukti XML disertakan.
- Ruff lint/format sumber dan test lulus.
- Wheel/sdist berhasil dibangun; isi wheel diverifikasi memuat modul diagnostik dan
  perubahan router/workflow. Docker image belum dibangun di lingkungan pengembangan ini.
- Test HTTP menggunakan mock; tidak ada inference nyata atau premium dalam pengujian.
- Test mencakup pelestarian penyebab, status HTTP, penyaringan log, tidak ada retry,
  tidak ada inference dari katalog, dan alur consent premium yang sudah ada.
- Pemilik sebelumnya melaporkan **207 passed** untuk v0.3.0 sebelum hotfix.
  Hasil itu tidak diklaim sebagai pengujian hotfix. Gate native hotfix masih harus dijalankan.
- Kegagalan awal pada instalasi pemilik masih membutuhkan kode diagnostik baru untuk
  menentukan perbaikan rute/akun yang tepat. Budget premium tetap USD0.

Jika perlu rollback kode, ambil hanya `src/jarvis/assistant/{cli,graph,router}.py`,
`tests/unit/test_assistant_{graph_setup,router}.py`, `docs/ASSISTANT_WINDOWS.md` dan
`docs/STAGE_2B_VERIFICATION.md` dari ZIP v0.3.0 asli. Hapus hanya dua file tambahan
hotfix: `src/jarvis/assistant/diagnostics.py` dan
`tests/unit/test_assistant_diagnostics.py`. Setelah itu rebuild assistant dengan
perintah di atas. Jangan menyalin Compose lama di atas konfigurasi port localhost
yang sudah diperbaiki.
