# Hotfix Windows CRLF — Jarvis Tahap 1 v0.1.0

28 September 2026. Gunakan pada paket Tahap 1 asli yang dibuat melalui `setup_local.py`.

## Masalah

Pengguna telah menunjukkan hasil **58 test lulus pada PostgreSQL 16.15 native di Docker**.
Saat menjalankan konfigurasi runtime, PostgreSQL healthy tetapi proses `migrate` berhenti
dengan exit code 3. Kode tersebut menandakan error database, bukan diagnosis tunggal.

Pemeriksaan menemukan bug pada generator v0.1.0: penulisan file dalam mode teks di Windows
mengubah akhiran LF menjadi CRLF. Pembaca Python menghapus akhiran tersebut, sedangkan
`$(cat file)` dalam bootstrap shell menyisakan CR. Password role dapat tersimpan dengan
karakter CR tambahan sehingga koneksi aplikasi/migrator ditolak.

Perbedaan pembacaan berhasil direproduksi memakai nilai sintetis. Hubungannya dengan
kegagalan instalasi pengguna masih perlu dibuktikan melalui probe autentikasi. Skrip
hotfix melakukan pembuktian itu sebelum mengubah password database.

## Penerapan pada instalasi yang gagal

1. Ekstrak isi `Jarvis_Tahap_1_Hotfix_Windows_CRLF.zip` langsung ke direktori proyek
   `A:\jarvis-stage-1`. Timpa file kode yang sama. ZIP tidak berisi direktori `.secrets`
   atau volume database dan tidak membuat proyek kedua.
2. Biarkan service `postgres` yang sudah healthy tetap berjalan. Dari PowerShell di
   direktori proyek, jalankan:

   ```powershell
   python scripts/repair_windows_secrets.py
   ```

3. Lanjutkan hanya jika hasilnya memuat `"status": "credentials_verified"`:

   ```powershell
   docker compose up -d --build --wait --wait-timeout 180 api
   docker compose --profile ops run --rm --no-deps ops doctor
   curl.exe --fail http://127.0.0.1:8000/health/ready
   ```

Hasil akhir yang diharapkan adalah `doctor` melaporkan database ready dan RLS
enabled_and_forced, lalu HTTP health menampilkan `{"status":"ready"}`.

Jangan menghapus `.secrets`, menjalankan ulang generator untuk membuat password baru,
atau menggunakan `docker compose down --volumes` untuk memperbaiki masalah ini.
Perubahan file bootstrap saja tidak memperbaiki password role pada volume yang sudah ada,
karena init script tidak dijalankan ulang untuk cluster yang telah diinisialisasi.

## Perilaku skrip pemulihan

- Memvalidasi enam file kredensial asli dan kecocokan URL dengan password yang terkait.
  Konfigurasi custom, karakter tak terduga, atau symlink ditolak.
- Membaca secret yang sudah terpasang di container; sidik jari dibandingkan dengan file
  proyek agar tidak menyasar container dengan kredensial lain.
- Mencoba autentikasi TCP lokal untuk role postgres, jarvis_app, dan jarvis_migrator dengan
  bentuk normal dan bentuk pembacaan shell lama. Tidak mengeluarkan password atau URL.
- Jika salah satu role menolak kedua bentuk, berhenti tanpa mengubah password/file.
- Jika bentuk lama diterima tetapi bentuk normal ditolak, menyelaraskan password ketiga
  role dengan nilai asli tanpa terminator CRLF dalam **satu transaksi**. Tidak mengubah
  role privilege, schema, tabel, data, UUID, atau nilai acak secret.
- Memeriksa autentikasi bentuk normal sebelum menulis ulang terminator file menjadi LF.
  Mode file dikembalikan setelah penulisan. Nilai pepper tetap sama sehingga perubahan
  terminator ini tidak merotasi token.
- Aman dijalankan ulang untuk kredensial yang sudah sesuai: tidak melakukan ALTER ROLE
  lagi jika semua role sudah menerima bentuk normal.

Output `crlf_password_mismatch_confirmed: true` berarti probe membuktikan perbedaan
password. Jika bernilai false tetapi status credentials_verified, kredensial sudah cocok;
penyebab error migrasi yang tersisa perlu dicari dari log. Status tersebut bukan bukti
bahwa seluruh migrasi atau aplikasi sudah berhasil berjalan.

## Bila skrip berhenti atau migrasi masih gagal

Simpan secret dan volume yang ada. Ambil log berikut dan kirim hasilnya untuk diagnosis;
tidak perlu mengirim isi `.secrets`, token, atau URL database:

```powershell
docker compose logs --no-color --tail=80 migrate postgres
```

Jika operasi file gagal setelah penyelarasan database, periksa hak akses folder dan
jalankan kembali skrip. Probe akan mengakui password yang sudah normal tanpa menggantinya
lagi. Jangan mencoba mengatasi kegagalan autentikasi dengan memakai akun admin sebagai
akun runtime atau mematikan RLS.

## Perubahan dan bukti pengujian

| File | Perubahan |
|---|---|
| `scripts/setup_local.py` | Menulis ASCII dalam mode binary dengan LF konsisten lintas OS |
| `infra/postgres/bootstrap.sh` | Menghapus terminator CR/LF dari file password lama |
| `scripts/repair_windows_secrets.py` | Probe dan perbaikan role yang telah dibuat, tanpa penghapusan data |
| `tests/unit/test_windows_secrets.py` | Sembilan uji regresi format Windows dan guard pemulihan |
| `.github/workflows/ci.yml` | Menambah pemeriksaan generator pada runner Windows |

Hasil lokal hotfix: **56 unit test lulus**, Ruff lulus, dan syntax shell bootstrap/probe/
repair lulus. Pengujian mencakup simulasi translasi newline Windows, eksekusi shell bootstrap
dengan file CRLF, password/data yang tetap sama, guard kesalahan autentikasi lain, mount
secret yang berbeda, konfigurasi custom, pengulangan skrip, dan penyembunyian error sensitif.

Probe/perbaikan database nyata belum dijalankan oleh asisten karena tidak tersedia Docker
daemon di lingkungan pengerjaan. Test baru untuk perilaku pemulihan memakai stub subprocess;
hasilnya tidak dinyatakan sebagai pengujian transaksi password PostgreSQL native. Runner
Windows CI baru juga belum dieksekusi. Skrip melakukan pemeriksaan pada instalasi pengguna
sebagai prasyarat sebelum memperbaiki dan melanjutkan startup.

Jika ingin menjalankan ulang suite keseluruhan setelah hotfix, gunakan cluster test yang
terpisah sesuai README. Total menjadi 67 test: 56 unit dan 11 integrasi. Keberhasilan suite
tidak menggantikan `doctor`, healthcheck, dan validasi operasional produksi.

Rujukan perilaku newline: [Python open](https://docs.python.org/3/library/functions.html#open).
Perintah psql dan substitusi literal memakai [dokumentasi PostgreSQL 16](https://www.postgresql.org/docs/16/app-psql.html).
