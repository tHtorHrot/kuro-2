# Gate Stage 4 setelah batch kandidat 0009

Stage 4 tetap OPEN. Klarifikasi durable dan scheduled execution **sudah diimplementasikan** pada kandidat, dengan unit/offline checks; keduanya tidak lagi daftar “belum ada di source”. Native/transaksi dan live delta kandidat masih harus diterima sebelum freeze. Daftar/status per item ada di `WORK_MATRIX.md`, bukti di `../docs/evidence/stage-4h/` dan checkpoint root.

- S4-01–03: natural ingress/binding/read existing dipertahankan, offline regression kandidat; prior read/agenda user_reported. Natural-chat LLM live belum diketahui, perlu satu smoke jika belum pernah dibuktikan.
- S4-04/06/07/09/10: durable draft, scoped provenance/expiry/correction, exact approval binding schedule, target cancel, detached job + separate completion, UTC/DST/window tersedia. Native tests ditulis dan dikoleksi; perlu native PG + acceptance delta.
- S4-05/08/11: owner/config/grant/binding rechecked, dedup/lease/fencing/recovery/typed provider tetap. Mock crash setelah provider menerima efek ada di suite native baru; belum dieksekusi di lingkungan asisten.
- S4-12: satu gate consolidated melalui compose.test.yaml + persisted logs/XML/JSON, Docker build dan bounded live delta diperlukan. Baseline 444 pass dan laporan write acceptance pengguna tidak membuktikan source kandidat 0009.

Grammar terbatas: solo create immediate lengkap existing dapat auto-authority dari teks asli; multi-turn/scheduled solo create memakai final approval. Scheduled invite/delete dan planner bebas/lintas specialist bukan bagian slice ini. calendar:send tidak diperluas. Job existing v1 tidak di-upgrade izin/fingerprint atau diulang. Status in-flight/uncertain tidak ditarik balik oleh /cancel.

Tidak perlu mengulang read OAuth/write activation/pairing/grant/volume setup. Jangan memakai filename STAGE4_COMPLETE.md sebagai sertifikat. Stage 5 foundation dapat dikembangkan terisolasi sementara acceptance ini terbuka; belum deploy/freeze.
