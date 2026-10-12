"""Bounded worker runtime — satu execution backend + satu workspace strategy dulu.

Uji output commit/ownership sebelum multi-worker (Bagian 7.1). Worker hanya
mengerjakan read-only Research/Knowledge in-process pada Phase 1; coding/data
didelegasikan ke sandbox (Phase 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from jarvis.agents.manager import claim_task, finish_run, heartbeat_run
from jarvis.execution.sandbox import SandboxError, validate_execution_class


@dataclass(frozen=True)
class WorkerResult:
    run_id: UUID
    status: str
    summary: str


async def run_read_only(
    db, *, owner: UUID, worker_instance: str, roles: list[str] | None = None, knowledge_search=None
) -> WorkerResult | None:
    """Satu worker in-process untuk read-only Research/Knowledge (Phase 1).

    Gerbang capability: role tanpa read_only ditolak sebelum claim apa pun.
    """
    from jarvis.agents.roles import require_capability

    wanted = roles or ["research", "knowledge"]
    require_capability(wanted, "read_only")
    run = await claim_task(db, owner, worker_instance=worker_instance, roles=wanted)
    if run is None:
        return None
    try:
        await heartbeat_run(db, owner, run.id, run.lease_token)
        summary = f"task {run.task_id} diklaim worker {worker_instance}"
        if knowledge_search is not None:
            try:
                hits = await knowledge_search(run.task_id)
                summary += f"; evidence {len(hits or [])}"
            except Exception:
                summary += "; evidence_unavailable"
        await finish_run(db, owner, run.id, run.lease_token, "succeeded")
        return WorkerResult(run.id, "succeeded", summary)
    except Exception as exc:
        try:
            await finish_run(
                db, owner, run.id, run.lease_token, "failed", error_code=type(exc).__name__[:80]
            )
        except Exception:
            pass
        return WorkerResult(run.id, "failed", str(exc)[:200])


async def guarded_code_step(*, tool_effect: str, in_sandbox: bool) -> None:
    """Escaped workspace, leaked secrets, orphan child — ditolak di sini."""
    validate_execution_class(tool_effect, in_sandbox=in_sandbox)
    if not in_sandbox and tool_effect in ("code_exec", "workspace_write"):
        raise SandboxError("sandbox_required")
