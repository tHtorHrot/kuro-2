# Bukti pelajaran AO #5: review artifact di complete (11 Okt 2026)

Workspace/sandbox Kuro ternyata sudah implementasi (worktree/managed,
resolve_inside, quarantine-dirty, docker args nonroot) + teruji
(`test_workspace_rejects_escape`) — tidak ada kerja di sana. Celah nyata
yang ditutup: `POST complete(succeeded)` tidak verifikasi `artifact_ids`
sama sekali, padahal kontrak modul menuntut "checks passed".

## Kode (tanpa kredensial, tanpa migrasi)

* `artifacts/repository.py`: `artifact_accepted()` murni (hanya passed
  milik task ini; seragam tolak tanpa oracle) + `require_accepted()`
  (ID malformed ditolak SEBELUM SQL — asyncpg melempar 500 bila cast
  UUID gagal di WHERE).
* `api/tasks.py::complete()`: verifikasi artifact dulu, baru
  `mark_task`. Peta error: task_not_found→404 (selaras `cancel`),
  artifact_not_accepted→422, sisanya 409 (tak berubah).

## Tes + gate

* Unit `test_artifact_review.py`: terima passed; tolak
  hilang/asing/task-lain/pending/failed/needs_human/unknown.
* Native `test_task_complete_review.py`: endpoint + app + DB nyata —
  200 untuk passed; 422 `artifact_not_accepted` untuk pending, failed,
  task-lain, ghost, malformed, campuran; 422 `artifact_required`
  tanpa IDs.
* Pelajaran tes: `submit_goal` idempoten per key — seed ganda wajib
  key beda.
* Gate native 11 Okt: **686 passed / 0 failed** (XML 775, subtests 89),
  schema `0016_memory_projects`, source
  `e20361f4a8186478bd0a9d2de1b0abcd286a7b431b7a348c92520fda902cbba0`,
  `verdict: passed`, ruff bersih.
