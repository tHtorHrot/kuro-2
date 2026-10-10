"""Task API — satu service untuk API dan Telegram (Bagian 7.1 langkah 4).

Progress root task tidak mengunci satu active chat request berjam-jam.
Ingress acknowledgement segera mengembalikan task ID; pekerjaan berjalan
background. Jangan menahan HTTP request sepanjang build/penelitian.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

from jarvis.api.dependencies import CurrentPrincipal, TenantSession
from jarvis.core.errors import ApplicationError
from jarvis.orchestration import repository as task_repo
from jarvis.orchestration.contracts import SubmitGoalInput, TaskError
from jarvis.orchestration.planner import validate_plan
from jarvis.orchestration.task_manager import (
    cancel_task,
    create_plan_tasks,
    mark_task,
    release_ready,
    submit_goal,
)
from jarvis.storage.models import Task

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class SubmitBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    constraints: dict = Field(default_factory=dict)
    client_request_key: str = Field(min_length=1, max_length=128)
    cost_ceiling_usd: float = Field(default=5.0, ge=0, le=1000)
    deadline_seconds: int = Field(default=3600, ge=60, le=86400)
    plan: list[dict] | None = None


class PlanBody(BaseModel):
    nodes: list[dict]
    revision: int = 1


def _view(task: Task) -> dict:
    return {
        "id": str(task.id),
        "root_id": str(task.root_id or task.id),
        "title": task.title,
        "role": task.role,
        "status": task.status,
        "plan_revision": task.plan_revision,
        "cost_ceiling_usd": str(task.cost_ceiling_usd),
        "cost_spent_usd": str(task.cost_spent_usd),
        "error_code": task.error_code,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.post("", status_code=201)
async def submit(body: SubmitBody, actor: CurrentPrincipal, session: TenantSession):
    actor.require("tasks:write")
    plan = validate_plan(body.plan) if body.plan else None
    try:
        root = await submit_goal(
            session.bind if hasattr(session, "bind") else _Db(session),
            SubmitGoalInput(
                owner_id=actor.owner_id,
                goal=body.goal,
                constraints=body.constraints,
                client_request_key=body.client_request_key,
                cost_ceiling_usd=body.cost_ceiling_usd,
                deadline_seconds=body.deadline_seconds,
            ),
            plan=plan,
            plan_keys=[n.get("key", f"t{i}") for i, n in enumerate(body.plan)]
            if body.plan
            else None,
        )
    except TaskError as exc:
        raise ApplicationError(
            409 if "mismatch" in exc.code else 422, exc.code, "Goal ditolak."
        ) from None
    return {"task_id": str(root.id), "status": root.status}


class _Db:
    """Adapter tipis: Task Manager memakai db.tenant(); di request scope
    kita sudah berada dalam tenant session sehingga tenant() cukup yield."""

    def __init__(self, session):
        self._session = session

    def tenant(self, owner_id: UUID):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _ctx():
            yield self._session

        return _ctx()


@router.get("")
async def list_tasks(
    actor: CurrentPrincipal, session: TenantSession, status: str | None = None, limit: int = 50
):
    actor.require("tasks:read")
    rows = await task_repo.list_tasks(session, actor.owner_id, status=status, limit=min(limit, 100))
    return [_view(t) for t in rows]


@router.get("/{task_id}")
async def get_status(task_id: UUID, actor: CurrentPrincipal, session: TenantSession):
    actor.require("tasks:read")
    task = await task_repo.get_task(session, actor.owner_id, task_id)
    if task is None:
        raise ApplicationError(404, "not_found", "Task tidak ditemukan.")
    progress = None
    if task.root_id == task.id or task.parent_id is None:
        progress = await task_repo.task_progress(session, actor.owner_id, task.root_id or task.id)
    return {**_view(task), "progress": progress}


@router.post("/{task_id}/plan")
async def attach_plan(
    task_id: UUID, body: PlanBody, actor: CurrentPrincipal, session: TenantSession
):
    actor.require("tasks:write")
    try:
        created = await create_plan_tasks(_Db(session), actor.owner_id, task_id, body.nodes)
    except TaskError as exc:
        raise ApplicationError(422, exc.code, "Plan ditolak.") from None
    return {"tasks": [str(t.id) for t in created]}


@router.post("/{task_id}/cancel")
async def cancel(task_id: UUID, actor: CurrentPrincipal, session: TenantSession):
    actor.require("tasks:write")
    try:
        task = await cancel_task(_Db(session), actor.owner_id, task_id)
    except TaskError as exc:
        raise ApplicationError(
            404 if exc.code == "task_not_found" else 409, exc.code, "Cancel ditolak."
        ) from None
    return _view(task)


@router.post("/{task_id}/complete")
async def complete(task_id: UUID, body: dict, actor: CurrentPrincipal, session: TenantSession):
    actor.require("tasks:write")
    status = body.get("status", "succeeded")
    if status not in ("succeeded", "failed", "uncertain", "cancelled"):
        raise ApplicationError(422, "task_status_invalid", "Status tidak valid.")
    # Success hanya untuk artifact committed dan required checks passed —
    # caller wajib menyertakan artifact_ids bila succeeded.
    if status == "succeeded" and not body.get("artifact_ids"):
        raise ApplicationError(
            422, "artifact_required", "Succeeded wajib menyertakan artifact_ids."
        )
    try:
        task = await mark_task(
            _Db(session), actor.owner_id, task_id, status, error_code=body.get("error_code")
        )
    except TaskError as exc:
        raise ApplicationError(409, exc.code, "Complete ditolak.") from None
    return _view(task)


@router.post("/release")
async def release(actor: CurrentPrincipal, session: TenantSession):
    actor.require("tasks:write")
    n = await release_ready(_Db(session), actor.owner_id)
    return {"released": n}
