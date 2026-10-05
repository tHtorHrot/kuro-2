# Pembaruan 2B → Tahap 3 di Windows

Paket **0.4.0** menambahkan dokumen PDF/DOCX, OCR PNG/JPG/PDF scan, dan pertanyaan dengan sumber.
Ini paket development untuk diuji. Tahap 2B Anda sudah diterima; penerimaan Tahap 3 memerlukan gate Docker dan tes Telegram di bawah.

**Hotfix OCR-1 (1 Oktober 2026):** Dockerfile kini memasang mesin `tesseract-ocr`
secara eksplisit, selain paket bahasa, serta memeriksa executable dan bahasa saat build.
Jika paket awal menghasilkan satu kegagalan `test_real_image_ocr_and_scanned_pdf`,
terapkan ZIP hotfix dan build ulang tes sesuai `HOTFIX_OCR_1.md`.

## 1. Cadangkan, kemudian ekstrak ZIP

Di folder **A:\jarvis-stage-1**, sebelum menimpa kode:

```powershell
Set-Location A:\jarvis-stage-1
python scripts/backup_local.py
if ($LASTEXITCODE -ne 0) { throw "Backup gagal; hentikan pembaruan." }
```

Pastikan keluaran menunjukkan path file `.dump` di `backups`. Simpan salinan kode 2B dan `.secrets` secara privat di luar folder proyek. Dump ini tidak terenkripsi dan tidak mencakup file dokumen; pada instalasi 2B belum ada volume dokumen.

Jika sudah menimpa kode tetapi baru menjalankan `compose.test.yaml`, buat backup sekarang
sebelum migrasi. Ekstraksi file tidak otomatis mengubah database atau mengganti image
container yang sedang berjalan. Test memakai database sementara terpisah. Backup baru
mencadangkan database saat ini, bukan memulihkan salinan kode 2B yang sudah tertimpa.

Ekstrak **isi ZIP langsung ke `A:\jarvis-stage-1`**, lalu pilih ganti file yang sudah ada. `compose.yaml` dan `pyproject.toml` harus langsung berada di folder tersebut, bukan di subfolder baru. Paket tidak berisi `.env`, `.secrets`, isi database, atau backup Anda. File konfigurasi dan data yang ada tetap dipakai. Ekstraksi saja belum memperbarui container: lanjutkan build dan migrasi.

## 2. Gate pengujian sebelum migrasi database Anda

```powershell
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
$testExitCode = $LASTEXITCODE
Write-Output "TEST_EXIT_CODE=$testExitCode"
if ($testExitCode -ne 0) { throw "Tes gagal; jangan lanjut ke migrasi." }
docker compose -f compose.test.yaml down
```

Gate memakai proyek terpisah `personal-jarvis-tests`, PostgreSQL sementara, Qdrant sementara, dan kredensial test. Tidak memasang secret/volume produksi. Gate juga mencoba migrasi dari 2B yang sudah berisi contoh owner, pairing dan memory, lalu memeriksa bahwa data tersebut tetap ada. Tes OCR wajib berjalan di image test.

Pesan **“Aborting on container exit”** setelah tes selesai adalah perilaku normal opsi Compose tersebut. Syarat lulus: tidak ada tes gagal, container tests keluar 0, dan `TEST_EXIT_CODE=0`. Jangan menilai hanya dari baris terakhir log PostgreSQL.

Jika gagal, **simpan log sebelum `down`**. Perintah `down` menghapus container beserta
log yang dibaca oleh `docker compose logs`. Jangan menjalankan langkah berikutnya
hanya karena PowerShell kembali menampilkan prompt setelah `throw`.

```powershell
docker compose -f compose.test.yaml logs --no-color tests 2>&1 | Tee-Object -FilePath .\stage3-tests.log
```

## 3. Siapkan perintah Compose lengkap

Jalankan dalam sesi PowerShell yang sama:

