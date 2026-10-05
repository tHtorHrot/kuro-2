# Hotfix Tahap 2A: bootstrap tidak masuk image test

28 September 2026. Berlaku untuk paket v0.2.0 dengan hasil `143 passed, 1 failed` pada
`test_bootstrap_reads_legacy_windows_files_without_extra_password_byte`.

## Penyebab dan perubahan

Test membaca `infra/postgres/bootstrap.sh`. Dockerfile awal menyalin direktori tests dan
scripts tetapi tidak menyalin bootstrap itu ke stage `tests`, sehingga test di container
menemui FileNotFoundError. Kegagalan berhasil direproduksi pada layout file yang sama.
Ini kesalahan packaging test pada paket yang dibuat, bukan bukti password database rusak.

Satu baris ditambahkan setelah `COPY scripts ./scripts` pada stage `FROM builder AS tests`:

```dockerfile
COPY infra/postgres/bootstrap.sh ./infra/postgres/bootstrap.sh
```

Stage runtime tetap sama. Tidak mengubah migrasi, secret, password, pepper, atau database.
Tidak menghapus atau melewati test yang gagal.

## Cara menerapkan

Ekstrak ZIP hotfix ke `A:\jarvis-stage-1`, setujui penggantian **Dockerfile**. ZIP ini tidak
berisi `.secrets`. Alternatif: tambahkan baris di atas secara manual pada posisi tersebut.
Jangan menjalankan ulang `repair_windows_secrets.py` untuk masalah packaging ini.

Jalankan dari PowerShell:

```powershell
cd A:\jarvis-stage-1
docker compose -f compose.test.yaml down
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
```

Perintah `down` di sini khusus proyek `personal-jarvis-tests` dan membersihkan container
test yang memakai tmpfs agar bootstrap mendapat cluster test baru. Pertahankan argumen
`-f compose.test.yaml`. Database instalasi `personal-jarvis` tidak ditargetkan.
Target hasil **144 passed**, tanpa gagal/skip. Setelah itu lanjutkan backup sebelum
upgrade API pada `docs/TELEGRAM_WINDOWS.md`, bukan membuat owner baru.

## Bukti dan batas validasi

- Sebelum perbaikan pada layout file image test: 1 tes terkait gagal FileNotFoundError.
- Setelah file bootstrap disertakan pada layout tersebut: **121 unit test lulus**.
- Pengguna melaporkan 143 tes lulus, termasuk seluruh 23 native integration, sebelum fix.
- Build/rerun Docker setelah fix masih perlu dijalankan pengguna; lingkungan pengerjaan
  tidak memiliki daemon Docker. Pengujian layout file tidak menggantikan build Docker.

Ringkasan machine-readable: `docs/evidence/stage-2a/test-image-hotfix.json`.
