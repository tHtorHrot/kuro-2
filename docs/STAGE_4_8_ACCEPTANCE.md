# Acceptance Stage 4–8

Update kandidat 5 Oktober 2026: source Stage 4h/schema 0009 sudah mengimplementasikan klarifikasi durable, scheduled execution dan detached delivery. Stage 4 tetap OPEN sampai native gate dan live delta pada kandidat diterima. Write acceptance sebelumnya diterima menurut USER_REPORTED; bukan bukti untuk source baru. Stage 5 fondasi operasi tersedia, seluruh S5 gate belum ditutup. Status/bukti saat ini: CHECKPOINT.json, WORK_MATRIX.md dan evidence/stage-4h/.

## Aturan penutupan

Setiap gate mempunyai release/source hash, lingkungan, waktu tes, hasil aktual dan artefak bukti. Status yang dipakai: `OPEN`, `IMPLEMENTED`, `TESTED_LOCAL`, `TESTED_INTEGRATION`, `ACCEPTED_PRODUCTION`. Stage baru boleh `FROZEN` setelah seluruh gate wajib diterima pada versi yang sama. Tes yang di-skip karena dependency/service tidak ada tidak dihitung lulus.

Sebuah release tetap boleh dipakai untuk pilot dengan subset fitur yang sudah diterima; fitur yang belum diterima harus dinonaktifkan. Klaim keberhasilan tindakan berasal dari journal/provider evidence, tidak dari prosa LLM. Tidak ada target '100% aman' tanpa batas: kasus uji dan residual risk wajib eksplisit.

## Stage 4 — Close the loop

| ID | Implementasi/output wajib | Skenario penerimaan |
|---|---|---|
| S4-01 | Natural chat memakai queue/privacy/budget yang sama dengan `/ask` | Pesan biasa → satu request → satu jawaban; replay update tidak menambah inference |
| S4-02 | Trusted ingress immutable; planner tidak membawa flag izin | Negasi, pertanyaan, kutipan, forwarded text dan argumen yang diganti model tidak memberi auto-authority |
| S4-03 | Calendar read melalui execution boundary | 'Apa jadwalku besok?' memakai zona owner, rentang benar, pagination/batas eksplisit dan hasil bersumber provider |
| S4-04 | Create solo lengkap atau clarification durable | Instruksi lengkap membuat satu event; jam akhir/title/tanggal ambigu ditanyakan; tidak mengarang waktu |
| S4-05 | Current owner/scope/policy diperiksa pada dispatch | Suspend/revoke setelah antre atau sebelum dispatch mencegah HTTP write |
| S4-06 | Tool approval terpisah dari premium consent | Invite/delete membutuhkan persetujuan exact action, TTL, sekali pakai; perubahan payload/due time membatalkannya |
| S4-07 | Cancel terikat task/action dan status | Cancel queued/claimed berhasil; cancel in-flight tidak mengklaim membatalkan efek yang sudah terkirim |
| S4-08 | Deduplikasi source-task-step dan provider reconciliation | Crash sebelum dispatch boleh recover; crash setelah insert tidak menggandakan event; `uncertain` tidak di-retry buta |
| S4-09 | Hasil provider dan notifikasi durable | Event ID dan result disimpan; retry Telegram hanya mengirim hasil, tidak mengulang create |
| S4-10 | Scheduler timezone, lease/fencing dan shutdown | Scheduled action survive restart; DST gap/fold tidak ditebak; lease stale ditolak; action lain tetap diproses |
| S4-11 | Typed arguments/output dan provider budgets | Type/range/email/ID invalid gagal sebelum dispatch; respons besar, halaman banyak dan provider timeout terkendali |
| S4-12 | Full regression dan bounded production smoke | Unit/lint/native PG/RLS/Qdrant/OCR/migrasi lulus; real Calendar test memakai kalender uji dan persetujuan untuk efek eksternal |

**Contoh produk:** 'Buat rapat besok jam 10' belum lengkap tanpa aturan durasi yang sudah disetujui. KURO meminta durasi atau memakai preferensi pengguna yang sudah tervalidasi dan menampilkan waktu akhirnya. 'Buat acara untuk besok' berbeda dengan 'besok jalankan pembuatan acara'; event start dan action `due_at` harus dibedakan.

**Desain state berikutnya:** task mengikat owner/source/conversation/revision; proposal memuat argumen tervalidasi; action memuat source-step key, policy/grant reference, due time, approval dan lease; result menyimpan external reference; outbox menyimpan delivery key. Semua owner-scoped, transaksional, dengan migration baru. Google secret tetap hanya pada execution worker, termasuk operasi read.