```powershell
$k = @(
  "-f", "compose.yaml",
  "-f", "compose.telegram.yaml",
  "-f", "compose.assistant.yaml",
  "-f", "compose.knowledge.yaml",
  "--profile", "telegram",
  "--profile", "assistant",
  "--profile", "knowledge"
)
function Invoke-KuroCompose {
  & docker compose @k @args
  if ($LASTEXITCODE -ne 0) { throw "Docker Compose gagal: $LASTEXITCODE" }
}
Invoke-KuroCompose config --quiet
Invoke-KuroCompose build api assistant telegram knowledge document-parser
```

Build/model pertama memerlukan internet dan ruang disk beberapa GB. OCR serta embedding menambah pemakaian RAM/CPU; mulai pengujian Docker Desktop dengan sekitar **6 GB RAM tersedia untuk Docker** bila perangkat memungkinkan. Ini alokasi awal untuk pengujian, bukan hasil benchmark atau perubahan target biaya VPS. Pantau `docker stats`; jangan menganggap konfigurasi OCR ini sudah terbukti muat di VPS kecil sebelumnya.

## 4. Migrasi dan hidupkan layanan lokal

```powershell
Invoke-KuroCompose stop assistant telegram api
Invoke-KuroCompose run --rm --no-deps migrate
Invoke-KuroCompose --profile ops run --rm --no-deps ops doctor
Invoke-KuroCompose --profile knowledge-setup run --rm --no-deps knowledge-init
Invoke-KuroCompose --profile knowledge-setup run --rm --no-deps knowledge-model-download
```

`doctor` harus menyebut `stage: "3"`, database ready dan RLS enabled/forced. Pengunduh model hanya mengunduh embedding lokal; tidak menggunakan OpenRouter atau mengirim dokumen. Model dan checksum dipatok. Unduhan pertama sekitar 252 MB file model/tokenizer; siapkan ruang cache lebih besar. Tunggu `download_complete: true`, `dimensions: 384`, `inference_sent: false`.

```powershell
Invoke-KuroCompose up -d postgres api document-parser qdrant knowledge assistant telegram
Invoke-KuroCompose ps
python scripts/documents.py check
if ($LASTEXITCODE -ne 0) { throw "Pemeriksaan lokal gagal; lihat log knowledge/parser/qdrant." }
python scripts/documents.py status
Invoke-KuroCompose exec -T assistant jarvis assistant-status
```

Tunggu status `worker_recent: true` pada knowledge dan assistant. `/ask` baru bisa digunakan setelah assistant siap. `enabled`, `frozen`, `config_matches`, pairing dan rute AI memakai konfigurasi 2B Anda. Tidak perlu membuat owner, pairing, atau API key baru. Tidak perlu menjalankan ulang `setup_local.py` / `setup_assistant.py`. Model Ling/Novita yang sudah bekerja tetap berasal dari `.secrets/assistant_config.json` Anda.

Jika sebelumnya AI sengaja dinonaktifkan, pengaktifan tetap eksplisit:

```powershell
Invoke-KuroCompose exec -T assistant jarvis assistant-enable
```

## 5. Uji dokumen contoh, kemudian dokumen Anda

```powershell
python scripts/documents.py add ".\tests\fixtures\knowledge-demo.docx"
python scripts/documents.py list
```

Salin `id` UUID dari JSON. Periksa sampai `status: "ready"`:

```powershell
python scripts/documents.py info "UUID_DARI_HASIL_IMPORT"
```

Di Telegram:

```text
/docs
/doc UUID_DARI_HASIL_IMPORT
/askdoc UUID_DARI_HASIL_IMPORT Apa kode proyek dan kapan rapatnya?
```

Jawaban harus menyebut kode **RAMBUTAN731**, jadwal **17 Oktober 2026 pukul 09.00 WIB**, label seperti `[S1]`, dan daftar sumber nama file serta paragraf. Jawaban AI tetap dapat salah; periksa sumbernya. Jika kutipan yang ditemukan tidak mencakup jadwal, tanyakan jadwal secara khusus.

Uji OCR:

