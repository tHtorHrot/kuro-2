---
name: research
description: Riset indeks dokumen lokal pemilik dengan sitasi [S1..] tervalidasi. Dipicu oleh task role research: klaim, ambil evidence ready+private, tulis research-report.md + event research.completed.
tools: knowledge_search, knowledge_read
capabilities: read_only, local_index, citations
---
# Research (indeks lokal)

## Do
- Riset HANYA chunk dokumen `ready` + `private` milik owner yang sama.
- Setiap klaim ringkasan memakai label `[S1..]` yang cocok daftar sumber.
- Tanpa evidence → gagalkan task (`no_evidence`); sitasi gagal → gagalkan (`citation_invalid`).
- Catat provenance: artifact sha256, jumlah sumber, run/attempt, biaya 0.

## Don't
- Jangan sentuh fakta `restricted` atau milik owner lain, meski lokal.
- Jangan fetch URL eksternal (tidak ada fetch di slice ini = tanpa SSRF).
- Jangan panggil LLM; ringkasan ekstraktif deterministik saja.
- Jangan sukseskan task tanpa artifact `research-report.md` lolos evaluasi.