**Gate freeze:** S4-01 sampai S4-12 lulus. Keberadaan gateway, status doctor `stage=4`, atau migration head saja tidak menutup stage.

## Stage 5 — Operations

| ID | Output wajib | Skenario penerimaan |
|---|---|---|
| S5-01 | Deployment privat yang dapat diulang dari release immutable | Server/VM bersih → install → health seluruh service; DB/Qdrant tidak dipublikasikan |
| S5-02 | Monitor health, queue age, failed/uncertain, lease dan resource | Matikan satu worker; alarm muncul dalam jendela yang ditetapkan; log tanpa prompt/token |
| S5-03 | Backup konsisten dan terenkripsi di luar host | DB + file + index/rebuild metadata + release/schema/config fingerprint tersedia dan checksum diverifikasi |
| S5-04 | Restore drill pada target disposable | Owner, pairing, memory, dokumen, retrieval, pending approvals dan jobs pulih; executor frozen sampai rekonsiliasi selesai |
| S5-05 | Rollback/roll-forward yang kompatibel schema | Image lama hanya dipakai bila kompatibel; migration destruktif tidak ditebak balik; smoke ulang lulus |
| S5-06 | Secret lifecycle dan incident response | Rotasi bot/LLM/OAuth/DB/HMAC terencana; secret lama dicabut; worker bisa recover tanpa mencetak secret |
| S5-07 | Profiling kapasitas dan failure handling | Beban chat + OCR + scheduler diukur; timeout/backpressure bekerja; disk penuh/DB down gagal terkendali |

**Target awal yang diusulkan, belum disepakati atau diukur:** RPO backup maksimal 24 jam, RTO restore maksimal 60 menit untuk private pilot kecil; alarm worker stale dalam 2 menit. Jadwal backup, retensi dan kapasitas harus disesuaikan volume nyata dan biaya. Nilai ini bukan SLA atau hasil tes.

Backup harus memiliki manifest: waktu UTC, release digest, schema head, hash/size tiap komponen, identitas key enkripsi tanpa secret, dan cara memperoleh model embedding yang persis sama. Gunakan snapshot konsisten atau jeda writer yang terbatas. Pemulihan action yang dulu dispatching harus frozen/uncertain sampai provider direkonsiliasi. Restore DB tidak membatalkan efek di luar sistem.

**Gate freeze:** restore nyata terukur, rollback diuji, monitor dan runbook dapat dipakai. Script backup tanpa restore tidak cukup.

## Stage 6 — Personal Intelligence

| ID | Output wajib | Skenario penerimaan |
|---|---|---|
| S6-01 | Model memory terpisah: profil, preference, proyek, episodic, task | Setiap record punya owner, jenis, provenance, waktu, kelas data, retention dan status validasi |
| S6-02 | Context selection berdasarkan task dan project | Kumpulan pertanyaan berlabel memperoleh konteks relevan; data proyek lain tidak ikut tanpa alasan/izin |
| S6-03 | Preference dengan sumber dan precedence | Preferensi eksplisit terbaru mengalahkan dugaan model; konflik tidak ditimpa diam-diam |
| S6-04 | Review, koreksi, forget, expiry dan tombstone | Hapus/koreksi tercermin di retrieval, cache dan index; restore tidak menghidupkan memory terhapus tanpa proses yang benar |
| S6-05 | Privacy policy lintas local/cloud | Restricted memory tidak keluar ke cloud; context tidak dapat mengubah authority; ekspor owner tetap terisolasi |
| S6-06 | Evaluasi retrieval dan biaya context | Dataset evaluasi tetap, relevance/leakage/latency/token dicatat; baseline history/profile dibandingkan sebelum rollout |

Profile/history dasar sudah ada. Stage ini bukan sekadar menambah database vector kedua. Hindari menyimpan setiap dugaan LLM sebagai fakta. User dapat mengetahui apa yang disimpan dan mengoreksinya. Nilai recall/precision yang ditargetkan perlu disepakati setelah dataset evaluasi dibuat; jangan mengarang skor.

**Gate freeze:** kualitas pada benchmark tetap membaik, isolasi/retensi/forget terbukti, dan jumlah konteks serta biaya tetap bounded.

## Stage 7 — Specialists

Setiap specialist memakai lifecycle yang sama: proposal → authority → journal → dispatch → result → outbox. Registrasi nama agent dan prompt saja tidak memenuhi acceptance.

