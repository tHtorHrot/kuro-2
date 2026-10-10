# KURO — perbaikan runner setelah penimpaan manual

Pengguna melaporkan 64 payload `already_current`, hanya mengekstrak/menimpa source dan belum build/migrate/recreate. Gate pertama mereset network personal-jarvis-tests, lalu berhenti pada NativeCommandError untuk progres `Image ... Building`. Tidak ada hasil suite native yang diterima.

Runner awal memakai native redirection `2>&1 | Tee-Object` dengan ErrorActionPreference Stop; PowerShell lama dapat mengubah stderr native menjadi error record. Microsoft menjelaskan perubahan perilaku sejak PowerShell 7.2: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_preference_variables . Revisi memakai stdlib Python Popen, stderr→stdout di subprocess, capture byte/log, lalu exit code asli. Tidak mematikan ErrorActionPreference atau mengubah execution policy sistem.

Scope tetap project personal-jarvis-tests dan hanya compose.test.yaml. Reset `down --volumes` hanya test disposable itu. Database test memakai tmpfs dan credential test; tidak ada mount .secrets/produksi, polling Telegram, scheduler Calendar, transport eksternal atau LLM. Runner membangun image test dan memakai disk/RAM host.

## Terapkan revisi

Ekstrak ZIP revisi ke **A:\Kuro2\kuro-runner-fix**. Di dalamnya ada KURO_PATCH_MANIFEST.json dan scripts. Jangan menimpa instalasi secara manual lagi. Helper terbaru menerima byte tepat dari baseline atau kandidat awal (archive SHA256 2c0e80902230726dc30d7136275c1134d563c247a4b0e8902dfebadbaaed8498). Edit lokal tetap ditolak. File kandidat awal yang berubah dicadangkan; ini tidak memulihkan edit yang sudah hilang pada penimpaan pertama. Manifest baru disalin sebagai metadata terpisah tanpa self-hash.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $kuroFix = 'A:\Kuro2\kuro-runner-fix'
    $kuroRoot = 'A:\Kuro2\kuro-main'
    Set-Location $kuroRoot
    python "$kuroFix\scripts\apply_kuro_patch.py" --patch-dir $kuroFix --target $kuroRoot
    if ($LASTEXITCODE -ne 0) { throw 'Preflight gagal; berhenti.' }
    python "$kuroFix\scripts\apply_kuro_patch.py" --patch-dir $kuroFix --target $kuroRoot --apply
    if ($LASTEXITCODE -ne 0) { throw 'Penerapan revisi gagal; berhenti.' }
    & '.\scripts\run_release_gate.ps1'
    if ($LASTEXITCODE -ne 0) { throw 'Gate gagal; jangan rollout produksi.' }
}
```

Jika muncul Security warning untuk file unduhan, tinjau script/payload yang telah diverifikasi. Pilihan R menjalankan sekali. Jangan mengubah execution policy seluruh komputer. Microsoft menerangkan penanda Zone.Identifier dan Unblock-File di https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/unblock-file . Perbaikan ini tidak membutuhkan Unblock-File massal.

Sesudah gate berhasil: panduan upgrade/backup/build/migrate/recreate dan delta tetap KURO_CANDIDATE_UPGRADE.md/KURO_DELTA_ACCEPTANCE.md. Jangan setup/OAuth/pairing/tools-grant ulang.

## Bukti

- Real child subprocess (Linux): stderr progres exit 0 diterima; exit gagal 7 dipertahankan; stdout/stderr byte cocok persis; executable hilang tidak bisa dianggap lulus; log tidak bisa dibuka mencegah child dimulai.
- Preflight/applier: kandidat sebelumnya diterima berdasarkan byte hash, edit pengguna ditolak, backup/idempotensi diuji; metadata manifest ikut diperbarui tanpa self-hash.
- Final offline regression: 467 items + 83 subtes lulus, 0 failed/skipped, 91 native deselected; evidence/stage-4h/release-runner-fix-package-final/verification.json.
- Runtime Calendar/migrasi 0009/Compose produksi/dependency tidak berubah oleh perbaikan runner. PowerShell/Windows/Docker revisi NOT_RUN di lingkungan asisten; hasil native masih menunggu host pengguna.
- Percobaan SQL statis awal tidak memasang migration URL dan gagal dengan Missing JARVIS_MIGRATION_DATABASE_URL. Run berikut memakai placeholder non-production dalam mode offline, exit 0, SQL byte-identical. Kedua log dipertahankan; bukan native pass.

Pemeriksaan akhir juga menemukan filter packaging `operations` terlalu luas, sehingga dua source file src/jarvis/operations/__init__.py dan monitor.py tidak ada di ZIP awal. Revisi menyertakan keduanya; folder operations di root yang berisi artefak privat tetap dikecualikan. Test packaging memperiksa include source + exclude private archive/secret. Byte source modul tidak berubah dari workspace kandidat awal; keduanya baru disertakan dalam paket.
