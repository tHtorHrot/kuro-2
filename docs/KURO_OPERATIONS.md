# Fondasi Stage 5 — belum diterima untuk operasi produksi

## Backup lengkap terenkripsi

Legacy `backup_local.py` tetap tersedia tanpa perubahan. `ops_backup.py` mengambil DB custom pg_dump + cold `document-data`, `qdrant-data`, `embedding-models`, konfigurasi nonrahasia/source hash, schema dan image ID/digest yang benar-benar diinspeksi. PostgreSQL data filesystem aktif tidak disalin. Source hash host dan image ID diamati terpisah; belum ada klaim pemetaan image build yang tidak diuji.

Boundary: jeda seluruh writer existing (`api`, `telegram`, `assistant`, `knowledge`, `scheduler`) dan Qdrant; pastikan tidak ada operator/app DB session tersisa. Reader parser dapat tetap hidup. Operator/manual file writes tidak boleh berjalan selama maintenance; consistency tidak menjanjikan snapshot lintas tool di luar KURO. Pause default maksimum 600 detik, tiap operasi dibatasi sisa waktunya. Writer yang sebelumnya hidup selalu di-start kembali lewat overlay lengkap dalam finally, termasuk ketika dump/disk/provider helper gagal. Restart ini memakai container/mount original, bukan recreate/grant baru. Jika pemulihan start gagal, runner gagal dan operator harus start layanan terdaftar.

Gunakan OpenSSL CMS AuthEnvelopedData AES-256-GCM + RSA-OAEP-SHA256. Enkripsi hanya memakai **sertifikat public recovery milik operator**, dipin SHA256; private key tidak masuk arsip. Sertifikat/pin dan kemampuan enkripsi dipreflight sebelum pause. Tes lokal nyata mengenkripsi, mendekripsi, memulihkan bytes, dan menolak ciphertext yang dimodifikasi. GPG-agent terblokir socket di lingkungan asisten; backend CMS telah diuji dengan OpenSSL 3.0.13. Dokumentasi primer: https://docs.openssl.org/3.5/man1/openssl-cms/ .

Key custody belum dipilih. Simpan private key recovery terenkripsi dan passphrase/akses recovery secara terpisah dari host/backup. Backup original `.secrets` dan `.env` lewat jalur privat terpisah; HMAC pepper/DB/provider credentials original diperlukan untuk pemulihan identitas. Tidak ada rotasi/pembuatan kunci atau credential produksi oleh sesi ini. Jangan menempelkan secret ke chat. Plaintext sementara berada dalam direktori privat mode 0700 (NTFS ACL current-user pada Windows), lalu dihapus setelah selesai/gagal; unlink bukan janji secure erase SSD. Gunakan volume privat terenkripsi/tmpfs dengan kapasitas cukup untuk dua salinan arsip sementara. ACL Windows belum dieksekusi di lingkungan Linux asisten.

Contoh PowerShell setelah operator menyediakan certificate recovery:

```powershell
Set-Location 'A:\Kuro2\kuro-main'
$kuroCert = 'D:\PrivateRecovery\kuro-public.pem'
$kuroCertPin = (Get-FileHash -Algorithm SHA256 -LiteralPath $kuroCert).Hash.ToLower()
python '.\scripts\ops_backup.py' --project personal-jarvis --compose compose.yaml --compose compose.telegram.yaml --compose compose.assistant.yaml --compose compose.knowledge.yaml --compose compose.calendar.yaml --compose compose.calendar.write.yaml --compose compose.operations.yaml --recipient-cert $kuroCert --cert-sha256 $kuroCertPin
if ($LASTEXITCODE -ne 0) { throw 'Backup lengkap gagal; periksa apakah writer sudah kembali hidup.' }
```

Verifikasi pin terhadap sertifikat public yang dipercaya lewat jalur privat; menghitung hash file saja tidak membuktikan siapa pemilik kunci. Sertifikat RSA kompatibel dan OpenSSL host diperlukan. Command hanya contoh parameter setelah key custody diputuskan, bukan instruksi membuat key pengguna otomatis. Memerlukan knowledge volumes existing; helper tidak melakukan download ulang model. Output `.tar.cms`, sidecar checksum, report waktu capture; isi manifest berada di dalam arsip terenkripsi. Tidak ada backup/secret produksi dalam patch.

