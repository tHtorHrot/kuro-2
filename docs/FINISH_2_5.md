# Finish rapi Tahap 2–5 — checklist exit (10 Okt 2026)

Sumber kriteria: `STAGE_4_8_ACCEPTANCE.md` (S4-01–12, S5-01–07),
`KURO_DELTA_ACCEPTANCE.md`, `KURO_OPERATIONS.md`, `STAGE_3_VERIFICATION.md`.
Bukti kode: native gate schema `0016_memory_projects`, 660 passed / XML 749
(`docs/evidence/native-candidate/run/verification.json`).

## Stage 2 — TUTUP (10 Okt)

* 2A transport + pairing: user-konfirmasi aman. Native hijau.
* 2B AI: native hijau + live `/ask` dijawab via rute gratis + ledger
  actual-vs-held + katalog bertimestamp. Sisa hanya perawatan katalog.
* Keputusan: premium tetap opsional USD0; teks biasa = antre AI (kode
  `INFERENCE_COMMANDS`); lampiran/voice tetap di luar scope.

## Stage 3 — TUTUP 10 Okt (bukti `evidence/finish-2-5/stage3-doc-drill.md`)

* [x] 3a. `knowledge-status` + worker recent hijau di produksi.
* [x] 3b. Drill dokumen live hijau: PDF private 163 chunks `/askdoc`
  bersitasi (1 transien `citation_invalid` lalu retry hijau), DOCX 2x hijau,
  restricted DITOLAK tanpa panggilan AI, dedup lintas-class
  (`duplicate_policy_mismatch`) benar, `/deldoc` + restart konsisten.
* Defer (bukan blocker pilot, dicatat): konversi `.doc` lama, gambar Word
  tertanam/header/footer/track-changes, UI cari restricted lokal, lampiran
  bot, pemilih model di Telegram, voice.

## Stage 4 — TUTUP 10 Okt (bukti `evidence/finish-2-5/stage4-delta.md`)

* [x] 4a. Native S4-01–12 hijau (660, mock) + delta live USER_REPORTED:
  6 skenario 5 Okt + delta hijau 10 Okt + konfirmasi pemilik (pagi/siang/
  sore dikenali, rancu → konfirmasi). Grammar TOD + HELP + konfirmasi
  terverifikasi di source + tes.
* [x] 4b. Keputusan: `calendar:send` tetap NONAKTIF.
* Defer: follow-up bebas tanpa label field, scheduled invite/delete,
  planner lintas specialist (milik Stage 8).

## Stage 5 — hampir tutup (bukti `evidence/finish-2-5/stage5-drill05.md`)

* [x] 5a. Backup terenkripsi BARU schema 0016 hijau (51 dtk) + restore
  drill05 disposable hijau (38 dtk, counts identik, tanpa pending
  dispatching/claimed). Drill lama 0013/0014 tertutup oleh ini.
* [ ] 5a-offsite. PENDING media pengganti (11 Okt): 2x copy microsd
  gagal hash (panjang sama = korupsi diam-diam); kartu tidak dipercaya,
  tidak diformat. Berlaku: arsip lokal sah; copy ke eksternal ditunda
  sampai media baru, wajib hash-cocok, COPY bukan MOVE.
* [x] 5b. `ops_watch --once` hijau kecuali `backup_missing_or_old`
  (tertutup backup 0016 10 Okt). Baseline terukur: capture 51 dtk /
  restore 38 dtk. RPO 24 jam / RTO 60 mnt tetap TARGET, bukan SLA.
* [x] 5c. Keputusan operator (11 Okt, dari tindakan, bukan angan):
  hosting = pilot lokal (VPS ditunda) / alert = file lokal
  (`external_adapter: disabled` terbukti di 5b) / key custody = operator
  (tanpa demo rotasi) / `calendar:send` tetap nonaktif /
  Stage 6–8 hanya via staging + gate.
* Defer: load penuh chat+OCR+scheduler bersamaan, failure-load disk
  penuh/DB down di produksi (hanya drill disposable).

## Penutup 11 Okt — Tahap 2–5 SELESAI kecuali 1 item media

2 TUTUP penuh (native + live). 3 TUTUP (drill dokumen live). 4 TUTUP
(native + delta USER_REPORTED, send mati). 5 TUTUP kecuali
**5a-offsite PENDING media pengganti** + retrieval dingin di clone
(`not_run`) + RPO/RTO = target. Bukti per tahap di
`docs/evidence/finish-2-5/`.

## Runbook (tanpa nilai secret di output)

```powershell
# 3a (knowledge-ops butuh secret assistant_config dari overlay assistant)
docker compose -p personal-jarvis -f compose.yaml -f compose.assistant.yaml -f compose.knowledge.yaml --profile knowledge-ops run --rm --no-deps knowledge-ops knowledge-status
# 3b (file uji lokal HARUS ada; ganti dengan PDF/DOCX/PNG/JPG nonsensitif milikmu, 1 byte-20 MiB)
python .\scripts\documents.py add "<PATH-KE-FILE-UJI>"
# lalu di Telegram: /docs, /askdoc UUID pertanyaan, /deldoc UUID
# 4a: ikuti KURO_DELTA_ACCEPTANCE.md 1-5 di kalender uji
# 5a: contoh ada di KURO_OPERATIONS.md (ganti path/hash/sertifikat aktual)
# 5b
python .\scripts\ops_watch.py --project personal-jarvis --compose compose.yaml --owner-id <UUID-OWNER> --once
```

Setiap langkah: catat exit code + 3 baris bukti (tanpa credential) ke
`docs/evidence/finish-2-5/`. Klaim "selesai" hanya dari bukti itu, bukan
dari ingatan chat.
