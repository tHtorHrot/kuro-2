"""Task-owned inference ledger — cermin policy chat, tanpa fake request.

Chat memakai (request_id, kind) untuk idempotency; task memakai
(task_run_id, kind). Free route: reserve harus 0 + batas harian. Premium
DITOLAK di sini (butuh persetujuan per panggilan lewat jalur chat).
Commit dispatch DULU, panggil provider, commit finish — tidak menahan
transaksi saat I/O jaringan. Ambiguous call mengikuti prinsip existing:
tahan cap sebagaimana billed yang belum pasti.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select

from jarvis.assistant.policy import money
from jarvis.orchestration.contracts import TaskError
from jarvis.storage.models import LLMCall, Task, TaskRun


def _now():
    return datetime.now(UTC)


async def _live_run(session, owner: UUID, run_id: UUID) -> TaskRun:
    run = await session.get(TaskRun, run_id, with_for_update=True)
    if run is None or run.owner_id != owner:
        raise TaskError("run_not_found")
    if (
        run.lease_token is None
        or run.status not in ("claimed", "running")
        or (run.lease_expires_at is not None and run.lease_expires_at <= _now())
    ):
        raise TaskError("stale_run_lease")
    return run


async def dispatch_task_call(
    db, owner: UUID, *, run_id: UUID, plan: dict, kind: str = "free"
) -> UUID:
    """Reservasi + catat LLMCall untuk task run. Kembalikan call ID."""
    if kind != "free":
        raise TaskError("task_premium_requires_chat_consent")
    if not isinstance(plan, dict) or not plan.get("model") or not plan.get("provider"):
        raise TaskError("task_plan_invalid")
    try:
        cap = money(plan.get("reserve_usd", 0))
    except Exception:
        raise TaskError("task_plan_invalid") from None
    if cap != 0:
        raise TaskError("free_route_has_cost")
    async with db.tenant(owner) as session:
        run = await _live_run(session, owner, run_id)
        task = await session.get(Task, run.task_id, with_for_update=True)
        if task is None or task.owner_id != owner:
            raise TaskError("task_not_found")
        if task.cost_spent_usd >= task.cost_ceiling_usd:
            raise TaskError("task_budget_exceeded")
        existing = await session.scalar(
            select(LLMCall).where(
                LLMCall.owner_id == owner,
                LLMCall.task_run_id == run.id,
                LLMCall.kind == kind,
            )
        )
        if existing:
            raise TaskError("attempt_already_used")
        day = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        count = await session.scalar(
            select(func.count())
            .select_from(LLMCall)
            .where(
                LLMCall.owner_id == owner,
                LLMCall.kind == "free",
                LLMCall.created_at >= day,
            )
        )
        daily_limit = 15
        try:
            from jarvis.assistant.config import load_assistant_config

            daily_limit = load_assistant_config().daily_free_calls
        except Exception:
            pass
        if (count or 0) >= daily_limit:
            raise TaskError("daily_free_limit")
        call = LLMCall(
            id=uuid4(),
            owner_id=owner,
            request_id=None,
            task_run_id=run.id,
            kind=kind,
            model=str(plan["model"])[:200],
            provider=str(plan["provider"])[:120],
            status="dispatching",
            reserved_usd=cap,
            created_at=_now(),
        )
        session.add(call)
        await session.flush()
        return call.id


async def finish_task_call(db, owner: UUID, *, call_id: UUID, result=None, error=None) -> dict:
    """Catat actual usage; uncertain mengikuti semantik ledger existing."""
    async with db.tenant(owner) as session:
        call = await session.get(LLMCall, call_id, with_for_update=True)
        if call is None or call.owner_id != owner:
            raise TaskError("call_not_found")
        if call.status != "dispatching":
            raise TaskError("call_not_dispatching")
        call.finished_at = _now()
        if result is not None:
            call.status = "succeeded"
            call.actual_usd = Decimal(str(result.cost))
            call.prompt_tokens = result.prompt_tokens
            call.completion_tokens = result.completion_tokens
        else:
            uncertain = error is None or bool(getattr(error, "uncertain", False))
            call.status = "uncertain" if uncertain else "rejected"
            if call.status == "rejected":
                call.actual_usd = Decimal(0)
            elif error is not None and getattr(error, "kind", "") in {
                "policy_violation",
                "unverifiable_response",
            }:
                call.actual_usd = call.reserved_usd
        if call.task_run_id is not None and call.actual_usd is not None:
            run = await session.get(TaskRun, call.task_run_id)
            if run is not None and run.owner_id == owner:
                task = await session.get(Task, run.task_id)
                if task is not None and task.owner_id == owner:
                    task.cost_spent_usd = (task.cost_spent_usd or Decimal(0)) + call.actual_usd
                    task.updated_at = _now()
        return {"status": call.status, "actual_usd": str(call.actual_usd or 0)}