Offsite default **NOT_ACTIVATED**. `--offsite-dir` menerima mount off-host yang diprovisikan operator; copy hanya ciphertext dan checksum hasil copy dicek. Direktori berbeda tidak membuktikan pemisahan geografis. RPO/RTO 24 jam/60 menit adalah target usulan; bukan hasil/SLA. RPO aktual tetap null tanpa riwayat recovery/insiden.

Retensi terarah, preview default:

```powershell
python '.\scripts\ops_retention.py' '.\backups\encrypted' --keep 7
if ($LASTEXITCODE -ne 0) { throw 'Preview retensi gagal.' }
# Setelah daftar konkret ditinjau, --apply hanya menghapus backup CMS milik helper + sidecar-nya.
```

Tidak menghapus dump legacy, folder produksi atau arsip sembarang.

## Jadwal pilot (diputuskan 10 Okt 2026)

Backup terenkripsi mingguan + copy offsite microsd terverifikasi setiap selesai
backup; retensi keep-7; `ops_watch.py --once` harian. Pengukuran pertama:
capture ~64 dtk, restore ~32 dtk, search dingin <0.1 dtk. RPO/RTO
24 jam/60 menit tetap target, bukan SLA, sampai ada riwayat insiden.

## Restore disposable / quarantine

`ops_restore.py` hanya menerima project baru bernama `kuro-restore-*`, schema 0016, checksum ciphertext dan sertifikat public dipin, key recovery privat lokal. Compose standalone `compose.restore.yaml` **tidak** digabung dengan production. Hanya PostgreSQL `_test` internal + helper volume network none; tidak ada scheduler, polling/sending Telegram, LLM, secrets/provider token mounts atau ports publik. Target volume harus kosong; tar traversal, device, symlink keluar dan duplicate member ditolak. Ini bukan clone produksi yang langsung diaktifkan.

```powershell
python '.\scripts\ops_restore.py' '.\backups\encrypted\NAMA_BACKUP.tar.cms' --sha256 HASH_DARI_REPORT_TERPERCAYA --project kuro-restore-drill01 --recipient-cert $kuroCert --cert-sha256 $kuroCertPin --private-key 'D:\PrivateRecovery\kuro-private.pem' --key-passphrase-file 'D:\PrivateRecovery\passphrase.txt' --report '.\backups\restore-drill01.json'
if ($LASTEXITCODE -ne 0) { throw 'Restore drill gagal; jangan aktifkan executor/transport.' }
```

Nama/path/hash di atas harus diganti dengan artefak aktual. Key/passphrase tidak dicetak atau ditaruh bersama arsip. PyYAML host diperlukan untuk validasi konfigurasi. Restore mempertahankan owner/identity/profile/dokumen/chunks/result/task/notification/receipt, mencatat hitungan **sebelum** quarantine, lalu menonaktifkan assistant/grants, membuat dispatching uncertain, mengembalikan claimed ke queued untuk review, dan membuat send ambigu uncertain. Grant revision/pepper tidak diganti. PostgreSQL clone selalu dihentikan pada akhir drill; volume retained untuk review, bukan dihancurkan otomatis.

**Terukur 9–10 Okt 2026:** restore DB/volume Docker nyata hijau (drill02 schema 0013, drill03/04 schema 0014, counts identik pre/post quarantine, executor/transports absent, ~32 dtk); retrieval query dingin hijau (drill04: koleksi `jarvis_knowledge_v1` status green, 6 points 384-dim Cosine, filter owner/document ada, search mandiri 1.0 + tetangga; cache model embedding ada di volume). **Wajib ulang sekali di schema 0016** (drill lama tidak mencakup tabel `projects`/`project_state`): backup terenkripsi baru + drill disposable + catat pending-job-after-restore. **Sisa:** RTO/data-loss window penuh, load model embedding + search bahasa alami di clone. Report runner mengukur durasi aktual jika dijalankan; tidak mengisi hasil yang belum ada. Sebelum aktivasi, lakukan reconciliation GET stable ID untuk solo-create uncertain, pemeriksaan manual invite/delete, verifikasi retrieval dan secret original. Restore DB tidak membatalkan event Google. Perlu persetujuan terpisah sebelum restore ke volume produksi; helper ini tidak mempunyai target production.

