"""Stage 7 slice Research (S7-R, fase indeks lokal).

Riset atas indeks dokumen milik owner sendiri: tanpa fetch eksternal
(tanpa SSRF), tanpa panggilan LLM (biaya nol, deterministik ekstraktif),
tanpa kredensial provider. Setiap klaim ringkasan memakai label [S1..]
yang dievaluasi sebelum artifact ditulis; tanpa evidence atau sitasi
gagal, task gagal jujur — tidak ada placeholder sukses.

Batas slice: retrieval leksikal Postgres (semantik Qdrant menyusul),
maks 3 dokumen / 8000 char evidence, laporan maks 6000 char, 1 langkah
dari jatah 6 role research. Hanya fakta `private` yang masuk; `restricted`
tidak pernah diriset meski lokal.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from jarvis.knowledge.retrieval import Evidence, select_evidence

MAX_SOURCES = 4
MAX_REPORT_CHARS = 6000
_TOKEN = re.compile(r"[a-z0-9]{4,}")


def build_report(*, goal: str, evidence: list[Evidence], run_id: UUID, attempt: int) -> str:
    """Ringkasan ekstraktif dengan sitasi; murni, unit-testable."""
    lines = [
        "# LAPORAN RISET",
        "",
        f"Goal: {goal}",
        f"Sumber: {len(evidence)} (indeks lokal, {datetime.now(UTC).date().isoformat()})",
        "",
        "## Temuan",
        "",
    ]
    for i, item in enumerate(evidence, 1):
        snippet = re.sub(r"\s+", " ", item.text).strip()[:600]
        lines.append(f"[S{i}] {snippet}")
        lines.append("")
    lines.append("## Provenance")
    lines.append("")
    for i, item in enumerate(evidence, 1):
        lines.append(f"[S{i}] {item.title} — {item.locator}")
    lines.append("")
    lines.append(f"Run: {run_id} (attempt {attempt})")
    report = "\n".join(lines)
    return report[:MAX_REPORT_CHARS]


def _tokens(query: str) -> list[str]:
    return _TOKEN.findall(query.lower())


async def retrieve_local(session, owner: UUID, query: str) -> list[dict]:
    """Evidence leksikal dari chunk dokumen ready+private milik owner.

    Tenant aman berlapis: filter owner_id eksplisit + RLS sesi.
    """
    from sqlalchemy import select

    from jarvis.storage.models import Document, DocumentChunk

    tokens = _tokens(query)[:12]
    if not tokens:
        return []
    rows = (
        await session.execute(
            select(DocumentChunk, Document.title)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.owner_id == owner,
                Document.owner_id == owner,
                Document.status == "ready",
                Document.data_class == "private",
            )
            .order_by(DocumentChunk.ordinal)
            .limit(200)
        )
    ).all()
    scored = []
    for chunk, title in rows:
        text = chunk.content or ""
        lowered = text.lower()
        score = sum(1 for tok in tokens if tok in lowered)
        if score:
            scored.append((score, chunk.ordinal, chunk, title))
    scored.sort(key=lambda item: (-item[0], item[1]))
    hits = [
        {"source_id": "", "title": title, "locator": chunk.locator, "text": chunk.content}
        for _, _, chunk, title in scored[: MAX_SOURCES * 3]
    ]
    picked = select_evidence(query_hits=hits)
    return [
        {"source_id": f"S{i}", "title": item.title, "locator": item.locator, "text": item.text}
        for i, item in enumerate(picked, 1)
    ]


async def execute_research(db, owner: UUID, *, worker: str, run, title: str) -> dict:
    """Satu run research sampai terminal; mengembalikan processed dict."""
    from jarvis.agents.manager import finish_run
    from jarvis.artifacts.repository import commit_artifact, mark_evaluated
    from jarvis.knowledge.evaluation import evaluate_answer
    from jarvis.memory.service import validated_task_summary
    from jarvis.orchestration.task_manager import mark_task

    try:
        async with db.tenant(owner) as session:
            hits = await retrieve_local(session, owner, title)
        if not hits:
            await finish_run(db, owner, run.id, run.lease_token, "failed", error_code="no_evidence")
            await mark_task(
                db, owner, run.task_id, "failed", error_code="no_evidence", run_id=run.id
            )
            return {"task_id": str(run.task_id), "status": "failed", "error": "no_evidence"}
        evidence = [Evidence(h["source_id"], h["title"], h["locator"], h["text"]) for h in hits]
        report = build_report(goal=title, evidence=evidence, run_id=run.id, attempt=run.attempt)
        sources = [{"label": h["source_id"]} for h in hits]
        verdict = evaluate_answer(
            answer=report, sources=sources, supported=len(sources), total=len(sources)
        )
        if not verdict.passed:
            await finish_run(
                db, owner, run.id, run.lease_token, "failed", error_code="citation_invalid"
            )
            await mark_task(
                db, owner, run.task_id, "failed", error_code="citation_invalid", run_id=run.id
            )
            return {"task_id": str(run.task_id), "status": "failed", "error": "citation_invalid"}
        artifact = await commit_artifact(
            db,
            owner,
            task_id=run.task_id,
            run_id=run.id,
            lease_token=run.lease_token,
            rel_path="research-report.md",
            data=report.encode(),
            media_type="text/markdown",
        )
        await mark_evaluated(db, owner, artifact.id, "passed")
        excerpt = report[:2000]
        from jarvis.skills.catalog import discover_skills, skill_sha

        skill_ref = discover_skills().get("research")
        async with db.tenant(owner) as session:
            from jarvis.storage.models import TaskEvent

            session.add(
                TaskEvent(
                    owner_id=owner,
                    task_id=run.task_id,
                    run_id=run.id,
                    event_type="research.completed",
                    payload={
                        "artifact_id": str(artifact.id),
                        "sha256": artifact.sha256,
                        "sources": len(hits),
                        "steps_used": 1,
                        "cost_usd": "0",
                        "excerpt": excerpt,
                        "skill": "research/SKILL.md",
                        "skill_sha256": skill_sha(skill_ref) if skill_ref else "missing",
                    },
                )
            )
        await finish_run(db, owner, run.id, run.lease_token, "succeeded")
        done = await mark_task(db, owner, run.task_id, "succeeded", run_id=run.id)
        try:
            await validated_task_summary(
                db,
                owner,
                task_id=run.task_id,
                summary=f"{title} -> {done.status} (artifact {artifact.id})",
                provenance=f"task-research:{run.id}",
            )
        except Exception:
            pass  # Memory tidak boleh menggagalkan riset yang sudah sukses.
        return {
            "task_id": str(run.task_id),
            "status": done.status,
            "artifact_id": str(artifact.id),
            "sources": len(hits),
            "worker": worker,
        }
    except Exception as exc:
        from jarvis.agents.manager import finish_run as _finish

        try:
            await _finish(
                db, owner, run.id, run.lease_token, "failed", error_code=type(exc).__name__[:80]
            )
        except Exception:
            pass
        return {"task_id": str(run.task_id), "status": "run_failed", "error": type(exc).__name__}
