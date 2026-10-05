# Kesiapan hosting KURO

**KURO dapat ditargetkan ke server privat, tetapi kandidat ini belum siap dinyatakan sebagai deployment produksi yang diterima.** Tidak perlu menunggu seluruh Stage 8 untuk mulai private pilot. Yang wajib selesai sebelum pilot dengan tindakan eksternal adalah Stage 4 dan gate operasional Stage 5 yang relevan.

## Bentuk hosting yang sesuai kode sekarang

Project ini memiliki PostgreSQL persisten, Qdrant, penyimpanan dokumen, model embedding lokal, parser OCR dan worker yang terus berjalan. Bentuk awal yang sesuai adalah satu server Linux dengan Docker Compose dan storage persisten. Ini mengikuti struktur Compose yang sudah ada. Docker mendokumentasikan penggunaan Compose pada satu server produksi [1].

Untuk antarmuka Telegram saja, domain publik dan web dashboard tidak menjadi prasyarat. Bot sekarang memakai long polling; Telegram mendukung mekanisme tersebut [2]. Dengan pola ini worker menghubungi Telegram dari server. API dapat tetap terikat localhost dan administrasi melalui koneksi privat. Ini inferensi arsitektur dari pola long polling dan Compose saat ini, bukan klaim firewall suatu server sudah diperiksa.

Jangan mengekspos PostgreSQL, Qdrant, parser atau metrics ke internet. Domain/TLS/reverse proxy baru perlu dirancang ketika ada antarmuka web publik atau webhook. Web UI dan voice adalah perluasan terpisah dari target backend Stage 8, kecuali pengguna menambahkannya ke scope.

## Apa yang perlu diputuskan

| Keputusan | Informasi yang dibutuhkan | Mengapa |
|---|---|---|
| Target | Komputer lokal yang selalu hidup atau VPS/server Linux | Menentukan uptime, backup, operasi dan akses |
| Anggaran | Batas server/storage/backup dan batas inference terpisah | Nilai legacy konfigurasi bukan pengendali tagihan provider |
| Data | Jenis dokumen dan klasifikasi restricted/private | Menentukan retensi, lokasi backup, akses cloud |
| Provider | Calendar serta provider Research/Email/LLM | Menentukan OAuth/scopes, hasil tes dan biaya |
| Pemulihan | RPO/RTO dan lokasi backup terpisah | Menentukan jadwal backup dan kapasitas restore |
| Akses | Pemilik tunggal atau penggunaan multi-owner nyata | RLS sudah ada, tetapi onboarding/admin multi-user belum menjadi produk lengkap |

Tidak ada password, API key, refresh token atau private key yang perlu ditempelkan ke percakapan. Provisioning dilakukan melalui secret files/secret manager pada lingkungan target setelah target dipilih.

## Kapasitas harus diukur

Dokumentasi deployment lama menyebut sekitar 2 GB untuk fondasi API/PostgreSQL. Itu bukan ukuran yang sudah tervalidasi untuk stack penuh. Batas memori yang tertulis di Compose untuk service utama adalah:

| Service | Batas konfigurasi |
|---|---:|
| PostgreSQL | 512m |
| API | 384m |
| Assistant | 384m |
| Telegram | 256m |
| Knowledge | 1200m |
| Parser | 1024m |
| Qdrant | 768m |
| Scheduler | 256m |

Total plafon service tersebut adalah 4784m, belum termasuk OS, Docker, build, migrator, helper dan cache filesystem. Plafon bukan RAM yang selalu terpakai dan bukan hasil sizing server. Ukur beban percakapan, ingestion/OCR, embedding dan scheduler secara bersamaan sebelum membeli kapasitas. Harga/provider server belum dipilih atau dibandingkan dalam audit ini.

## Urutan deployment yang dapat diterima

1. Build release dan jalankan full suite pada test environment terisolasi; simpan source/image digest dan hasil tes.
2. Tutup product acceptance Stage 4, termasuk revoke-before-dispatch, duplicate prevention, result delivery dan real Calendar smoke yang bounded.
3. Siapkan server privat, login SSH berbasis key, patch OS, network rules dan secret provisioning. Gunakan image release yang sama dengan bukti pengujian.
4. Jalankan migrasi satu kali, lalu health seluruh service. Memakai PostgreSQL/Qdrant persisten dan izin volume yang benar. Jangan mengulang setup owner di instalasi lama.
5. Uji backup/restore pada target kosong. Writer/executor harus frozen selama restore dan rekonsiliasi action yang belum pasti.
6. Jalankan pilot terbatas. Monitor worker heartbeat, queue age, action uncertain, provider errors, disk/RAM dan biaya. Bukti keberhasilan berasal dari hasil aktual.
7. Aktifkan Stage 6–8 hanya setelah gate masing-masing lulus. Rilis baru tidak boleh menghilangkan kemampuan rollback.

## Yang menghalangi deployment sekarang

- Jalur Calendar chat, pemeriksaan izin, hasil durable dan solo reconciliation sudah
  diimplementasikan; acceptance native kandidat final dan smoke Google nyata belum lulus.
- Unit/offline kandidat final lulus 366 tes dan 83 subtes. Native baseline lama lulus
  389/81; hasil itu tidak mencakup seluruh perubahan akhir. Lingkungan terbaru tidak
  dapat menjalankan PostgreSQL non-root, dan eskalasi ditolak oleh policy sesi.
- Clarification/follow-up bebas dan scheduled execution melalui chat belum lengkap.
- Backup lengkap terenkripsi, restore drill, rollback, alert dan operasi host belum dibuktikan.
- Target server, provider specialist dan akses deployment belum ditentukan.

Tidak ada tambahan tahap tanpa batas di luar roadmap: pekerjaan di atas adalah isi konkret Stage 4 dan Stage 5. Setelah itu pilot dapat berjalan sambil Stage 6–8 dikembangkan, dengan perubahan tetap melalui staging dan release gate.

## Referensi

1. [Docker Compose in production](https://docs.docker.com/compose/how-tos/production/), diperiksa 2 Oktober 2026.
2. [Telegram Bot FAQ — getting updates](https://core.telegram.org/bots/faq#getting-updates), diperiksa 2 Oktober 2026.

