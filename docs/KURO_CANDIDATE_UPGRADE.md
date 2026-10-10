# KURO — kandidat Stage 4h / fondasi Stage 5

Baseline: `kuro2.zip`, SHA256 `67535ace1926135986170771f20b9f7fdf91d9a5d3593be90df8edc608cef4bb`, schema `0008_executor_binding`. Target `A:\Kuro2\kuro-main`; Compose production `personal-jarvis`. Ini patch kumulatif relatif ke root proyek, bukan installer/setup baru. Tidak ada file dihapus. `.env`, `.secrets`, owner, pairing, volumes, dokumen, model cache, konfigurasi dan histori pengguna tidak disertakan/diganti.

Kandidat membutuhkan **build runtime baru**, migrasi **0009**, lalu **recreate assistant, scheduler dan telegram**. Dependency aplikasi/uv.lock dan migrasi 0001–0008 tidak berubah. Package/namespace tetap personal-jarvis/jarvis. Dokumen ini tidak menyatakan native gate/Windows/live delta sudah dijalankan.

## 1. Preflight dan patch source

Ekstrak ZIP patch ke folder staging berbeda, misalnya `A:\Kuro2\kuro-patch`. Jangan ekstrak langsung menimpa root instalasi. Python host 3.12–3.13 diperlukan untuk helper. Jika helper memakai dependency, gunakan lingkungan host yang sesuai; jangan menjalankan setup/pairing/grant ulang.

```powershell
Set-Location 'A:\Kuro2\kuro-main'
python 'A:\Kuro2\kuro-patch\scripts\apply_kuro_patch.py' --patch-dir 'A:\Kuro2\kuro-patch' --target 'A:\Kuro2\kuro-main'
if ($LASTEXITCODE -ne 0) { throw 'Preflight gagal; source pengguna belum diubah.' }
python 'A:\Kuro2\kuro-patch\scripts\apply_kuro_patch.py' --patch-dir 'A:\Kuro2\kuro-patch' --target 'A:\Kuro2\kuro-main' --apply
if ($LASTEXITCODE -ne 0) { throw 'Patch gagal; berhenti dan periksa conflict.' }
```

Jika satu-satunya mismatch adalah CRLF/LF, ulangi preflight dengan `--allow-newline-only`, periksa laporan `newline_only_baseline; byte_hash_different`, lalu gunakan flag itu pada apply. Ini pemeriksaan kesetaraan newline, **bukan** keberhasilan hash byte baseline. Perubahan isi pengguna tetap ditolak. Untuk update dari kandidat awal, manifest juga mencatat hash byte kandidat sebelumnya. Hanya kecocokan tepat yang diterima (`byte_previous_candidate`); edit pengguna tetap ditolak. Manifest release ikut disalin tanpa memasukkan hash dirinya ke daftar payload. File source lama disimpan di `backups/patch-files-*`; tidak ada database/container yang berubah pada apply. Payload final diverifikasi terhadap `KURO_PATCH_MANIFEST.json`; manifest mengecualikan dirinya sendiri dari hash.

## 2. Gate terisolasi, satu kali per kandidat

```powershell
& '.\scripts\run_release_gate.ps1'
if ($LASTEXITCODE -ne 0) { throw 'Gate gagal; jangan rollout.' }
```

Runner memakai **hanya** compose.test.yaml, project **personal-jarvis-tests**; reset volume hanya project itu. Runner melakukan lint/format, fixture upgrade populated 0003 → 0008 → 0009 dengan action pending/claimed/dispatching/uncertain, migrasi dua kali, native PG/RLS, provider mock, Qdrant dan OCR. OpenSSL tersedia di image tes untuk drill enkripsi. Log, XML dan JSON dipersistenkan di `docs/evidence/native-candidate/run`. Run sebelumnya diarsipkan sebelum run baru. Exit native command ditangkap sebelum cleanup/log lain. Jangan menyamakan `deselected`, `skipped`, hasil baseline 444, atau subtes dengan item pytest baru.

**Gate harus lulus sebelum mengubah database produksi.** Jangan menjumlahkan hasil historis dengan suite kandidat ini. Runner PowerShell belum dieksekusi pada Windows oleh asisten.

## 3. Backup, build, migrate, recreate

Gunakan overlay aktif existing. Contoh di bawah menggunakan Telegram + assistant + knowledge + Calendar read + Calendar write. **write harus sesudah Calendar read**, termasuk pada recreate scheduler. Jika knowledge tidak aktif, keluarkan overlay/profile knowledge; jangan mengaktifkan layanan baru hanya untuk upgrade. Tambahkan overlay produksi lain yang sudah dipakai, dalam urutan existing.

