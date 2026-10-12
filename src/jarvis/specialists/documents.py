"""Stage 7 slice Documents (S7-D, fase artifact store).

Tulis deterministik dari payload acceptance eksplisit ke artifact store
berversi: tanpa LLM, tanpa filesystem, tanpa kredensial. Setiap tulis
adalah versi baru; overwrite memulihkan versi lama via daftar versi.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

MAX_WRITE_BYTES = 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".md", ".txt", ".json", ".csv"})


def validate_write_input(acceptance) -> tuple[str, bytes]:
    """Payload eksplisit → (rel_path, bytes). Gagal = TaskError."""
    from jarvis.artifacts.repository import validate_rel_path
    from jarvis.orchestration.contracts import TaskError

    if not isinstance(acceptance, dict):
        raise TaskError("missing_input")
    path = acceptance.get("path")
    content = acceptance.get("content")
    if not isinstance(path, str) or not isinstance(content, str):
        raise TaskError("missing_input")
    validate_rel_path(path)
    if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
        raise TaskError("unsupported_type")
    data = content.encode("utf-8")
    if not 1 <= len(data) <= MAX_WRITE_BYTES:
        raise TaskError("content_size_invalid")
    return path, data


async def list_versions(session, owner: UUID, rel_path: str) -> list:
    """Semua versi satu path milik owner, lama → baru (pemulihan overwrite)."""
    from sqlalchemy import select

    from jarvis.storage.models import Artifact

    return list(
        (
            await session.scalars(
                select(Artifact)
                .where(Artifact.owner_id == owner, Artifact.rel_path == rel_path)
                .order_by(Artifact.created_at, Artifact.id)
            )
        ).all()
    )


async def execute_document_task(
    db, owner: UUID, *, worker: str, run, title: str, acceptance: dict
) -> dict:
    """Satu run tulis sampai terminal; mengembalikan processed dict."""
    from jarvis.agents.manager import finish_run
    from jarvis.artifacts.repository import commit_artifact, mark_evaluated
    from jarvis.memory.service import validated_task_summary
    from jarvis.orchestration.contracts import TaskError
    from jarvis.orchestration.evaluation import eval_code
    from jarvis.orchestration.task_manager import mark_task
    from jarvis.skills.catalog import discover_skills, skill_sha

    try:
        rel_path, data = validate_write_input(acceptance)
        verdict = eval_code(files={rel_path: data.decode("utf-8")})
        if not verdict.passed:
            await finish_run(
                db, owner, run.id, run.lease_token, "failed", error_code="eval_rejected"
            )
            await mark_task(
                db, owner, run.task_id, "failed", error_code="eval_rejected", run_id=run.id
            )
            return {"task_id": str(run.task_id), "status": "failed", "error": "eval_rejected"}
        async with db.tenant(owner) as session:
            prior = await list_versions(session, owner, rel_path)
        version = len(prior) + 1
        artifact = await commit_artifact(
            db,
            owner,
            task_id=run.task_id,
            run_id=run.id,
            lease_token=run.lease_token,
            rel_path=rel_path,
            data=data,
            media_type="text/markdown" if rel_path.endswith(".md") else "text/plain",
        )
        await mark_evaluated(db, owner, artifact.id, "passed")
        await finish_run(db, owner, run.id, run.lease_token, "succeeded")
        done = await mark_task(db, owner, run.task_id, "succeeded", run_id=run.id)
        skill_ref = discover_skills().get("documents")
        async with db.tenant(owner) as session:
            from jarvis.storage.models import TaskEvent

            session.add(
                TaskEvent(
                    owner_id=owner,
                    task_id=run.task_id,
                    run_id=run.id,
                    event_type="documents.completed",
                    payload={
                        "artifact_id": str(artifact.id),
                        "sha256": artifact.sha256,
                        "path": rel_path,
                        "version": version,
                        "bytes": len(data),
                        "steps_used": 1,
                        "cost_usd": "0",
                        "skill": "documents/SKILL.md",
                        "skill_sha256": skill_sha(skill_ref) if skill_ref else "missing",
                    },
                )
            )
        try:
            await validated_task_summary(
                db,
                owner,
                task_id=run.task_id,
                summary=f"{title} -> {done.status} (artifact {artifact.id})",
                provenance=f"task-documents:{run.id}",
            )
        except Exception:
            pass
        return {
            "task_id": str(run.task_id),
            "status": done.status,
            "artifact_id": str(artifact.id),
            "version": version,
            "worker": worker,
        }
    except TaskError as exc:
        from jarvis.agents.manager import finish_run as _finish
        from jarvis.orchestration.task_manager import mark_task as _mark

        try:
            await _finish(db, owner, run.id, run.lease_token, "failed", error_code=exc.code)
            await _mark(db, owner, run.task_id, "failed", error_code=exc.code, run_id=run.id)
        except Exception:
            pass
        return {"task_id": str(run.task_id), "status": "failed", "error": exc.code}
    except Exception as exc:
        from jarvis.agents.manager import finish_run as _finish

        try:
            await _finish(
                db, owner, run.id, run.lease_token, "failed", error_code=type(exc).__name__[:80]
            )
        except Exception:
            pass
        return {"task_id": str(run.task_id), "status": "run_failed", "error": type(exc).__name__}
