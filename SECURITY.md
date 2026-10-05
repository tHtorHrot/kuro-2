# Security review — fondasi dan Tahap 2A

Ini checklist untuk keputusan deployment, bukan klaim audit/pentest independen.
Tidak ada data pribadi pengguna yang dimasukkan ke test suite.

## Batas kepercayaan

| Ancaman | Pengendalian Tahap 1 | Batas |
|---|---|---|
| Orang lain mengakses API | Bearer acak 256-bit, digest HMAC, scope, TTL, revoke, akun suspended | Token yang dicuri dapat dipakai sampai dicabut/kedaluwarsa |
| Query salah mengakses owner lain | Filter owner + PostgreSQL RLS/FORCE + role non-owner | Proses/kredensial DB yang dikuasai bisa mengatur GUC owner |
| Input terlalu besar/lambat | Batas 64 KiB, read timeout 10 detik, limiter bounded | Belum proteksi DDoS skala jaringan; deploy localhost |
| Pemalsuan IP lewat header | Proxy headers Uvicorn dimatikan; IP socket dipakai | Reverse proxy nanti membutuhkan desain ulang trust/limiter |
| Secret masuk log | Daftar field log terbatas, redaksi, access log mentah mati | Plugin/proxy/tracing tambahan harus ditinjau terpisah |
| Runtime mengubah schema | Credential migrator terpisah, app tidak punya CREATE/role membership | Host/Docker/admin DB tetap dipercaya |
| Audit diubah aplikasi | Runtime tidak punya UPDATE/DELETE pada audit | Administrator database dapat mengubah audit |
| Penggunaan model mahal otomatis | Policy mengharuskan konfirmasi; belum ada panggilan LLM | Persetujuan atomik dan ledger biaya harus selesai pada Tahap 2 |
| Dokumen memerintah agent/tool | Belum ada parser/LLM/tool runtime | Isolasi parser, prompt injection, SSRF, izin tool harus diuji pada tahap terkait |

## Implementasi yang tersedia

- [x] Token berentropi 32 byte, HMAC seluruh token, perbandingan constant-time.
- [x] TTL maksimum 90 hari, revoked timestamp, scope eksplisit, suspend owner.
- [x] Token/pairing/API key tidak dikirim sebagai query parameter.
- [x] Pairing terikat sender ID, private chat, TTL, batas percobaan, dan row lock.
- [x] Lima tabel memakai owner isolation dengan RLS ENABLE + FORCE.
- [x] Runtime menolak superuser/BYPASSRLS/role pembuat/replication/table owner/membership.
- [x] Tenant context transaction-local dan commit sebelum HTTP sukses.
- [x] Role runtime, migrasi, dan administrator dipisahkan.
- [x] Container API non-root, read-only, capabilities dilepas, no-new-privileges.
- [x] PostgreSQL tidak memiliki published host port; API localhost.
- [x] PostgreSQL/migrator/CLI hanya di network internal; bridge tambahan hanya untuk API.
- [x] Secret file dipasang hanya pada layanan yang membutuhkan.
- [x] Body size/time limit, request ID, host allowlist, no-store, nosniff.
- [x] Log/metric label menghindari raw URL, input, header/token, dan isi exception.
- [x] Kelayakan provider menolak training/retensi tidak diketahui dan biaya tidak diketahui.
- [x] Dependency lock dan digest image; CI dengan permission read-only dan action commit pin.

Tanda di atas menyatakan implementasi tersedia. Bukti eksekusi tiap lapisan dibedakan di
`docs/VERIFICATION.md` untuk snapshot historis dan `docs/STAGE_2A_VERIFICATION.md` untuk
hasil terbaru. Fondasi telah diuji pemilik; migrasi/worker baru masih memerlukan gate native.

Hotfix jaringan menambahkan bridge `api_access` pada API untuk publikasi port localhost.
Bridge ini juga mengizinkan koneksi keluar API; tidak ada isolasi internet penuh pada
proses API. Tidak ada integrasi cloud/dokumen aktif pada Tahap 1. Kontrol tujuan dan data
keluar wajib diterapkan sebelum integrasi AI/tool. Lihat `docs/HOTFIX_LOCALHOST.md` untuk
bukti runtime pengguna dan batas validasi hotfix.

## Syarat penerimaan sebelum data nyata

