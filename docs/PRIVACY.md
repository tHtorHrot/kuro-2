# Dokumen dan privasi — Opsi A

Dalam Jarvis, “dokumen” mencakup PDF, Word, catatan, hasil OCR, potongan teks, metadata,
embedding, dan salinan cadangan yang nanti digunakan untuk menjawab pertanyaan. Menghapus
file asli saja belum cukup bila potongan teks dan indeksnya masih tersimpan.

## Empat hal yang berbeda

| Istilah | Makna untuk rancangan ini |
|---|---|
| Privat | Akses aplikasi dibatasi kepada pemilik; tidak ada link publik otomatis |
| Pemrosesan cloud | Pertanyaan dan konteks terpilih dikirim ke router/provider agar model menjawab |
| Tidak digunakan untuk training | Provider tidak diizinkan memakai data tersebut untuk melatih model menurut kebijakan endpoint |
| Zero Data Retention | Pembatasan retensi menurut kebijakan endpoint; bukan berarti data tidak diproses atau tidak pernah berada di memori |

Contoh nanti: sebuah PDF disimpan di server pribadi. Ketika pemilik bertanya tentang
satu bagian, retrieval memilih potongan relevan. Potongan itu dapat dikirim ke model cloud
sesuai Opsi A. File tidak menjadi publik, tetapi provider tetap memproses isi potongan.
Kebijakan cloud juga harus mencakup riwayat percakapan dan memory yang disertakan sebagai
konteks. Mengirim potongan lebih sedikit mengurangi paparan, bukan menghilangkannya.

## Kebijakan router

Dokumentasi OpenRouter membedakan retensi prompt, penggunaan input/output, dan metadata.
Logging input/output serta penggunaan konten harus tetap tidak diaktifkan. Metadata
permintaan masih dikumpulkan; dokumentasinya juga menyebut kategorisasi anonim sebagian
prompt. Karena itu “dataku tidak dipakai sama sekali oleh pihak luar” lebih ketat daripada
Opsi A dan memerlukan pemrosesan lokal yang dirancang tersendiri.

Filter ZDR OpenRouter berlaku pada routing inference, tidak otomatis melindungi plugin
atau tool eksternal. OpenRouter juga mengizinkan cache prompt di memori dalam interpretasi
ZDR-nya. Rancangan menonaktifkan plugin secara default, mensyaratkan kebijakan endpoint
yang jelas, dan menolak kebijakan tidak diketahui. Label open-source/gratis tidak menentukan
kebijakan privasi layanan hosting model.

Sumber resmi diperiksa 28 September 2026:

