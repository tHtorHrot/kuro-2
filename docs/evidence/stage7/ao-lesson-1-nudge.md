# Bukti pelajaran AO #1: no_signal + nudge sekali (11 Okt 2026)

Diadaptasi dari agent-orchestrator (derived display status, grace
no_signal, nudge dedup); disesuaikan ke arsitektur Kuro (tanpa
mengubah ambang/tes existing).

## Kode (tanpa kredensial, tanpa migrasi)

* `operations/monitor.py`: `derive_signal(expected, age)` murni →
  `ok | no_signal | idle` (grace 90 dtk) + daftar `no_signal` di
  snapshot. Kunci `expected/age_seconds/recent` tak berubah (kompatibel
  `ops_watch` + alarm existing).
* `orchestration/calendar_tasks.py`: `remind_approvals()` — satu
  pengingat per usulan task ≤3 menit sebelum kedaluwarsa, kunci
  `nudge:{id}:{fp12}` idempoten; hanya awaiting_approval valid (tidak
  pernah frozen/uncertain/cancelled); solo-create tanpa task tidak
  diingatkan (batas tercatat).
* `orchestration/calendar_chat.py`: `deliver_completed` memanggil
  reminder (jalur heartbeat existing, tanpa worker/loop baru).
* `interfaces/telegram/notifications.py`: gerbang claim memblokir
  pengingat basi (status sudah bukan awaiting_approval).
* Pelajaran proses: `rowcount` INSERT+DO NOTHING tidak menentu lintas
  driver → hitung via cek-eksistensi + constraint sebagai penjaga race.

## Tes

* Unit `derive_signal`: ok/batas-90/no_signal/None/idle.
* Native `test_calendar_nudge.py`: ingatkan-sekali + dedup panggilan
  kedua + basi-diblokir-pasca-approve + jauh-jadwal-tidak-diingatkan.

## Live produksi 11 Okt (USER_REPORTED, tidak dieksekusi asisten)

* 21:52 WIB: draft "uji kuro stage 7" → proposal approval + tombol.
* 21:59 WIB: tepat 1 pesan "Pengingat 1x: usulan eeccefb7 menunggu
  persetujuan, kedaluwarsa 2026-10-11T15:02:39…" (±3 mnt sebelum expiry).
* Pemilik setujui DARI pesan pengingat (`/toolapprove` di nudge).
* 22:00 WIB: completion "Kalender: uji kuro stage 7 tersimpan…
  ID: kuro…" tiba; tidak ada pengingat kedua/susulan.
* Terbukti hidup: kirim-sekali, approve-dari-nudge sah, basi tidak
  terkirim ulang.
