# Resume KURO — lanjut dari delta, jangan audit ulang baseline

Baca `CHECKPOINT.json`, `DEVELOPMENT_STATUS.md`, `docs/WORK_MATRIX.md` dan `docs/evidence/stage-4h/release-dacl-fix/verification.json`. Baseline ZIP hash sesuai prompt; tidak ada Git/AGENTS atau source lebih baru dalam workspace. File `.env/.secrets` instalasi tidak ada dan tidak dibuat. Package manifest lama tetap historis; manifest byte baru `KURO_PATCH_MANIFEST.json`.

Laporan pengguna 5 Oktober bahwa write acceptance seluruhnya berhasil sudah disimpan sebagai `user_reported`. Read/agenda sebelumnya diterima. Log 444 tes / 28.50s memang tersedia pada `calendar-test.log`; klaim lama “log belum diunggah” superseded. Hash release/ID/timestamp/grant pengujian historis tidak diketahui. Jangan mengulang OAuth, pairing, grant, migrasi 0008 atau baseline smoke.

Batch kode terbaru: draft/job Calendar durable, parser bounded, snapshot provenance/anchor, event/due terpisah, immutable fingerprint v2 dengan v1 kompatibel, detached turns, completion outbox, target cancel, migrasi 0009 + upgrade/native tests, backup CMS/restore quarantine/monitor/retention/rollback/release helpers. Source menentukan implemented; bukti final menentukan tested. Tidak ada label frozen atau production-ready.

Gate berikut:

1. Terapkan patch melalui preflight dengan target `A:\Kuro2\kuro-main`; conflict perubahan pengguna ditolak. Jalankan `scripts/run_release_gate.ps1` pada project test terisolasi. Perbaiki hanya failure/delta yang ditemukan, lalu simpan JSON/XML/log untuk kandidat baru yang benar. Native mock khusus crash setelah provider accept mengukur satu POST + GET recovery.
2. Sesudah native gate lulus: backup upgrade, build runtime, migrate 0009, doctor dan recreate services dengan write overlay sesudah Calendar read, sesuai panduan. Source live memakai image, bukan bind mount; restart saja tidak cukup. Jangan grant ulang.
3. Jalankan `docs/KURO_DELTA_ACCEPTANCE.md` untuk klarifikasi restart + scheduled acknowledgement/read + completion + correction/cancel. Natural chat live cukup satu smoke jika belum ada bukti; setup/model/privacy/budget existing tetap.
4. Stage 5: jalankan encrypted backup + **disposable** DB/volume restore/retrieval, ukur waktu dan pending jobs/quarantine. Pilih key custody/offsite/alert/hosting hanya ketika hasil siap ditinjau. Hindari produksi/fault injection akun nyata untuk tes crash.

Blocker terukur lingkungan asisten: Docker/PostgreSQL tidak tersedia, UID map hanya `0 0 1`; Windows/live/restore/hosting NOT_RUN. GPG socket dilarang, backend CMS berhasil diuji. PGlite supplementary GRANT catalog error, tidak dipakai sebagai native evidence. Jangan mengulang perintah blocker tanpa perubahan kondisi.

Delta terbaru hanya runner host/capture, preflight update kandidat, tes dan bukti/dokumentasi. Source runtime Calendar/schema/dependency sama dengan kandidat awal. Pengguna sudah menimpa source dan semua 64 payload sesuai; percobaan gate native awal terhenti pada progres stderr sebelum suite selesai. Terapkan ZIP revisi dari staging memakai helper terbaru, lalu ulangi gate; jangan klaim Windows runner revisi telah lulus. Source hash/count final ada di checkpoint dan release-runner-fix-package-final.

Blocker pengguna terbaru diketahui: SeSecurityPrivilege pada pembuatan private backup directory, sebelum apply copy. Perbaikan helper DACL tersedia; target main masih kandidat awal menurut posisi kegagalan di kode. Terapkan revisi ACL dari staging baru lalu native gate; jangan menaikkan privilege atau mengulang setup. Evidence final release-dacl-fix; Windows DACL enforcement revisi belum diuji di sini.