- [ ] Unit, native PostgreSQL integration, migrasi ulang, dan runtime Docker smoke lulus pada mesin tujuan/CI.
- [ ] Uji dua owner menunjukkan pembacaan/penulisan lintas owner ditolak.
- [ ] Race pairing menghasilkan satu konsumsi sukses; request ulang tidak menggandakan identity.
- [ ] Role runtime dan hak SQL telah diperiksa dengan koneksi `jarvis_app`, bukan admin `SET ROLE` saja.
- [ ] SSH memakai key; sistem/Docker diperbarui; akses root/Docker dibatasi.
- [ ] Pemeriksaan port dari luar host: PostgreSQL dan API tidak terbuka publik.
- [ ] File secret dan direktori induk terlindungi; ACL Windows/WSL diperiksa jika relevan.
- [ ] Enkripsi disk/volume sesuai kebutuhan dan kemampuan penyedia telah diputuskan.
- [ ] Backup terenkripsi di luar host, retensi dan kunci terpisah tersedia; restore berhasil diuji.
- [ ] Pemulihan token, revokasi, suspend, restart, dan kegagalan database diuji operator.
- [ ] Image/container OS turut dipindai; audit Python tidak mencakup paket OS/image.
- [ ] Kapasitas RAM/disk serta alert kegagalan/backup ditetapkan berdasarkan pengukuran.

## Gate untuk tahap AI dan dokumen

- [ ] Verifikasi kebijakan endpoint aktual dan account settings; tanpa prompt logging/opt-in penggunaan konten.
- [ ] Adapter mengirim aturan no-training/ZDR, allowlist eksplisit, plugin mati; kebijakan/harga berubah harus gagal tertutup.
- [ ] Tidak ada fallback premium tanpa persetujuan atomik sekali pakai per upaya, termasuk retry.
- [ ] Tool registry menolak shell, credential store, Docker socket, dan tujuan jaringan tidak diizinkan.
- [ ] Parser file punya batas ukuran/halaman/waktu/memori dan tidak mengeksekusi macro/kode dokumen.
- [ ] URL fetch aman dari SSRF, redirect ke alamat privat, dan DNS rebinding sesuai desain fetcher.
- [ ] ACL retrieval memfilter owner sebelum konteks dikirim; vector bukan anonimisasi.
- [ ] Penghapusan mencakup file, teks, index, cache, job, dan kebijakan backup.
- [ ] Telegram hanya menerima private chat identity yang telah dipasangkan; update idempotent.

## Penanganan insiden awal

Jika token diduga bocor, cabut token melalui CLI dan terbitkan pengganti. Bila akun/mesin
dicurigai diambil alih, hentikan akses jaringan yang terdampak, suspend owner, dan periksa
host serta kredensial sebelum menyalakan layanan kembali. Penggantian pepper mencabut
validitas seluruh token lama. Catat request ID/waktu kejadian tanpa menyalin dokumen atau
token rahasia ke issue tracker. Tidak ada endpoint pelaporan publik dalam proyek privat ini.

## Tambahan review Tahap 2A

Kontrol yang diterapkan pada kode (status pengujian terpisah di STAGE_2A_VERIFICATION):

- ID sender numerik allowlist, private chat ID yang sama, bukan bot, owner aktif dan pairing.
- Forward, edit, channel, grup, business/delegated updates ditolak.
- Transaksi bersama untuk konsumsi pairing, receipt dan cursor; primary key mencegah replay.
- Session advisory lock satu poller, cursor durable, RLS tujuh tabel, parameterized SQL.
- Tidak menyimpan input/raw update; output template whitelist, tanpa link preview/paid broadcast.
- Client HTTPS tujuan tetap, TLS verification default, proxy lingkungan/redirect dimatikan,
  respons maksimum 1 MiB, batas timeout, error tanpa URL/token/body.
- Connect failure yang pasti belum terkirim dapat retry; kegagalan kirim ambigu tidak retry.
- Otorisasi diperiksa kembali saat claim antrean; disable tidak membatalkan kiriman in-flight.
- File setup exclusive, token entry tersembunyi tanpa fallback echo, ID challenge dikonfirmasi lokal.
- Secret bot hanya dipasang pada worker; API dan CLI status/pair tidak menerima token bot.
- Worker non-root/read-only/capabilities dropped, resource/log limits, tanpa published port.

