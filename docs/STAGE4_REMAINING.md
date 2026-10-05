# Audit sisa Stage 4 — setelah agenda diterima pengguna

Laporan terbaru 4 Oktober 2026 21:01 WIB: build runtime berhasil; assistant healthy,
enabled, config_matches dan worker_recent true; pengguna menyatakan balasan bot sudah
sesuai format agenda. Bukti ini laporan pengguna, bukan akses asisten ke host Windows.

## Sudah selesai

- Full regression baseline: 444 passed, exit 0, dilaporkan pengguna.
- Upgrade database/head 0008, RLS forced, volume lama, backup lokal sebelum upgrade.
- Assistant/Telegram/knowledge berjalan; Calendar OAuth baca, grant dan scheduler aktif.
- Read Calendar nyata cocok dengan kalender pengguna, termasuk tampilan agenda terbaru.
- Bug tmpfs scalar sudah diperbaiki pengguna dan disamakan pada source.

Pekerjaan di atas tidak perlu diulang untuk mengaktifkan kandidat tulis. Label `stage: 3`
pada assistant-status adalah label historis, bukan hasil pemeriksaan schema.

## Peta gate

| Gate | Bukti yang tersedia | Sisa sebelum freeze |
|---|---|---|
| S4-01 Natural chat | Queue/privacy/premium shared; tes baseline | Satu laporan balasan LLM biasa masih belum diberikan |
| S4-02 Trusted routing | Grounding ketat, negasi/source/scope, tes unit/integrasi | Regresi konsolidasi release terakhir |
| S4-03 Calendar read | Read dan UI live diterima pengguna | Dipertahankan pada release final |
| S4-04 Create/clarification | Create lengkap dan template klarifikasi tersedia, tes integrasi | Create live; klarifikasi bertahap durable belum ada |
| S4-05 Current authority | Revoke/suspend/grant revision/binding diuji | Regresi konsolidasi |
| S4-06 Approval | TTL/fingerprint/once/replay, integrasi mock invite | Delete dengan approval live; send tetap nonaktif |
| S4-07 Cancel | Queued/claimed dan pembatasan in-flight diuji | Cancel proposal delete live |
| S4-08 Recovery | Pre-dispatch retry, uncertain, stable-ID GET reconciliation diuji | Restart dengan antrean live; tidak mengklaim live post-dispatch fault |
| S4-09 Result/outbox | Result durable/dedup/outbox; read live | Create ID tersimpan dan hasil dikirim sekali pada smoke |
| S4-10 Scheduler | Due time, lease, fence, timezone dan shutdown diuji | Restart live; chat untuk waktu eksekusi tertunda masih terbatas |
| S4-11 Boundaries | Typed args, scopes, pagination/HTTP limits diuji | Regresi konsolidasi |
| S4-12 Release acceptance | Baseline 444; helper/UI focused checks dan read live | Satu full regression source final + smoke tulis + manifest release |

Tests terkait: `tests/integration/test_tool_actions.py`,
`tests/integration/test_calendar_chat.py`, `tests/unit/test_calendar_boundaries.py`,
`tests/unit/test_calendar_recovery.py`, dan gate dasar lainnya. Keberadaan tes bukan
klaim bahwa tes baru telah dijalankan pada Docker pengguna; catatan run dibedakan.

## Urutan paling dekat

1. Siapkan kandidat write melalui `scripts/setup_calendar.py --access write`; credential
   lama tidak ditimpa. Helper ini lulus 43 tes lokal. Aktivasi/tes nyata masih menunggu
   login dan tindakan pengguna sesuai `STAGE4_WRITE_ACCEPTANCE.md`.
2. Gabungkan uji antrean-restart, create solo, cancel dan delete approval dalam satu
   acara uji. Kendalikan efek dengan judul eksplisit dan tanpa penerima undangan.
3. Selesaikan/terima batas klarifikasi dan penjadwalan chat, lalu lakukan satu regresi
   konsolidasi. Jangan menyatakan Stage 4 frozen hanya karena create sekali berhasil.
4. Lanjutkan operasi Stage 5: release/deploy privat, monitoring, backup lengkap terenkripsi,
   restore dan rollback nyata, kemudian lifecycle secret serta disaster recovery.

Stage 4 tetap OPEN. Pilot read-only sudah berjalan. Stage 5–8 belum selesai; belum ada
server publik yang dideploy. Persiapan operasi dapat dikerjakan tanpa membuka fitur
yang belum diterima, tetapi freeze tetap mengikuti gate yang sudah ditetapkan.