- [Data Collection](https://openrouter.ai/docs/guides/privacy/data-collection)
- [Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr)

Kode `policies/privacy.py` pada Tahap 1 menguji kelayakan kebijakan saja. API key,
pengaturan akun OpenRouter, allowlist provider aktual, dan pengiriman konten belum aktif.
Tidak ada klaim bahwa pengaturan akun eksternal pengguna sudah diubah.

## Telegram dan file sensitif

Bot Telegram memakai chat cloud, bukan Secret Chat end-to-end. Pesan/file yang dikirim
ke bot melewati layanan Telegram. Karena itu file yang tidak boleh berada di Telegram
jangan dikirim melalui bot. Pada tahap ingestion akan disediakan jalur upload privat
di server/web agar pengguna dapat memilih jalur selain Telegram.

Rujukan: [Telegram FAQ — Secret Chats](https://telegram.org/faq#q-how-are-secret-chats-different).
Pembatasan owner ID mencegah orang lain menggunakan bot Jarvis, tetapi tidak mengubah
model penyimpanan pesan Telegram.

## Klasifikasi dan penyimpanan

| Kelas | Rencana perilaku |
|---|---|
| Public | Boleh ke cloud yang lolos kebijakan, tetap tidak dipublikasikan otomatis |
| Personal | Akses pemilik; konteks minimum ke endpoint yang lolos kebijakan |
| Restricted | Tidak boleh keluar ke model cloud; tolak jika fungsi lokal belum tersedia |

Kredensial, password, API key, dan data yang pemilik tandai sangat sensitif tidak boleh
dianggap konteks LLM. Embedding bukan anonimisasi; Qdrant dan payload teks memerlukan
kontrol akses dan backup yang sama dengan file asli.

Keputusan implementasi tahap dokumen: ekstraksi dan embedding kecil dijalankan lokal;
isi dokumen diperlakukan sebagai data tidak tepercaya, bukan instruksi untuk menjalankan
tool. Penghapusan harus mencakup file, chunk, vector, cache, dan metadata job. Salinan
backup hilang mengikuti retensi backup yang ditetapkan; tidak dijanjikan terhapus seketika.

## Batas perlindungan yang perlu dipahami

- Operator/root server dan pihak hosting berada dalam batas kepercayaan. Aplikasi tidak
  dapat menjamin kerahasiaan terhadap host yang sudah dikuasai.
- Volume PostgreSQL dan file Compose secrets pada paket ini tidak dienkripsi oleh aplikasi.
  Enkripsi disk dan backup harus ditetapkan dalam deployment sebelum data sensitif masuk.
- Hash token melindungi token mentah di database; pepper wajib dijaga terpisah dari dump.
- Log aplikasi memakai daftar field terbatas dan tidak merekam body. Administrator tetap
  perlu mencegah tracing/proxy/debug lain merekam payload atau header authorization.
- Persetujuan biaya premium tidak membatalkan aturan privasi dan bukan izin mempublikasikan data.

Pada Tahap 1 belum tersedia upload, conversation memory, atau penyimpanan dokumen.
Validasi awal menggunakan data contoh, sehingga kebijakan retensi dokumen belum dijalankan.

## Data aktual pada Tahap 2A

| Data | Tempat/proses | Retensi |
|---|---|---|
| Pesan yang dikirim ke bot | Telegram cloud, lalu memori worker selama pemrosesan | Mengikuti Telegram untuk salinan mereka; tidak disimpan sebagai teks chat oleh Jarvis |
| Token bot | File secret lokal dan memori worker; endpoint HTTPS Telegram | Sampai dirotasi/dicabut; tidak masuk log/artefak |
| Kode pairing mentah | Output CLI sekali, pesan pairing di Telegram, memori worker | Di Jarvis hanya digest yang disimpan; kode 10 menit dan satu pemakaian |
| ID owner/bot/sender/chat | Config privat, identitas dan state di PostgreSQL | Bertahan untuk otorisasi sampai proses penghapusan/migrasi terkelola |
| Receipt pengiriman | ID update/chat, template key, status/retry/waktu/message ID | Terminal dibersihkan setelah 48 jam saat worker berjalan, dengan cleanup berbatas |
| Audit pairing/enable/disable | PostgreSQL append-only dari role runtime | Bertahan; retensi/penghapusan terkelola belum diotomatisasi |
| Backup database | File lokal dalam `backups` | Dikelola pemilik; belum ada cleanup/enkripsi otomatis |

Tidak ada unduhan lampiran, penyimpanan isi chat, panggilan LLM, embedding, atau pelatihan
model pada Tahap 2A. Ini tidak menghapus pemrosesan oleh Telegram terhadap pesan yang
sudah dikirim. Fitur `protect_content` membatasi forward/save melalui fitur Telegram;
tidak mencegah screenshot, penyalinan manual, perangkat kompromi, atau pemrosesan provider.

Penghapusan receipt bukan penghapusan secure-erase dari WAL, snapshot, dump, maupun server
Telegram. Retensi backup dan audit memerlukan kebijakan tersendiri sebelum dokumen nyata.
Untuk kebutuhan “dokumen hanya untuk saya”, jalur upload privat akan dibuat pada Tahap 3;
Telegram tidak diposisikan sebagai Secret Chat E2EE atau bukti no-training/ZDR.

## Perubahan pada Tahap 2B

Pernyataan historis Tahap 2A bahwa isi chat tidak disimpan hanya berlaku pada 2A.
Saat 2B aktif, `/ask` menyimpan prompt/snapshot/hasil dalam PostgreSQL privat sampai
30 hari. Profil tersimpan sampai `/forget`; `/clear` membersihkan isi aktif lokal,
bukan profil, metadata ledger/audit, salinan Telegram atau backup. Receipt balasan AI
bersifat sementara dan teksnya dihapus setelah pengiriman/hasil terminal, paling lambat
pembersihan receipt 48 jam saat worker berjalan. Riwayat lama tidak dipakai sebagai konteks
setelah `/new`; /clear membersihkannya. Jika worker berhenti, cleanup menunggu worker aktif.

Pertanyaan, profil dan riwayat terpilih diproses OpenRouter/provider cloud. Endpoint dicek
ZDR, request membatasi data_collection=deny dan zdr=true. Pengaturan akun input/output
logging harus dimatikan oleh pemilik. Menurut definisi OpenRouter, caching sementara dalam
memori bisa kompatibel dengan ZDR. Tidak ada jaminan kriptografis bahwa pihak ketiga tidak
pernah melihat konten. Tidak ada embedding, upload dokumen atau plugin provider di 2B.
Klasifikasi restricted eksplisit dan filter pola secret gagal tertutup; deteksi pola tidak
bisa mengenali seluruh informasi sensitif. Jangan masukkan data restricted melalui /ask.


## Perubahan aktual pada Tahap 3 (0.4.0)

Bagian tahap sebelumnya di atas adalah catatan historis. Saat ini upload lewat
`scripts/documents.py` dari komputer ke Docker, bukan lewat lampiran Telegram.
Parser lokal tidak mendapat database, secret, volume sumber, atau akses internet.
Worker melakukan embedding lokal; hanya pengunduh model eksplisit yang mengambil
bobot dari repositori model dengan revisi dan SHA-256 dipatok.

Kelas yang tersedia pada CLI adalah **private** dan **restricted**. Private berarti
pemilik mengizinkan pertanyaan beserta maksimal empat kutipan relevan dikirim saat
`/askdoc` ke endpoint AI yang lolos aturan assistant. Restricted tetap dapat disimpan
dan diindeks lokal, tetapi `/askdoc` ditolak sebelum inference. Antarmuka pencarian
teks lokal restricted belum tersedia. Nama file restricted disembunyikan di bot;
operator lokal tetap dapat melihat metadata.

File asli disimpan pada volume privat `document-data`. Teks/chunk, metadata, antrean,
dan snapshot pertanyaan berada di PostgreSQL. Qdrant menyimpan embedding serta ID
owner/dokumen, tanpa teks. Embedding tetap merupakan data sensitif. Dokumen tidak
mempunyai kedaluwarsa otomatis; hapus secara eksplisit. Snapshot pertanyaan mengikuti
retensi request assistant 30 hari dan `/clear`; jawaban dokumen tidak masuk history
percakapan umum. Receipt sementara mengikuti cleanup Telegram yang sudah ada.

`/deldoc` segera menolak penggunaan dokumen berikutnya, membatalkan request terkait
serta membersihkan snapshot/balasan lokal terkait. Worker kemudian menghapus vector,
file dan chunk; status `deleting` menunggu cleanup berhasil, bukan klaim selesai.
Tombstone UUID/status/waktu dan ledger biaya tanpa isi tetap disimpan. Panggilan cloud
atau kiriman Telegram yang sudah dimulai tidak dapat ditarik kembali. Salinan Telegram,
WAL/snapshot dan backup lama tidak ikut dihapus oleh perintah tersebut.

Filter secret adalah perlindungan tambahan, bukan klasifikasi isi yang sempurna.
Kutipan tidak boleh diperlakukan sebagai instruksi/otorisasi. Validasi label sumber
juga tidak menjamin setiap klaim AI benar. Uji dengan fixture sebelum dokumen nyata.
`backup_local.py` hanya mencadangkan PostgreSQL; backup lengkap Tahap 3 memerlukan
volume sumber dan indeks yang konsisten. Lihat KNOWLEDGE_WINDOWS.md.
