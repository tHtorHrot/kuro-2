# Bukti finish 2–5: Stage 3 drill dokumen live (10 Okt 2026, ~22:15–22:22 WIB)

Tanpa credential, tanpa isi file. UUID + status + kode saja.

## 3a. Kesehatan knowledge — HIJAU

`knowledge-status`: `worker_recent:true`, `documents:{ready:2}`,
`pipeline:knowledge-1-minilm384`, `inference_sent:false`.
`documents status`: sama, worker recent.

## 3b. Drill dokumen live — HIJAU

* Upload PDF private (`Markdown to PDF.pdf`, 326965 byte): `queued` → `ready`,
  163 chunks, attempts 1, OCR auto, pipeline `knowledge-1-minilm384`.
* Upload PNG restricted (file lain, 715617 byte): `queued` → `ready`, 1 chunk.
  Upload ulang berkas SAMA sebagai restricted ditolak benar:
  `duplicate_policy_mismatch` (dedup lintas-class bekerja).
* `/docs`: tampil 2–3 dokumen sesuai fase, restricted tampil `[restricted]`
  tanpa judul.
* `/askdoc <docx-full-UUID>`: dijawab bersitasi `[S1]–[S4]` + `Sumber:`
  paragraf. HIJAU (2x).
* `/askdoc <pdf-full-UUID>` percobaan 1: diblokir `citation_invalid`
  (transien model 1 panggilan). Retry: dijawab bersitasi `[S1]–[S4]` +
  `Sumber:` halaman 3/16/1. HIJAU.
* `/askdoc <restricted-UUID>`: DITOLAK — "Dokumen restricted tidak dikirim
  ke AI cloud. Tidak ada panggilan AI." HIJAU.
* `/deldoc <pdf-UUID>`: deleting antre; `/docs` sesudahnya tanpa PDF.
  Restart `knowledge` + `list`: docx + restricted tetap `ready`. HIJAU.
* Catatan UX: `/askdoc` wajib UUID penuh; 8-char prefix ditolak dengan
  pesan pemakaian (bukan crash). Defer: terima prefix sebagaiarbe nice-to-have.

## Sisa Stage 3

Defer eksplisit (bukan blocker pilot): konversi `.doc`, gambar Word
tertanam/header/footer/track-changes, UI cari restricted lokal, lampiran
bot, pemilih model di Telegram, voice.
