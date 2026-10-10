# Kontrak UX tebak → konfirmasi → eksekusi

Prinsip lintas-domain untuk semua antarmuka (teks hari ini, voice nanti):
**toleransi di input, ketegasan di eksekusi.** Ketepatan tidak datang dari
format input, melainkan dari loop konfirmasi. Berlaku untuk kalender (sudah),
task, memory, dokumen, specialist, dan voice.

## Aturan

1. Tidak ada pesan error format generik. Setiap input yang dikenali sebagian
   menjawab tiga hal: yang ditangkap, yang kurang, yang diabaikan.
2. Kata tanpa quote tidak pernah ditebak sebagai nama/judul; sisa kata yang
   tidak dipahami dilaporkan apa adanya, tidak disimpan, tidak dijalankan.
3. Usulan konkret selalu mendahului eksekusi: judul + waktu + zona + Ref/nomor,
   lalu pengguna menyetujui (ketuk, `ya`, nomor, atau perintah exact).
4. Nomor antrean selalu berarti antrean saat ini; Ref/ID mengikat aksi exact.
   Persetujuan massal buta ditolak; pembatalan massal dilaporkan per item.
5. Klausa gabungan (`A dan B`) berjalan berurutan atau tidak sama sekali bila
   satu klausa samar. Kegagalan di tengah dilaporkan per item.
6. Negasi, kabar burung (`katanya…`), dan kata buntut yang mencurigakan tidak
   pernah menjadi aksi. Satu kata santai (`ok`) bukan persetujuan.
7. Pesan suara tidak pernah memuat ID; referensi voice berupa nomor/urutan
   atau konteks ("rapat jam 2", "yang tadi") yang di-resolve server-side
   ke aksi exact saat itu juga.

## Status per domain

| Domain | Kondisi |
|---|---|
| Kalender | Diterapkan: salvage + klarifikasi spesifik + konfirmasi/bulk/nomor + tombol + kata waktu Indonesia |
| Task | Nomor Ref/daftar sebagian; gabungan + konfirmasi kata belum |
| Memory/dokumen | Pola sama menunggu Stage 6/7: usulan konkret → konfirmasi |
| Voice | Adapter STT/TTS + auth audio + tanpa-ID-diucapan menunggu Stage 8 |

## Penerimaan

Setiap domain baru lulus bila: 5 input acak-acakan menghasilkan tebakan
spesifik atau penolakan beralasan (bukan error generik); tidak ada eksekusi
tanpa konfirmasi; bulk-approve buta ditolak; seluruhnya tercakup gate stage
masing-masing. Dokumen ini dibaca bersama STAGE_4_8_ACCEPTANCE.
