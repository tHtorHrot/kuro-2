# Catatan keputusan desain

Tanggal: 28 September 2026. Dokumen ini memperjelas keputusan setelah pengguna memilih
Opsi A dan meminta biaya sekitar Rp100 ribu serta persetujuan setiap fallback premium.

## ADR-001 — Cloud privat dengan pembatasan

Dipilih: file/metadata milik pemilik, tidak ada publikasi umum; pemrosesan cloud boleh
untuk konten yang diizinkan melalui endpoint terverifikasi no-training dan ZDR.
Konten berlabel restricted tidak boleh dikirim ke cloud. Kebijakan tidak diketahui ditolak.
Dokumen privat tetap dapat diproses pihak ketiga sesuai pengaturan ini; tidak dijanjikan
bahwa tidak ada pihak lain yang memprosesnya. Lihat PRIVACY.md.

Status Tahap 1: policy eligibility telah ada. Provider adapter, unggah dokumen, dan
penegakan pada panggilan jaringan belum diperlukan karena belum ada panggilan LLM.

## ADR-002 — Premium harus disetujui setiap penggunaan

`premium_mode` hanya menerima `confirm_each_use`. Model gratis gagal/rate limited tidak
boleh otomatis beralih ke berbayar. Privasi tetap harus lolos meskipun pengguna menyetujui biaya.

Kontrak Tahap 2: satu persetujuan berlaku untuk **satu upaya panggilan premium** yang
terikat owner, request ID, hash konteks, model/endpoint, harga yang diperiksa, batas token,
estimasi biaya maksimum, dan TTL. Konsumsi persetujuan harus atomik. Retry premium atau
perubahan model/konteks memerlukan persetujuan baru. Jika status panggilan ambigu setelah
timeout, jangan mencoba ulang diam-diam. Tidak ada persetujuan global/selamanya.

Ini masih kontrak tahap berikutnya; UI konfirmasi, ledger biaya, dan konsumsinya belum
diimplementasikan dalam rilis fondasi ini.

## ADR-003 — Biaya dan server fleksibel

Target Rp100.000/bulan adalah anggaran infrastruktur, dengan kenaikan kecil dibicarakan
terlebih dahulu. Penyedia dan spesifikasi belum dipilih. Prioritaskan satu VPS kecil,
tanpa GPU, managed database, Kubernetes, atau domain berbayar pada awalnya.

Amplop perencanaan: usahakan server Rp70–85 ribu dan sisanya untuk pajak/cadangan/backup.
Ini **alokasi**, bukan penawaran harga yang sudah tersedia. Bila penawaran aktual
termasuk pajak dan backup melampaui target, validasi lokal dahulu dan pilih penyesuaian
bersama pengguna; jangan diam-diam menambah layanan. Biaya model premium terpisah,
dengan estimasi ditampilkan pada setiap permintaan persetujuan.

Kebutuhan awal diuji dari satu vCPU dan sekitar 2 GB RAM untuk fondasi. Tahap dokumen
harus diukur lagi sebelum memutuskan upgrade. Besar file, antrean, concurrency, dan jumlah
konteks dibatasi. Ketersediaan model gratis tidak dijanjikan. Jika tidak ada endpoint
gratis yang memenuhi privasi, tugas menunggu/ditolak atau meminta persetujuan berbayar.

## ADR-004 — Modular monolith dan PostgreSQL native

FastAPI + SQLAlchemy async + psycopg + Alembic. PostgreSQL menjadi sumber kebenaran.
RLS menjadi pertahanan tambahan atas filter owner di aplikasi. Role runtime tidak boleh
superuser, BYPASSRLS, pemilik tabel, pembuat role/database, replication, atau anggota role lain.

Tidak memakai SQLite sebagai pengganti uji PostgreSQL. PGlite hanya pemeriksaan SQL
tambahan; belum membuktikan perilaku driver, pool, locking, atau jaringan PostgreSQL 16.
Qdrant tetap arsitektur tujuan, ditambahkan ketika ingestion/retrieval diimplementasikan.

## ADR-005 — Telegram polling setelah fondasi

Tahap 2 menggunakan long polling agar tidak memerlukan domain/webhook publik. Hanya
pesan pribadi dari identity yang sudah dipasangkan boleh diterima. Adapter memeriksa
provenance update; endpoint untuk menyuntikkan ID Telegram bebas tidak disediakan.
Satu polling worker dengan locking/idempotensi dibutuhkan agar restart tidak menggandakan
efek. Bot token disimpan sebagai secret. File sensitif akan dapat diunggah lewat interface
privat lain pada tahap berikutnya bila pengguna tidak ingin file melewati Telegram.

## ADR-006 — Surface operasi kecil

Satu worker API, API localhost, private database network, tidak ada frontend publik.
Compose secrets berupa file host yang dipasang selektif ke container; bukan vault terenkripsi.
Image Python/PostgreSQL dikunci digest dan library dikunci `uv.lock`. Update keamanan
berkala harus mengubah lock/digest melalui review dan pengujian.

Token opaque dipilih agar pencabutan langsung dapat dicek di database. Akun dibuat melalui
CLI operator; tidak ada pendaftaran umum atau pemulihan melalui email pada tahap ini.
CLI operator adalah jalur istimewa yang harus dijauhkan dari tool registry LLM.