```powershell
python scripts/documents.py add ".\tests\fixtures\knowledge-scan.png"
```

Tunggu ready dan tanyakan kode pada gambar dengan `/askdoc ID_GAMBAR Apa kode dokumen?`. Kemudian uji PDF/Word milik Anda:

```powershell
python scripts/documents.py add "A:\Dokumen\laporan.pdf" --ocr auto
python scripts/documents.py add "A:\Dokumen\catatan.docx"
```

`private` adalah pernyataan Anda bahwa kutipan boleh diproses AI cloud saat `/askdoc`. Untuk dokumen yang **tidak boleh dikirim ke cloud**, impor sebagai restricted:

```powershell
python scripts/documents.py add "A:\Dokumen\dokumen-lokal.pdf" --data-class restricted
```

`/askdoc` terhadap dokumen restricted ditolak tanpa panggilan AI. Tahap ini menyediakan penyimpanan/index lokal untuk restricted, belum menyediakan antarmuka pencarian teks lokal untuk pemilik. Jangan mengunggah data sensitif ke Telegram.

## Perintah dan batas

| Kebutuhan | Perintah |
|---|---|
| Daftar/status dokumen di bot | `/docs`, `/doc UUID` |
| Pertanyaan satu dokumen | `/askdoc UUID pertanyaan` |
| Hapus dokumen | `/deldoc UUID` atau `python scripts/documents.py delete UUID` |
| Daftar lengkap di komputer | `python scripts/documents.py list` |
| Ulangi ingestion yang gagal | `python scripts/documents.py retry UUID` |
| Status worker | `python scripts/documents.py status` |
| Cek model, parser, Qdrant, schema | `python scripts/documents.py check` |

Maksimal 20 MiB/file, 200 halaman PDF, 50 halaman OCR, 500.000 karakter, 1.500 chunk, 200 dokumen aktif dan 2 GiB sumber per owner. Parser memiliki batas waktu 180 detik; dokumen yang kompleks bisa gagal sebelum batas halaman. Maksimal tiga percobaan ingestion; kegagalan tidak memanggil AI atau berulang tanpa batas.

PDF teks memakai teks aslinya; `--ocr auto` menambahkan OCR halaman tanpa teks atau bergambar. PDF teks dengan logo di banyak halaman dapat mencapai batas OCR; gunakan `--ocr never` jika text layer sudah baik. `--ocr always` untuk text layer yang buruk. OCR lokal memakai bahasa Indonesia + Inggris; tulisan tangan, tabel rumit, foto miring dan scan buram perlu diperiksa. Gambar tertanam dalam DOCX, header/footer, komentar dan track changes belum diekstrak; konversi ke PDF bila isi penting berada di bagian tersebut. Format `.doc` lama perlu dikonversi ke `.docx`.

Hasil chunk hanya empat kutipan dari satu dokumen. Ini belum pencarian gabungan banyak dokumen, ringkasan utuh buku, browser web, atau pemilih model di Telegram. Pilihan model AI tetap lewat pengaturan rute 2B dan pemeriksaan katalog; endpoint gratis yang sedang padat masih bisa menghasilkan 429. Tidak ada fallback premium otomatis.

Upload hanya dari komputer. Lampiran bot belum diproses. Ekstraksi/OCR/embedding tidak memakai cloud; `/askdoc` mengirim pertanyaan dan kutipan terpilih melalui aturan privasi/biaya assistant yang sudah ada. Jawaban dokumen tidak dicampurkan ke history umum `/ask`. Pemeriksaan label sumber tidak membuktikan setiap klaim AI benar.

## Uji penghapusan, restart, dan privasi