## Monitoring lokal dan alarm

`jarvis ops-monitor --owner-id ID` memeriksa DB/RLS/schema, heartbeat worker, umur job **yang sudah due**, stale lease, failed/uncertain, delivery backlog dan knowledge status. Tidak ada OAuth secret di monitor; heartbeat bukan bukti OAuth valid atau provider berhasil.

`ops_watch.py` polling default 30 detik (5–60), alarm stale >120 detik, backup >24 jam, disk <1 GiB dan RAM Linux available <256 MiB. Alarm/resolved dicatat hanya saat transisi; restart memakai state durable, sehingga tidak flood. Threshold ini asumsi operasi, belum SLA. Future job tidak dihitung stale. Resource host bukan kapasitas Docker VM Windows; RAM Windows saat ini tidak diukur helper. Label/log tidak memuat prompt, token, judul atau ID event.

```powershell
python '.\scripts\ops_watch.py' --project personal-jarvis --compose compose.yaml --owner-id OWNER_EXISTING --once
if ($LASTEXITCODE -ne 0) { throw 'Snapshot monitor gagal.' }
```

Hilangkan `--once` untuk loop. Tambahkan overlay existing jika diperlukan. Alarm lokal berada di `operations/alarms.jsonl`; external adapter default disabled. `--alert-command-json` merupakan argv adapter yang dipilih operator, event JSON pada stdin, tanpa shell. Kanal/penerima alert dan penerimaan eksternal belum dipilih/diuji. Tes mock membuktikan worker stale → satu alarm → recovery, bukan penerimaan alert eksternal.

## Rollback, secret lifecycle dan incident response

Rollback aplikasi hanya dengan image ID/digest dan schema compatibility record yang benar; guard menolak image/schema lama yang tidak tercatat kompatibel. Migration downgrade disabled. Setelah 0013, gunakan roll-forward atau tested data restore dengan reconciliation. Backup tidak memberi alasan untuk mengeksekusi ulang write yang mungkin sudah terjadi.

| Insiden/secret | Tindakan operator dan dampak |
|---|---|
| Telegram compromise | Stop polling/sending; revoke bot token melalui kanal resmi; ganti file mount secara privat, recreate Telegram; periksa pairing/config dan receipt uncertain sebelum enable. |
| LLM key compromise | Stop assistant inference; revoke key, ganti file privat/recreate; jangan otomatis mengulangi call dispatching/uncertain atau membebaskan budget ambigu. |
| Calendar OAuth revoke/change | Stop scheduler; revoke credential resmi; simpan kandidat baru terpisah; lakukan binding/grant review saat antrean aman; grant baru menaikkan revision dan tidak mewariskan approval lama. Jangan menambah calendar:send. |
| DB credential | Pause writer; rotate role passwords dan URL file privat dalam maintenance; recreate services; runtime tetap jarvis_app non-superuser/non-BYPASSRLS. |
| HMAC pepper | Ini migrasi identitas, bukan ganti string acak: token/pairing digest existing bergantung padanya. Siapkan revocation/reissue dan recovery privat; jangan melakukan demonstrasi rotasi. |
| DB down/disk full | Tahan executor/transport, pulihkan resource/readiness, baca journal/lease/outbox; retry hanya pre-dispatch yang aman, reconcile post-dispatch uncertain. |

Hosting target/offsite/key custody/penerima alert belum ditetapkan. Tidak ada pembelian VPS, biaya API baru, pembukaan port publik atau deploy. Jalur Linux Compose privat tetap arsitektur existing. Profil chat+OCR+embedding+scheduler bersamaan dan failure-load disk penuh/DB down/provider timeout belum diukur; jangan menyarankan kapasitas/harga server dari angka anggaran lama.
