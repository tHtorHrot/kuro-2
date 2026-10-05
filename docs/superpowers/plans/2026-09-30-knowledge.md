# Knowledge Implementation Plan

> For agentic workers: use superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** Deliver stage 3 as an upgrade ZIP supporting private PDF/DOCX/scanned documents and sourced Telegram questions.

**Architecture:** An isolated parser extracts bounded text, a durable owner-scoped worker indexes local embeddings into private Qdrant, and the existing assistant consumes immutable retrieval snapshots. Preserve existing cloud consent and cost controls.

**Tech Stack:** Python 3.12, PostgreSQL 16, SQLAlchemy, FastAPI/httpx, Poppler, Tesseract, FastEmbed, Qdrant, Docker Compose.

**Spec:** docs/superpowers/specs/2026-09-30-knowledge.md

## Global Constraints

Version 0.4.0; schema 0004_knowledge; preserve current owner/pairing/config/budget. No automatic premium or cloud OCR. Limits and isolation exactly as spec. Native tests require PostgreSQL, not SQLite. Archive has project files at its root, excludes credentials and data.

## Review Focus

1. Delete while indexing must never revive or leave searchable data (Task 2/3).
2. Cross-owner vector IDs must fail database revalidation (Task 2).
3. Corrupt PDFs and decompression bombs must terminate within resource bounds (Task 1).
4. A document deleted after premium approval invalidates snapshot/dispatch (Task 3).
5. Windows upload and failed CLI child must preserve bytes and propagate exit codes (Task 4).

### Task 1: Bounded extraction and source formatting

Files: new knowledge/config.py, extraction.py, parser_app.py, content.py; tests/unit/test_knowledge_content.py, test_knowledge_extraction.py.
Interfaces: extract(path, kind, ocr) -> list[Segment]; chunk_segments(segments) -> list[Chunk]; sourced_messages(question,sources) -> list[dict]; format_answer(answer,sources) -> str.
- [x] Write behavior tests for DOCX paragraph/table locators, PDF mixed/text/OCR, malformed input, archive expansion limits, chunk overlap, untrusted source delimiters, citation rejection.
- [x] Run tests and record missing-feature failure.
- [x] Implement bounded parser and pure formatting without touching assistant behavior.
- [x] Run focused tests including a real OCR fixture; commit verified code.

### Task 2: Durable storage, indexing and operator interface

Files: migration 0004, storage/models.py, knowledge/repository.py, services.py, worker.py, cli.py; tests/integration/test_knowledge.py, unit/test_knowledge_services.py.
Interfaces: KnowledgeRepository(db, owner, store); import_file(filename,bytes,data_class,ocr); claim() -> Document; process(document); prepare_query(); request_delete(session,owner,document).
- [x] Add failing integration and HTTP boundary tests: duplicates, owner isolation, leases, deletion races, Qdrant response validation.
- [x] Implement RLS tables, UUID paths, atomic imports, worker lock and bounded retry, offline embeddings and Qdrant REST adapter.
- [x] Run available tests; explicitly retain native-only skips if PostgreSQL cannot run. Commit.

### Task 3: Telegram document queries and deletion

Files: assistant/repository.py, assistant/policy.py, interfaces/telegram/commands.py; knowledge/commands.py; tests/integration/test_knowledge.py.
Interfaces: /askdoc creates AssistantRequest.document_id; knowledge worker fills sources before normal prepare; dispatch/finish verify document availability; answers must cite only supplied IDs.
- [x] Write failing tests for no-source/restricted requests without inference, no document memory contamination, deletion after consent, and valid source suffix.
- [x] Implement commands and immutable sourced snapshot through existing workflow/cost ledger. Keep /ask unchanged.
- [x] Run full regression and commit.

### Task 4: Compose, Windows upgrade and package

Files: Dockerfile, compose.knowledge.yaml, pyproject.toml/uv.lock, scripts/documents.py, docs/KNOWLEDGE_WINDOWS.md, README.md, docs/evidence/stage-3.
- [x] Add failing host-wrapper tests for byte streaming/exit codes; implement CLI/Compose packaging.
- [x] Pin dependencies/image versions, verify runtime isolation and schema SQL, run full available suite/lint/format.
- [x] Obtain one fresh-context code review under executing-plans; fix material findings with regression tests.
- [x] Build archive root layout and manifest; exclude secrets, caches, .git, data. Save ZIP and report actual verification limits.

Status pelaksanaan: implementasi dan pemeriksaan tersedia selesai; native acceptance tetap mengikuti rulings dan STAGE_3_VERIFICATION.md.