1. Impor ulang file identik: harus `duplicate: true` dengan ID sama. Perubahan class/OCR pada file identik ditolak; hapus sampai `deleted` lalu impor kembali dengan kebijakan yang benar.
2. `/deldoc UUID` langsung menutup akses dokumen dan membatalkan permintaan terkait. Cek `documents.py info UUID` sampai `deleted`. File/chunk/vector dibersihkan oleh worker; jika Qdrant mati, status tetap `deleting` dan cleanup mencoba kembali.
3. Coba `/askdoc` ID yang sudah dihapus: harus ditolak. Percakapan/dokumen lain tetap bisa dipakai.
4. Coba `/askdoc` restricted: harus ditolak; jumlah panggilan LLM tidak bertambah.
5. Coba akun Telegram lain: tidak dilayani. Uji ulang `/ask`, `/remember`, `/forget` dan `/clear`.
6. `Invoke-KuroCompose restart knowledge assistant telegram`, lalu cek status dan dokumen ready yang masih ada. Data disimpan dalam volume.

Panggilan cloud atau pengiriman Telegram yang sudah dimulai tidak dapat ditarik kembali. Penghapusan mencegah penggunaan berikutnya dan membersihkan salinan lokal terkait; salinan yang sudah terkirim, data provider sesuai retensi mereka, dan backup lama tidak ikut terhapus. Ledger biaya dipertahankan. `/clear` membersihkan konteks/jawaban, **bukan menghapus file dokumen**.

## Jika ada kendala

```powershell
Invoke-KuroCompose logs --since 10m --tail 80 knowledge document-parser qdrant
Invoke-KuroCompose logs --since 10m --tail 40 assistant
```

| Kode/gejala | Tindakan |
|---|---|
| `embedding_model_unavailable_run_model_download` | Jalankan init dan model-download, lalu restart knowledge. |
| `embedding_model_checksum_mismatch` | Cache tidak cocok dengan model paket. Hentikan knowledge dan laporkan; jangan mengubah checksum agar lolos. |
| `local_service_unavailable` | Periksa parser/Qdrant dan jaringan Compose; jangan buka port publik. |
| `ocr_page_limit`, `parser_timeout` | Pecah PDF; pilih `--ocr never` hanya jika text layer sudah benar. |
| `unsafe_docx`, `docx_expansion_limit` | Ekspor ulang DOCX atau PDF yang lebih kecil. |
| `document_context_blocked` | Kutipan menyerupai kredensial; gunakan dokumen yang sudah disanitasi. |
| `document_sources_unavailable` | Tidak ada hasil relevan/indeks tidak cocok; coba pertanyaan lebih spesifik dan cek status. |
| `citation_invalid` | Jawaban AI tidak menyertakan label yang sah. Coba pertanyaan baru; tidak ada pengulangan otomatis. |
| `failed` / `retry_limit` | Perbaiki penyebab, retry jika masih di bawah tiga attempts; setelah batas, hapus lalu impor ulang. |
| `openrouter_http_429` | Endpoint AI sedang menolak; periksa katalog/rute seperti 2B. Kuota harian tersedia tidak menjamin kapasitas provider. |

## Backup dan pemulihan

**Jangan jalankan `docker compose down -v` pada proyek `personal-jarvis`.** Itu menghapus volume data. Perintah `down` proyek test di atas berbeda dan terisolasi.

Untuk pembaruan pertama dari 2B, dump sebelum migrasi dan salinan kode/secret adalah titik pemulihan. Migrasi ini tidak menyediakan downgrade destruktif. Jika perlu kembali setelah migrasi, hentikan layanan baru, gunakan kode 2B dan pulihkan dump ke cluster/volume pemulihan yang baru; jangan menimpa volume yang masih berisi data tanpa memeriksa backup.

Setelah dokumen dipakai, backup lengkap juga harus mencakup **`document-data`**, **`qdrant-data`**, dan database dari titik waktu yang konsisten. Hentikan knowledge/assistant/telegram serta aktivitas impor sebelum mencadangkan ketiganya. Cache `embedding-models` dapat dicadangkan atau diunduh ulang dengan versi/checksum yang sama. `backup_local.py` tetap hanya membuat dump PostgreSQL: jangan menganggapnya sebagai backup lengkap dokumen Tahap 3. Simpan file sumber asli sampai prosedur backup/restore volume Anda diuji.
