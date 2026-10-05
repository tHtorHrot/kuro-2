# Hotfix OCR-1 — Tahap 3 v0.4.0

Pembaruan 1 Oktober 2026 untuk paket Tahap 3 awal. Terapkan setelah paket lengkap
0.4.0 sudah diekstrak. Hotfix hanya memuat perubahan Dockerfile/CI, panduan, bukti dan
manifest; tidak membawa secret, .env, database atau volume pengguna.

## Penyebab yang ditemukan

Dockerfile awal memakai `--no-install-recommends` dan memasang `tesseract-ocr-eng`
serta `tesseract-ocr-ind`. Keduanya adalah data bahasa. Paket CLI `tesseract-ocr`
hanya direkomendasikan, sehingga tidak ikut dipasang. Cacat ini ada pada image test
dan parser runtime. Hotfix memasang mesin secara eksplisit dan menambah pemeriksaan
executable Poppler/Tesseract serta bahasa eng+ind saat kedua image dibangun.

Rujukan paket Debian Bookworm:
- https://packages.debian.org/bookworm/tesseract-ocr-eng
- https://packages.debian.org/bookworm/tesseract-ocr-ind
- https://packages.debian.org/bookworm/tesseract-ocr

Laporan pengguna sebelum perbaikan: 281 passed, 1 failed pada tes OCR, exit 1.
Traceback lengkap belum tersedia; kode paket menunjukkan cacat dependency yang pasti,
namun hasil setelah hotfix tetap harus diverifikasi di Docker pengguna.

## Jika sudah menimpa file tanpa backup

Menimpa kode dan menjalankan compose.test.yaml tidak menjalankan migrasi database
instalasi utama. Jika hanya langkah itu yang dilakukan, cadangkan database sekarang:

```powershell
Set-Location A:\jarvis-stage-1
python scripts/backup_local.py
if ($LASTEXITCODE -ne 0) { throw "Backup gagal; berhenti sebelum migrasi." }
```

Pastikan ada path `.dump` pada hasil. Script memerlukan postgres instalasi utama masih
berjalan; jika gagal, kirim error dan hasil `docker compose -f compose.yaml ps postgres`.
Simpan salinan `.secrets` secara privat di luar folder proyek, tanpa mengirim isinya.
Backup database ini tidak memulihkan perubahan kode pribadi yang sudah tertimpa.
Jika sudah menjalankan migrasi instalasi utama, dump baru adalah kondisi setelah migrasi.

## Terapkan dan uji ulang

1. Ekstrak isi ZIP hotfix langsung ke `A:\jarvis-stage-1`, timpa file yang sama.
2. Jalankan blok berikut. Perubahan Dockerfile membuat layer paket OS dibangun ulang;
   tidak perlu menghapus volume atau image lain.

```powershell
Set-Location A:\jarvis-stage-1
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
$testExitCode = $LASTEXITCODE
docker compose -f compose.test.yaml logs --no-color tests 2>&1 | Tee-Object -FilePath .\stage3-tests.log
Write-Output "TEST_EXIT_CODE=$testExitCode"
if ($testExitCode -eq 0) {
    docker compose -f compose.test.yaml down
    Write-Output "Tes lulus. Lanjut bagian 3 KNOWLEDGE_WINDOWS.md."
} else {
    Write-Warning "Tes gagal. Jangan migrasi; simpan stage3-tests.log dan kirim bagian FAILURES."
}
```

Target suite versi ini: 282 passed, tidak ada failed/skipped, `TEST_EXIT_CODE=0`.
Ini target penerimaan, bukan klaim hasil yang sudah diamati setelah hotfix.
`Aborting on container exit` dan shutdown service pendamping terjadi saat Compose
menghentikan proyek test; penentu lulus tetap hasil pytest dan exit code tests.

`docker compose ... down` menghapus container test sehingga perintah logs sesudahnya
bisa kosong. Blok di atas menyimpan log sebelum down dan hanya membersihkan saat sukses.
Jika build gagal sebelum container tests dibuat, salin error build dari terminal karena
log container tests belum ada.

Sesudah tes lulus, lanjut **bagian 3** `docs/KNOWLEDGE_WINDOWS.md`, termasuk build
`document-parser`; hotfix harus ikut masuk image parser runtime, bukan hanya image test.
Jangan mengulang setup owner/pairing/model atau menonaktifkan tes OCR.

## Bukti dan batas pengujian hotfix

Pemeriksaan dependency image diamati gagal pada Dockerfile awal dan lulus setelah
perubahan. Tes ekstraksi lokal memakai Tesseract/Poppler nyata; hasil aktual ada di
`docs/evidence/stage-3/ocr-hotfix-1/extraction-tests.txt`. Build Docker hotfix tidak dapat
dijalankan di lingkungan pembuat paket, sehingga gate Docker pemilik tetap wajib.
