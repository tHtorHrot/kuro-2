KURO Calendar Setup — 4 Oktober 2026

Ekstrak isi ZIP langsung ke A:\Kuro2\kuro-main.
Folder scripts, tests dan docs digabung dengan folder yang sudah ada.
Ini helper OAuth lokal dan pembaruan dokumentasi; tidak perlu build atau migrasi ulang.

Mulai dari docs/GOOGLE_CALENDAR_WINDOWS.md.
Buat OAuth Desktop app, simpan JSON pribadi di .secrets/google_oauth_client.json,
lalu jalankan python .\scripts\setup_calendar.py dari PowerShell.
Setelah berhasil, lanjutkan grant calendar:read dan scheduler sesuai panduan.

Paket tidak membawa atau menimpa file .secrets. Jangan unggah JSON/token pribadi.
35 tes helper lulus; login Google nyata dilakukan pengguna, belum diuji di sesi asisten.
444 tes runtime dan upgrade telah dilaporkan berhasil oleh pengguna sebelumnya.
Stage 4 belum dibekukan; Stage 5–8 belum selesai.