```powershell
$kuroCompose = @('-p','personal-jarvis','-f','compose.yaml','-f','compose.telegram.yaml','-f','compose.assistant.yaml','-f','compose.knowledge.yaml','-f','compose.calendar.yaml','-f','compose.calendar.write.yaml')
# Berhenti mengirim perintah/operator write selama maintenance ini.
docker compose @kuroCompose stop --timeout 240 api assistant telegram scheduler knowledge
if ($LASTEXITCODE -ne 0) { throw 'Stop writer gagal; hentikan upgrade.' }
python '.\scripts\backup_local.py'
if ($LASTEXITCODE -ne 0) { throw 'Backup binary gagal; jangan migrate. Start kembali writer existing.' }
# Simpan image ID lama sebelum tag diganti. Ini metadata lokal, bukan bukti compatibility schema baru.
docker compose @kuroCompose images --format json | Set-Content -Encoding UTF8 '.\backups\images-before-0009.json'
if ($LASTEXITCODE -ne 0) { throw 'Pencatatan image gagal.' }
docker compose @kuroCompose build migrate api assistant telegram scheduler
if ($LASTEXITCODE -ne 0) { throw 'Build gagal; schema belum diubah. Jangan lanjut.' }
docker compose @kuroCompose run --rm --no-deps migrate
if ($LASTEXITCODE -ne 0) { throw 'Migration gagal; jangan jalankan image lama pada schema yang tidak diketahui.' }
docker compose @kuroCompose --profile ops run --rm --no-deps ops doctor
if ($LASTEXITCODE -ne 0) { throw 'Doctor gagal; tahan executor.' }
docker compose @kuroCompose --profile telegram --profile assistant --profile knowledge up -d --no-deps --force-recreate api assistant telegram scheduler knowledge
if ($LASTEXITCODE -ne 0) { throw 'Recreate gagal; periksa status layanan, jangan tools-grant ulang.' }
```

Scheduler tidak memakai profile tersendiri dalam overlay existing; layanannya disebut secara eksplisit. Jika instalasi tidak menjalankan knowledge, jangan menyebut `knowledge` pada stop/up dan profile. `build` services yang memakai runtime image sama membuat source baru masuk image; `restart` saja tidak menerapkan build/mount baru. Parser tidak perlu rebuild karena extractor/runtime parser tidak berubah, namun runtime knowledge harus memakai image schema 0009 saat kembali hidup.

Backup_local tetap pg_dump custom format **tanpa enkripsi**, berguna untuk backup upgrade privat. Helper Python menulis bytes langsung; jangan mengalihkan pg_dump melalui pipeline PowerShell text. Backup lengkap terenkripsi Stage 5 ada pada runbook operasi; belum menggantikan kewajiban restore drill nyata.

Pada upgrade 0008 → 0009, action lama tidak diulang, tidak diberi grant baru, tidak diganti fingerprint v1, dan tidak diubah payload/due time. Request lama mempertahankan lifecycle existing; job dari grammar baru memakai task + notification terpisah.

## 4. Rollback

Sebelum migrate, kegagalan patch/build dapat dipulihkan dari source backup dan image ID lama. **Sesudah schema 0009 diterapkan, image baseline 0008 tidak kompatibel dengan readiness check baru.** Utamakan roll-forward perbaikan kandidat 0009. `scripts/rollback_guard.py` hanya mengizinkan pasangan image digest/schema yang tercatat kompatibel; tidak mengubah deployment atau database.

Restore data adalah proses berbeda: hentikan executor **dan** pengiriman eksternal, lakukan drill disposable dahulu, verifikasi secret/pepper original melalui jalur privat, dan rekonsiliasi aksi yang mungkin sudah berefek di Google. Restore DB tidak menghapus event Google. Tidak ada downgrade migrasi otomatis atau `down --volumes` production. Mengembalikan image lama setelah restore memerlukan schema/backup/reconciliation yang benar, bukan sekadar mengganti tag Docker.

## 5. Penerimaan delta singkat

Lanjut ke `docs/KURO_DELTA_ACCEPTANCE.md`. Read/agenda, OAuth write, create/restart pre-dispatch, cancel deletion, approved delete baseline sudah diterima menurut laporan pengguna 5 Oktober. Tidak perlu mengulang setup atau tools-grant. Satu natural-chat smoke tetap dibutuhkan jika belum pernah ada bukti balasan live LLM.

## Perbaikan runner PowerShell

Jika gate berhenti dengan `NativeCommandError` pada progres Docker `Image ... Building`, terapkan revisi dari staging sesuai `KURO_RUNNER_FIX.md`. Helper Python menggabungkan stream native sebelum masuk PowerShell, menulis log biner dan mengembalikan exit Compose. Tidak perlu mengubah execution policy sistem. Windows runner revisi tetap perlu diuji pada host pengguna.
