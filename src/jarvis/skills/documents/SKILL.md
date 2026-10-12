---
name: documents
description: Tulis file deterministik ke artifact store berversi dari payload acceptance eksplisit. Dipicu oleh task role documents.
tools: artifact_write, knowledge_read
capabilities: artifact_write, versioned
---
# Documents (artifact store berversi)

## Do
- Tulis HANYA dari `acceptance.path` + `acceptance.content` eksplisit.
- Batas: path relatif `.md/.txt/.json/.csv`, isi 1 byte–1 MiB.
- Setiap tulis = versi baru (artifact baru); versi lama tidak dihapus.
- Evaluasi via `eval_code` sebelum commit; gagal = task gagal.

## Don't
- Jangan tulis ke filesystem (artifact store/DB saja; workspace
  filesystem + sandbox menyusul bersama slice Coding).
- Jangan karang isi, gabung sumber, atau panggil LLM di slice ini.
- Jangan timpa tanpa jejak: overwrite = versi baru yang bisa dipulihkan.
- Jangan terima path absolut, `..`, atau tipe di luar allowlist.