Gate yang masih memerlukan bukti di lingkungan pemilik:

- [ ] Seluruh native integration termasuk transaksi konkuren, RLS Telegram, advisory lock lulus.
- [ ] Upgrade volume lama/mount secret dan healthcheck image v0.2.0 lulus di Docker Windows.
- [ ] Pairing/perintah private chat, akun asing ditolak, disable dan restart diuji.
- [ ] ACL file Windows, akses Docker, perangkat Telegram dan verifikasi dua langkah ditinjau.
- [ ] Backup terenkripsi luar host, restore terisolasi, monitoring dan image scan sebelum produksi.

Bot tidak menyediakan shell, HTTP arbitrary, pencarian web, atau tool dari teks pengguna.
Kompromi token bot tetap serius: pemegangnya dapat mengakses bot melalui Telegram; revoke
melalui BotFather dan stop worker. Kode aplikasi yang memvalidasi ID tidak melindungi
penggunaan token curian langsung ke Telegram. Jangan membagikan output pairing/credential.

## Gate tambahan Tahap 2B

- RLS lima tabel AI; biaya/konteks dipisah dari log dan state LangGraph.
- No-training/ZDR/only-provider/max_price ditegakkan sebelum dispatch dan pada HTTP.
- Premium: konfigurasi bukan izin; butuh consent sekali pakai yang terikat snapshot/plan.
- Ledger dicadangkan atomik sebelum POST; tidak ada SDK/HTTP retry otomatis.
- Crash/timeout setelah dispatch tetap uncertain; bukan exactly-once delivery.
- Secret model hanya worker/catalognya; token bot hanya worker Telegram.
- Runtime DB role dapat mengakses seluruh modul milik tenant jika proses dikompromikan;
  RLS bukan pembatas bagi host/admin DB atau proses yang sudah menguasai kredensial.
- Metadata provider dan aturan retention adalah trust boundary eksternal. Tag provider
  dapat menunjuk beberapa infrastruktur internal provider, bukan identitas server fisik.
- Endpoint response tidak cocok/biaya tak terverifikasi membekukan inference. Belum ada
  rekonsiliasi otomatis atau resume untuk ledger uncertain; operator harus menyelidikinya.
- PostgreSQL dan backup lokal belum dienkripsi per kolom. Proteksi disk/OS dan restore
  backup, image/OS scanning, ingress/egress firewall VPS, serta monitoring tetap gate produksi.

Checklist terperinci di STAGE_2B_DESIGN.md; status nyata ada di STAGE_2B_VERIFICATION.md.


## Implementasi dan gate Tahap 3 (0.4.0)

- Parser terisolasi: tanpa secret/DB/volume, jaringan internal, non-root, readonly,
  satu parsing aktif, child deadline/CPU/memori/output bounded; ZIP DOCX dan XML
  divalidasi sebelum ekstraksi, macro tidak dieksekusi.
- Worker knowledge tidak memegang key OpenRouter/token bot atau egress internet.
  Embedding lokal dipatok revisi serta checksum; runtime hanya membaca cache model.
- PostgreSQL/FORCE RLS mencakup 15 tabel tenant. Qdrant memfilter owner/dokumen;
  semua ID hasil retrieval diverifikasi ulang terhadap chunk aktif milik owner di DB.
- Path file berupa UUID dengan penolakan symlink; batas file/owner/chunk membatasi
  penggunaan disk. Rate/lease/attempt dan worker advisory lock membatasi eksekusi.
- Delete menutup akses sebelum cleanup; snapshot divalidasi ulang saat prepare,
  approval, dispatch dan finish. Dokumen tidak dapat mengubah izin atau budget.
- Dokumen restricted tidak dikirim ke AI; kutipan private hanya melalui kebijakan
  assistant yang sama. Tidak ada tool eksekusi atau URL fetch dari dokumen.

Status bukti aktual, termasuk keterbatasan pengujian native PostgreSQL/Docker,
ada di docs/STAGE_3_VERIFICATION.md. Image/OS scan, enkripsi disk, akses host,
backup/restore volume lengkap, dan kapasitas OCR di komputer pemilik tetap gate
operasional; unit test tidak membuktikan seluruh deployment aman.
