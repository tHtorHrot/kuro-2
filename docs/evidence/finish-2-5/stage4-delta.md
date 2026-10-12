# Bukti finish 2–5: Stage 4 delta kalender (10 Okt 2026)

Tanpa credential. Kode + tes + laporan pengguna.

## Kode (terverifikasi di source)

* Kata waktu Indonesia di grammar deterministik
  (`src/jarvis/core/calendar_slots.py:29`):
  `pagi|siang|sore|malam|dini hari|subuh|tengah malam`, hanya di luar
  judul berquote (`_strip_tod`). Konversi 12-jam → 24-jam
  (`_apply_tod`): jam 3 sore → 15:00, jam 8 malam → 20:00,
  jam 2 siang → 14:00, jam 12 malam → 00:00, jam 15 eksplisit menang.
* Perintah rancu → klarifikasi, bukan karangan: slot kurang → status
  `clarified` + teks HELP (`calendar_chat.py:30`); salvage simpan field
  valid + lapor sisa (`test_salvage_keeps_validated_fields`).
* Konfirmasi: `ya/setuju/batal`, `setujui nomor N`, `batalin semua`,
  compound all-or-nothing; kalimat biasa (`ya, nanti aku kabari`)
  lewat ke chat, bukan approve buta (`test_calendar_confirm.py`).

## Tes native (dalam gate 660 hijau, schema 0016)

* `test_calendar_slots.py`: 6 kasus TOD berparameter + proteksi quote
  (`Rapat sore tim` tetap judul) + missing-slot + salvage.
* `test_calendar_confirm.py`: bare/nomor/bulk/compound + pass-through.
* Integration `test_calendar_chat.py` / `test_calendar_tasks.py`:
  draft durable, due vs event, approve exact, cancel, restart.

## Live — USER_REPORTED (tidak dieksekusi ulang asisten)

* `docs/evidence/stage-4h/user-acceptance.json` (5 Okt): read/agenda,
  OAuth write, create, restart pre-dispatch, cancel deletion, approved
  delete. Bukan bukti source baru; tanpa action ID/timestamp tebakkan.
* `DEVELOPMENT_STATUS.md` (10 Okt): delta live hijau + UX Fase A–C
  (tombol inline, kata waktu, salvage, kontrak konfirmasi).
* Laporan pemilik 10 Okt: pagi/siang/sore dikenali; perintah rancu
  dijawab konfirmasi. Konsisten dengan grammar + HELP di atas.
* Batas: tidak ada efek samping diuji asisten; undangan pihak luar
  (`calendar:send`) tetap NONAKTIF.

## Keputusan 4b

`calendar:send` tetap nonaktif. Undangan (`undang @`) butuh approval
exact terpisah dan bukan bagian uji ini.