| ID | Specialist dan scope awal | Batas dan bukti penerimaan |
|---|---|---|
| S7-R | Research: cari, baca, evaluasi sumber, rangkum dengan sitasi | Provider search ditentukan; URL/SSRF, ukuran unduhan dan budget dibatasi; claim dapat ditelusuri ke sumber; prompt injection sumber tidak mengubah izin |
| S7-D | Documents: baca, rangkum, buat/edit file pada workspace terpilih | Dukungan baca Stage 3 dipakai ulang; write berbatas path/type/size, hasil diperiksa dan versioned; overwrite dapat dipulihkan |
| S7-E | Email: list/read, draft, send/reply | Provider dan OAuth minimal; recipient resolve; attachment classification; persetujuan exact recipient/subject/body; timeout send direkonsiliasi |
| S7-C | Coding: checkout/workspace terisolasi, patch, build/test | Tidak menerima secret produksi/Docker socket; command/dependency/network dibatasi; diff dan tes nyata tersedia; push/deploy mengikuti policy |
| S7-A | Data: analisis dataset yang diizinkan, tabel/grafik, laporan | Input provenance/schema, query read-only atau snapshot; tidak mengarang data; output reproduktif; ekspor mengikuti data class |
| S7-O | DevOps: status/log terpilih, rencana perubahan, tindakan allowlist | Lingkungan staging/produksi dipisah; observasi minimum privilege; perubahan berdampak tinggi memerlukan persetujuan dan rollback |

Satu specialist dibangun dan diuji sampai tuntas sebelum berikutnya mendapat akses luas. Email dan DevOps tidak boleh diaktifkan otomatis hanya karena paket terpasang. Credential provider belum tersedia dalam lampiran. Tidak ada pembayaran provider atau pesan keluar dilakukan oleh audit ini.

**Gate per specialist:** happy path, invalid input, cross-owner/project denial, credential isolation, provider outage, cancellation/recovery, duplicate prevention, output yang benar-benar dapat dipakai, dan batas biaya lulus. Selesaikan semua specialist yang disepakati untuk freeze Stage 7.

## Stage 8 — Experience

| ID | Output wajib | Skenario penerimaan |
|---|---|---|
| S8-01 | Planner menghasilkan DAG/task steps terstruktur | Tool/argumen valid; langkah tidak dikenal/berputar/berlebihan ditolak; planner tidak memberi dirinya authority |
| S8-02 | Budget global per task | Batas call, step, waktu, biaya dan context ditegakkan lintas specialist; habis budget berhenti dengan hasil parsial jujur |
| S8-03 | Natural follow-up dengan referensi pasti | 'Pindahkan rapat itu' mengacu ke event yang diverifikasi; jika lebih dari satu kandidat, minta pilihan |
| S8-04 | Durable multi-step orchestration | Restart setelah satu langkah tidak mengulang efek; kegagalan dependency menghentikan langkah berikutnya yang memerlukannya |
| S8-05 | Cost/latency instrumentation dan optimasi | Ukur per model/task; cache tidak membocorkan owner atau memakai jawaban usang untuk tindakan |
| S8-06 | Routing local/cloud berbasis kemampuan dan privacy | Restricted task tidak fallback diam-diam ke cloud; kegagalan model dijelaskan; fallback berbayar tetap mengikuti consent |
| S8-07 | Acceptance perjalanan pengguna lintas specialist | Contoh riset → dokumen → draft email selesai dengan sumber, file valid dan approval send; semua status sesuai journal |

Contoh awal batas planner yang dapat dievaluasi: maksimal 8 langkah dan budget per task yang dikonfigurasi pemilik. Itu rancangan awal, bukan konfigurasi baru yang sudah diaktifkan. Keputusan akhir bergantung latensi/biaya benchmark. Cross-agent orchestration tidak berarti agent boleh berbagi semua memory atau credential.

**Gate freeze:** seluruh perjalanan pengguna yang disepakati lulus; policy/data provenance tidak hilang saat handoff; restart/recovery terbukti; biaya dan respons dapat diukur.

## Kontrak UX lintas-domain

Prinsip tebak → konfirmasi → eksekusi di `docs/UX_CONFIRMATION_CONTRACT.md`
mengikat semua domain dan antarmuka (termasuk voice). Stage 6–8 wajib
memenuhinya; error format generik dan approve massal buta tidak lulus gate.

## Jalur rilis

1. Kandidat Stage 4G ini → full regression dan review.
2. Tutup seluruh S4 → local accepted release.
3. Tutup S5 → private hosted pilot dengan fitur yang sudah diterima.
4. S6 → S7 per specialist → S8 di staging, lalu rollout bertahap.
5. Setiap rilis membawa source hash, perubahan schema, hasil tes, rollback dan batas yang masih terbuka.

Tidak ada pembelian server, deployment, atau aktivasi credential yang terjadi hanya karena checklist dibuat.
