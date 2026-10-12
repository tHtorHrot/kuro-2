# Bukti Stage 7 slice Research fase indeks lokal (11 Okt 2026)

Tanpa credential, tanpa fetch eksternal, tanpa LLM.

## Kode

* Baru `src/jarvis/research/service.py`: klaim (role research saja) →
  retrieval leksikal Postgres (chunk `ready`+`private` milik owner;
  `restricted`/asing tidak masuk) → laporan ekstraktif `[S1..]` +
  provenance (maks 6000 char) → `evaluate_answer` → artifact
  `research-report.md` + event `research.completed` (kutipan 2000 char,
  sha256, sources, steps 1, cost 0) → `succeeded` + ringkasan memory
  tervalidasi. Tanpa evidence/sitasi gagal = `failed` jujur
  (`no_evidence`/`citation_invalid`).
* `orchestration/intake.py`: research dirutekan ke eksekutor nyata;
  knowledge tetap placeholder. tasks-loop/CLI tidak berubah.
* Batas slice: leksikal (semantik Qdrant menyusul), maks 3 dok / 8000
  char evidence, tanpa fetch web (tanpa SSRF karena tanpa fetch),
  tanpa ringkasan LLM. Provider search eksternal = fase berikut.

## Tes

* Unit offline `test_research_report.py`: 3 passed (label+provenance,
  bounded, empty).
* Native `test_research.py`: 2 passed — sitasi lokal + isolasi
  restricted/asing + gagal-jujur + idempoten batch kedua [].
* `test_tasks.py::test_intake_batch_records_and_succeeds` disesuaikan:
  seed 1 dokumen agar research punya evidence (tetap sukses + memory).
* Gate native 11 Okt: **665 passed / 0 failed** (XML 754, subtests 89),
  schema `0016_memory_projects`, source
  `7220b39fdfadf5a30331cc8938d7ef986f350fa8be922aba6885d958aa94be0f`,
  ruff bersih.

## Gate S7-R yang tertutup slice ini

Happy path, invalid input (query kosong → no_evidence),
cross-owner denial (RLS + tes asing), credential isolation (tidak ada
secret disentuh/dibaca), cancellation/recovery (claim/lease/finish
existing + `uncertain_requires_reconcile` tak tersentuh), duplicate
prevention (`client_request_key` existing), output usable (event kutipan
via API/`/task`), cost bounded (0, deterministik).

## Belum (fase berikut, butuh keputusan + kredensial pemilik)

Provider search eksternal (ditentukan + allowlist/SSRF/budget),
fetch+baca bounded, ringkasan LLM via routing economy, retrieval
semantik Qdrant, delivery hasil ke Telegram (saat ini via API
task/events).
