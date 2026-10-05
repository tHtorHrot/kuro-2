# Hotfix akses localhost — Tahap 1

## Masalah dan bukti

Sesudah hotfix CRLF, pengguna mengonfirmasi:

- Ketidakcocokan password CRLF terdeteksi dan berhasil dinormalisasi; enam file secret
  diselaraskan tanpa mengganti nilai acak yang dimaksud.
- Migrasi selesai, API healthy, `doctor` menghasilkan database ready dan RLS enabled/forced.
- Readiness di dalam container menghasilkan `{"status":"ready"}`.
- Host Windows gagal tersambung ke `127.0.0.1:8000`; `docker compose ps` hanya menampilkan
  `8000/tcp`, dan `docker compose port api 8000` menghasilkan `invalid IP:0`.

Ini menunjukkan pemetaan host belum tersedia walaupun aplikasi bekerja. Compose awal
hanya menghubungkan API ke network `database` dengan `internal: true`. Hotfix menambahkan
endpoint bridge non-internal untuk API agar publikasi port host dapat dibuat.

## Perubahan dan privasi

- API memakai `api_access` dan `database`; port host tetap
  `127.0.0.1:${JARVIS_HTTP_PORT:-8000}:8000`.
- PostgreSQL, migrator, dan CLI tetap hanya memakai `database` internal, tanpa published port.
- Default bind untuk network baru juga `127.0.0.1`; tidak ada bind host `0.0.0.0`.
- Bridge baru mengizinkan API membuat koneksi keluar, termasuk internet jika tersedia.
  Jadi ini bukan konfigurasi API tanpa akses internet. Tahap 1 tidak memiliki integrasi
  provider, unggah dokumen, atau pengiriman prompt. Sebelum menambahkan integrasi tersebut,
  kontrol tujuan jaringan, kebijakan tanpa pelatihan/ZDR, dan persetujuan premium tetap wajib.
- Hotfix tidak mengubah kode autentikasi, secret, role SQL, skema, atau volume database.
- Tidak ada image baru, dependency baru, layanan tambahan, atau langganan yang dibutuhkan.

## Penerapan pada instalasi yang sudah healthy

Ekstrak isi ZIP langsung ke `A:\jarvis-stage-1` dan timpa file yang sama. Hotfix ini merupakan
tambahan setelah hotfix CRLF, bukan pengganti proyek lengkap. Paket tidak berisi `.secrets`.
Jika Compose telah dimodifikasi sendiri, gabungkan perubahan jaringan dengan konfigurasi
tersebut; jangan menimpa penyesuaian lokal tanpa meninjaunya.

Jalankan di PowerShell:

```powershell
cd A:\jarvis-stage-1
docker compose config --quiet
```

Jika perintah tersebut tidak menampilkan error dan exit code nol, lanjutkan:

```powershell
docker compose up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 api
docker compose port api 8000
curl.exe --noproxy "*" --connect-timeout 5 --max-time 10 --fail http://127.0.0.1:8000/health/ready
docker compose ps
```

Perintah recreate menghentikan dan mengganti container API secara singkat, memakai image
yang sudah berhasil dibangun. `--no-deps` membiarkan PostgreSQL dan migrator yang ada;
tidak ada penghapusan volume atau pembuatan ulang secret. `--no-build` sesuai karena hotfix
hanya mengubah Compose/dokumentasi/CI, bukan kode atau image.

Target hasil:

```text
docker compose port api 8000: 127.0.0.1:8000
readiness dari Windows: {"status":"ready"}
kolom PORTS API: 127.0.0.1:8000->8000/tcp
kolom PORTS PostgreSQL: 5432/tcp, tanpa panah ke port host
```

`5432/tcp` tanpa panah hanya informasi port container. API tidak menyediakan port database;
`docker compose port api 5432` memang tidak menghasilkan pemetaan.
Jika `JARVIS_HTTP_PORT` sudah diubah, gunakan nomor host yang ditampilkan oleh perintah
`docker compose port api 8000` pada URL curl; port dalam container tetap 8000.

Jika masih gagal, kirim keluaran perintah di atas dan:

```powershell
docker compose logs --no-color --tail=60 api
docker context show
```

Jangan kirim isi `.secrets`, token, atau keluaran konfigurasi penuh. Tidak diperlukan
`docker compose down --volumes`, reset database, atau menonaktifkan firewall Windows.

## Validasi dan batas bukti

- Struktur YAML, pewarisan konfigurasi, pemetaan localhost, dan keanggotaan network telah
  diperiksa secara statis. Perubahan Compose dibatasi pada network baru dan network API.
- Konfigurasi PostgreSQL, migrator, CLI, secret, volume, dan pembatasan container dibandingkan
  dengan versi sebelum hotfix untuk memastikan tetap sama.
- CI runtime kini mengecek pemetaan host secara eksplisit sebelum memanggil readiness host.
- Lingkungan pembuat hotfix tidak memiliki Docker daemon. Penerusan port yang sebenarnya
  belum dijalankan di sini; penerimaan hotfix menunggu hasil Docker Windows pengguna.
- Uji unit tidak diulang untuk perubahan Compose ini: unit test tidak menguji port Docker.
  Bukti 56 uji unit pada hotfix CRLF tetap merupakan hasil tahap sebelumnya.

## Referensi resmi

- [Docker: beberapa network pada satu container](https://docs.docker.com/engine/network/#connecting-to-multiple-networks)
- [Compose: network dan isolasi internal](https://docs.docker.com/reference/compose-file/networks/)
- [Docker: publikasi port localhost](https://docs.docker.com/engine/network/port-publishing/)
- [Compose up: recreate dan no-deps](https://docs.docker.com/reference/cli/docker/compose/up/)
