"""Intake batch — dipakai CLI tasks-run-once dan tasks-loop.

Memindahkan satu task read-only (planner/research/knowledge) dari queued
menjadi succeeded dengan intake-record artifact berprovenance. BUKAN hasil
eksekusi; eksekusi otonom butuh worker backend + sandbox (tahap berikutnya).
"""

from __future__ import annotations

from uuid import UUID

INTAKE_ROLES = ["research", "knowledge"]


async def process_intake_batch(db, owner_id: UUID, worker: str, max_n: int) -> list[dict]:
    from jarvis.agents.manager import claim_task, finish_run
    from jarvis.artifacts.repository import commit_artifact, mark_evaluated
    from jarvis.orchestration import repository as task_repo
    from jarvis.orchestration.task_manager import mark_task

    if not 1 <= max_n <= 10:
        raise ValueError("max_n must be 1..10")
    processed: list[dict] = []
    for _ in range(max_n):
        run = await claim_task(db, owner_id, worker_instance=worker, roles=list(INTAKE_ROLES))
        if run is None:
            break
        try:
            async with db.tenant(owner_id) as session:
                task = await task_repo.get_task(session, owner_id, run.task_id)
                title = task.title if task else str(run.task_id)
            record = (
                "# INTAKE RECORD\n\n"
                f"Goal: {title}\nWorker: {worker}\nRun: {run.id}\n"
                f"Attempt: {run.attempt}\n\nCatatan: arsip intake otomatis; "
                "BUKAN hasil eksekusi. Menunggu worker/operator.\n"
            ).encode()
            artifact = await commit_artifact(
                db,
                owner_id,
                task_id=run.task_id,
                run_id=run.id,
                lease_token=run.lease_token,
                rel_path="intake-record.md",
                data=record,
                media_type="text/markdown",
            )
            await mark_evaluated(db, owner_id, artifact.id, "passed")
            await finish_run(db, owner_id, run.id, run.lease_token, "succeeded")
            done = await mark_task(db, owner_id, run.task_id, "succeeded", run_id=run.id)
            try:
                from jarvis.orchestration.task_manager import maybe_complete_parent

                await maybe_complete_parent(db, owner_id, run.task_id)
            except Exception:
                pass
            try:
                from jarvis.memory.service import validated_task_summary

                await validated_task_summary(
                    db,
                    owner_id,
                    task_id=run.task_id,
                    summary=f"{title} -> {done.status} (artifact {artifact.id})",
                    provenance=f"task-intake:{run.id}",
                )
            except Exception:
                pass  # Memory tidak boleh menggagalkan batch intake.
            processed.append(
                {
                    "task_id": str(run.task_id),
                    "status": done.status,
                    "artifact_id": str(artifact.id),
                }
            )
        except Exception as exc:
            try:
                await finish_run(
                    db,
                    owner_id,
                    run.id,
                    run.lease_token,
                    "failed",
                    error_code=type(exc).__name__[:80],
                )
            except Exception:
                pass
            processed.append(
                {
                    "task_id": str(run.task_id),
                    "status": "run_failed",
                    "error": type(exc).__name__,
                }
            )
    return processed
