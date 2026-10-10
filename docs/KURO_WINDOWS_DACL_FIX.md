# KURO — perbaikan backup folder Windows

Pengguna menjalankan preflight kandidat revisi: 96 checks berhasil. Apply dan diagnosis berikutnya gagal pada Set-Acl dengan SeSecurityPrivilege; kegagalan terjadi di private_folder sebelum journal penyalinan dibuat. File patch belum disalin oleh kedua run itu. Database/container tidak disentuh oleh apply; gate Docker belum dimulai pada run tersebut.

Helper sekarang membaca hanya AccessControlSections.Access, mengganti aturan DACL folder privat menggunakan DirectoryInfo.SetAccessControl, tanpa mengubah owner, group atau audit/SACL. Path diberikan lewat environment sebagai data. Sebelum menulis backup, helper membaca kembali DACL dan memeriksa proteksi inheritance, satu rule current-user FullControl dan flag inheritance/propagation yang tepat. Exit nonzero atau marker verifikasi yang hilang menggagalkan operasi.

API .NET: https://learn.microsoft.com/en-us/dotnet/api/system.io.directoryinfo.getaccesscontrol?view=netframework-4.8.1 dan https://learn.microsoft.com/en-us/dotnet/api/system.io.directoryinfo.setaccesscontrol?view=netframework-4.8.1 . Script dijalankan lewat Windows PowerShell bawaan (`powershell -NoProfile -NonInteractive`), tidak meminta privilege baru atau elevasi.

## Penerapan

Ekstrak ZIP revisi terbaru ke **A:\Kuro2\kuro-acl-fix**; scripts dan KURO_PATCH_MANIFEST.json langsung di dalam folder tersebut. Target pengguna masih source kandidat awal karena apply sebelumnya terhenti sebelum penyalinan. Gunakan PowerShell biasa:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $kuroFix = 'A:\Kuro2\kuro-acl-fix'
    $kuroRoot = 'A:\Kuro2\kuro-main'
    Set-Location $kuroRoot
    python "$kuroFix\scripts\apply_kuro_patch.py" --patch-dir $kuroFix --target $kuroRoot
    if ($LASTEXITCODE -ne 0) { throw 'Preflight gagal; berhenti.' }
    python "$kuroFix\scripts\apply_kuro_patch.py" --patch-dir $kuroFix --target $kuroRoot --apply
    if ($LASTEXITCODE -ne 0) { throw 'Apply gagal; berhenti.' }
    & '.\scripts\run_release_gate.ps1'
    if ($LASTEXITCODE -ne 0) { throw 'Gate gagal; jangan rollout.' }
}
```

Keberhasilan apply mencetak applied=true dan lokasi backup. Preflight/backup tetap wajib; edit pengguna tetap ditolak. Tidak ada setup/OAuth/pairing/grant ulang. Runner masih mereset hanya project test personal-jarvis-tests. Ikuti panduan upgrade hanya setelah native gate berhasil.

## Bukti dan batas

Regresi offline: 470 pytest items + 83 subtes, 0 failed/skipped, 91 native deselected; `docs/evidence/stage-4h/release-dacl-fix/verification.json`. Tambahan tes bridge memakai subprocess mock untuk exit/attestation dan pemisahan path dari kode; itu tidak membuktikan enforcement ACL Windows. PowerShell/native DACL revisi dan Docker gate masih NOT_RUN di lingkungan asisten. Validasi aktual Windows dilakukan oleh readback helper sebelum source copy pada host pengguna.

Perubahan hanya helper host, pesan error, tes, bukti dan dokumentasi. Source fitur Calendar, migrasi 0009, dependency dan overlay produksi tidak diubah oleh perbaikan ACL ini. Hasil dan log kandidat sebelumnya tetap historis.
