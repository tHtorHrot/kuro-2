# Bukti finish 2–5: Stage 5 backup + drill 0016 (10 Okt 2026)

Tanpa credential, tanpa isi data. Hash + hitungan saja.

## 5a backup terenkripsi — HIJAU (lokal)

* File: `kuro-complete-20261010T155034493994Z.tar.cms`,
  sha256 `9b9c6f34e4732863db37c096d0087fe8b6d7d109130d6bee200d999bbaa5ed14`.
* `schema: 0016_memory_projects`, `capture_seconds: 51.48`,
  `encrypted: true`, `offsite: not_activated` (otomatis; exFAT menolak
  folder-privat skrip — lihat bawah).
* Insiden proses: run pertama dengan `--offsite-dir` gagal generik dan
  pemulihan start writer ikut gagal (9 writer mati). Dipulihkan manual:
  9 container Up + doctor `ready`. Tidak ada data diubah selain itu.

## 5a drill restore disposable — HIJAU

* Project `kuro-restore-drill05`, report `backups/restore-drill05.json`.
* `status: restored_quarantined`, `restore_seconds: 37.849`,
  `schema: 0016_memory_projects` (pertama di 0016; drill lama 0013/0014
  tidak mencakup tabel `projects`).
* Counts identik pre/post quarantine: owners 1, identities 1,
  profile_memory 5, **projects 0**, documents 3, chunks 7, drafts 14,
  results 15, notifications 14, receipts 108,
  actions {cancelled 14, succeeded 16}.
* Pending-job-after-restore: tidak ada `dispatching`/`claimed`/`sending`
  (quarantine no-op, benar). `executor`/`external_transports` absent.
* `retrieval_drill: not_run` (sisa, lihat bawah).
* `reconciliation: required` — restore tidak membatalkan event Google.

## Offsite — PENDING media pengganti (keputusan 11 Okt)

* Copy ke microsd exFAT gagal verifikasi 2x (A927… lalu 769C… ≠ 9B9C…,
  panjang sama = korupsi diam-diam). Kartu DINYATAKAN TIDAK DIPERCAYA
  untuk arsip; tidak diformat/diutak-atik (ada file penting pemilik).
* Beraku: arsip lokal terverifikasi sah penuh; salin ke media eksternal
  DITUNDA sampai media pengganti siap, lalu wajib hash-cocok sebelum
  diakui offsite. COPY saja, jangan MOVE (asli lokal dipertahankan,
  retensi keep-7 yang mengatur).

## Sisa Stage 5

* Retrieval dingin di clone (Qdrant + model + search bahasa alami).
* RPO 24 jam / RTO 60 mnt tetap TARGET (1 titik ukur, tanpa riwayat
  insiden), bukan SLA.
* Keputusan 5c menunggu konfirmasi pemilik (lihat FINISH_2_5.md).
