# Roadmap KURO — Stage 4 sampai 8

Roadmap ini mengikuti arahan pengguna tanggal 2 Oktober 2026. Status source dan hasil pemeriksaan terbaru ada di `../DEVELOPMENT_STATUS.md`; acceptance lengkap di `STAGE_4_8_ACCEPTANCE.md`.

| Stage | Urutan | Hasil yang menutup tahap |
|---|---|---|
| 4 — Close the loop | Natural chat → trusted routing → Calendar E2E → scheduler → approval → recovery → production acceptance | Satu perjalanan pengguna sampai hasil provider dan notifikasi, dengan authority/recovery terbukti |
| 5 — Operations | Deployment → monitoring → backup → restore → rollback → secret lifecycle → disaster recovery | Layanan privat dapat dioperasikan dan dipulihkan dari bukti restore nyata |
| 6 — Personal Intelligence | Memory architecture → context selection → preference model → project memory → retention/privacy | Memory bersumber, relevan, owner/project-scoped, dapat dikoreksi dan dilupakan |
| 7 — Specialists | Research → Documents → Email → Coding → Data → DevOps | Setiap specialist selesai sebagai vertical slice berizin dan teruji |
| 8 — Experience | Unified planning → multi-step tasks → natural follow-up → cross-agent orchestration → cost/latency → local/cloud routing | Tugas lintas specialist selesai secara durable dalam batas privacy/authority/budget |

## Posisi sekarang

Stage 4 masih terbuka. Full regression baseline, upgrade dan Calendar read telah
diterima dari laporan pengguna. Agenda yang lebih terbaca juga sudah berjalan di bot.
Create/approval/recovery memiliki implementasi dan tes, tetapi smoke tulis serta
beberapa alur percakapan belum diterima. Audit sisa gate: `STAGE4_REMAINING.md`.

## Prinsip yang tetap

- KURO Core memiliki authority; model/specialist mengusulkan pekerjaan.
- PostgreSQL menjadi sumber status, policy references, approval dan audit.
- Secret provider hanya masuk worker yang membutuhkannya.
- Approval terikat tindakan dan penerima/payload yang konkret; premium consent terpisah.
- Input dokumen/provider adalah data tidak tepercaya, bukan sumber izin.
- Tidak ada retry buta setelah efek eksternal mungkin terjadi.
- Setiap freeze berdasarkan release hash dan bukti, bukan jumlah file/agent atau tes historis.

## Kapan hosting

Private pilot dimungkinkan setelah Stage 4 dan kebutuhan operasi Stage 5 lulus. Tidak perlu menunggu semua specialist atau dashboard. Detail dan keputusan yang diperlukan ada di `HOSTING_READINESS.md`. Tidak ada server atau model berbayar yang dibeli/diaktifkan dalam sesi audit.

## Prioritas implementasi terdekat

1. Kandidat OAuth tulis terpisah dan satu smoke create/restart/cancel/delete approval.
2. Selesaikan batas klarifikasi dan waktu eksekusi tertunda pada chat.
3. Satu regresi konsolidasi release akhir, review seluruh gate dan bukti recovery.
4. Freeze Stage 4 hanya bila gate terpenuhi; bangun operasi Stage 5 sesuai bukti.
5. Buktikan backup/restore/rollback/monitoring sebelum rollout privat di hosting.

Web dashboard dan voice bukan persyaratan tersembunyi untuk menutup roadmap ini. Keduanya dapat dirancang kemudian bila pengguna membutuhkannya.
