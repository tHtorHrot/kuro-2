# Bukti Stage 7 slice Documents fase artifact store (12 Okt 2026)

Tanpa LLM, tanpa filesystem, tanpa kredensial, tanpa fetch.

## Kode

* `agents/roles.py`: role baru `documents` (allowlist
  artifact_write/knowledge_read, capabilities artifact_write/versioned,
  economy, skill documents). `run_read_only` otomatis menolaknya
  (tanpa read_only) — sudah teruji di tes capabilities.
* `skills/documents/SKILL.md`: kanonis Do/Don't.
* `specialists/documents.py`: `validate_write_input` murni (path
  relatif + sufiks md/txt/json/csv + 1 byte–1 MiB) + `execute_document_task`
  (eval_code → commit artifact → evaluated passed → succeeded + event
  `documents.completed` + ringkasan memory) + `list_versions`
  (overwrite = versi baru, lama retained).
* `orchestration/intake.py`: role documents dirutekan ke eksekutor
  (knowledge tetap placeholder). Konten dari `acceptance.path` +
  `acceptance.content` eksplisit (tanpa ubah skema PlanNode).
* `migrations/0017_task_role_documents.py`: CHECK role + 'documents'
  (aditif; 0001–0016 tak diubah). Pin schema 0016→0017 di database,
  release_gate, check_test_upgrade (+uji insert role), ops_restore,
  stage4_completion, wasm.

## Tes + gate

* Unit `test_documents_write.py`: 1 valid + 10 invalid.
* Native `test_documents.py`: tulis v1 → overwrite v2 (2 versi
  retained) + invalid (`../escape.md` → failed, tanpa artifact).
* Gate native 12 Okt: **701 passed / 0 failed** (XML 790, subtests 89),
  schema `0017_task_role_documents`, source
  `238318534cbe3cad09985b59e7e73b8f3a28b3e26d8e26bb7b8fc151b7286788`,
  `verdict: passed`, ruff bersih.
* `/task` anak documents tampilkan versi/path/sha (teruji native via
  bot-transport).

## Batas slice (fase berikut)

Ringkasan LLM/generator konten (Stage 8), tulis filesystem + sandbox
(bersama Coding), baca via bot (butuh perintah baca artifact).

## Live produksi 12 Okt (USER_REPORTED, tidak dieksekusi asisten)

* Upgrade 0016→0017 + rebuild + doctor `ready` (pola backup/migrate/
  recreate yang sama).
* `/task 15896e2a` tampilkan baris baru:
  `Dokumen: catatan.md (versi 1, sha d09bd660)`.
* `/goal arsip catatan` → root `2b045be9` queued → plan API 1 anak
  documents (`15896e2a`, acceptance path+content eksplisit).
* tasks-loop eksekusi → anak `succeeded`; `/task 2b045be9`
  tampilkan anak; `/task 15896e2a` tampilkan status.
* Insiden API selama uji (bukan bug produk): filter PowerShell
  `Where title -like` tidak memfilter di sesi itu (24 ID masuk URL →
  422) — mitigasi: ID eksplisit dari bot/API. Token bocor ke chat
  1x → revoke + ganti (kebijakan: token tak pernah ditempel ke chat).
