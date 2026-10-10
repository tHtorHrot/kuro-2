"""KURO Ultimate task gates on disposable PostgreSQL (native).

Failure matrix Bagian 7.2 melawan DB beneran: idempotency, conflict,
cycle rejection, claim race (satu pemenang), stale lease, uncertain tanpa
auto-retry, dependency release, dan sequence grant task_events (0013).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update
from test_telegram import make_repo

from jarvis.agents.manager import claim_task, heartbeat_run
from jarvis.artifacts.repository import commit_artifact
from jarvis.execution.recovery import recover_runs
from jarvis.operations.task_retention import prune_events
from jarvis.orchestration.contracts import SubmitGoalInput, TaskError
from jarvis.orchestration.task_manager import (
    cancel_task,
    create_plan_tasks,
    mark_task,
    maybe_complete_parent,
    release_ready,
    submit_goal,
)
from jarvis.storage.models import Task, TaskEvent, TaskRun, ToolAction

pytestmark = pytest.mark.integration


async def owner(db):
    return (await make_repo(db)).config.owner_id


def goal(owner_id, text="ringkas dokumen", key=None):
    return SubmitGoalInput(owner_id=owner_id, goal=text, client_request_key=key or uuid4().hex[:16])


async def test_submit_idempotent_same_key_same_payload(test_db):
    oid = await owner(test_db)
    first = await submit_goal(test_db, goal(oid, key="idem-1"))
    second = await submit_goal(test_db, goal(oid, key="idem-1"))
    assert first.id == second.id


async def test_submit_same_key_different_payload_conflict(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, SubmitGoalInput(owner_id=oid, goal="a", client_request_key="k"))
    with pytest.raises(TaskError, match="request_key_payload_mismatch"):
        await submit_goal(test_db, SubmitGoalInput(owner_id=oid, goal="b", client_request_key="k"))


async def test_plan_cycle_rejected_before_dispatch(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="plan-1"))
    nodes = [
        {
            "key": "a",
            "title": "A",
            "role": "research",
            "acceptance": {"criteria": ["x"]},
            "depends_on": ["b"],
        },
        {
            "key": "b",
            "title": "B",
            "role": "research",
            "acceptance": {"criteria": ["x"]},
            "depends_on": ["a"],
        },
    ]
    with pytest.raises(TaskError, match="plan_cycle_rejected"):
        await create_plan_tasks(test_db, oid, root.id, nodes)


async def test_dependency_release_after_success(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="dep-1"))
    kids = await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {"key": "a", "title": "A", "role": "research", "acceptance": {"criteria": ["x"]}},
            {
                "key": "b",
                "title": "B",
                "role": "research",
                "acceptance": {"criteria": ["x"]},
                "depends_on": ["a"],
            },
        ],
    )
    assert {k.status for k in kids} == {"queued", "waiting_dependency"}
    assert await release_ready(test_db, oid) == 0
    await mark_task(test_db, oid, kids[0].id, "succeeded")
    assert await release_ready(test_db, oid) == 1


async def test_two_workers_claim_same_task_single_winner(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, goal(oid, key="claim-1"))
    first = await claim_task(test_db, oid, worker_instance="w1", roles=["planner"])
    second = await claim_task(test_db, oid, worker_instance="w2", roles=["planner"])
    assert first is not None and second is None


async def test_stale_worker_lease_rejected(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, goal(oid, key="stale-1"))
    run = await claim_task(test_db, oid, worker_instance="w1", roles=["planner"])
    with pytest.raises(TaskError, match="stale_run_lease"):
        await heartbeat_run(test_db, oid, run.id, uuid4())
    await heartbeat_run(test_db, oid, run.id, run.lease_token)


async def test_uncertain_requires_reconcile_no_auto_retry(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="unc-1"))
    await mark_task(test_db, oid, root.id, "uncertain", error_code="provider_ambiguous")
    with pytest.raises(TaskError, match="uncertain_requires_reconcile"):
        await mark_task(test_db, oid, root.id, "queued")
    done = await cancel_task(test_db, oid, root.id)
    assert done.status == "cancelled"


async def test_artifact_commit_uses_event_sequence_grant(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, goal(oid, key="art-1"))
    run = await claim_task(test_db, oid, worker_instance="w1", roles=["planner"])
    artifact = await commit_artifact(
        test_db,
        oid,
        task_id=run.task_id,
        run_id=run.id,
        lease_token=run.lease_token,
        rel_path="ringkasan.txt",
        data=b"hasil",
    )
    assert artifact.evaluation_status == "pending" and artifact.byte_size == 5


async def test_intake_batch_records_and_succeeds(test_db):
    from jarvis.orchestration.intake import process_intake_batch
    from jarvis.orchestration.task_manager import create_plan_tasks
    from jarvis.storage.models import ProfileMemory, Task

    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, "catat ini", key="int-1"))
    # Intake tidak menyentuh root planner; hanya subtask research/knowledge.
    assert await process_intake_batch(test_db, oid, "test-loop", 3) == []
    kids = await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {
                "key": "r0",
                "title": "kumpulkan fakta",
                "role": "research",
                "acceptance": {"criteria": ["3 fakta"]},
            }
        ],
    )
    items = await process_intake_batch(test_db, oid, "test-loop", 3)
    assert len(items) == 1 and items[0]["status"] == "succeeded"
    assert items[0]["artifact_id"]
    assert await process_intake_batch(test_db, oid, "test-loop", 3) == []
    key = "task:" + kids[0].id.hex[:12]
    async with test_db.tenant(oid) as session:
        fact = await session.get(ProfileMemory, (oid, key))
        stored_root = await session.get(Task, root.id)
    assert fact is not None and "kumpulkan fakta" in fact.value
    # Auto-rollup: single child succeeded -> root auto-succeeds via mark_task.
    assert stored_root.status == "succeeded"


async def test_expired_claim_recovers_to_queued(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, goal(oid, key="rec-1"))
    run = await claim_task(test_db, oid, worker_instance="w1", roles=["planner"])
    async with test_db.tenant(oid) as session:
        await session.execute(
            update(TaskRun)
            .where(TaskRun.owner_id == oid, TaskRun.id == run.id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(minutes=10))
        )
    stats = await recover_runs(test_db, oid)
    assert stats["lost"] == 1 and stats["requeued"] == 1


async def test_lost_during_dispatch_keeps_task_uncertain(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, goal(oid, key="unc-2"))
    run = await claim_task(test_db, oid, worker_instance="w1", roles=["planner"])
    await heartbeat_run(test_db, oid, run.id, run.lease_token)
    async with test_db.tenant(oid) as session:
        session.add(
            ToolAction(
                owner_id=oid,
                task_run_id=run.id,
                agent="calendar",
                tool_name="calendar_create_event",
                effect="reversible_write",
                arguments={"title": "x"},
                action_fingerprint="f" * 64,
                status="dispatching",
                authorization_reason="already_authorized",
                due_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.execute(
            update(TaskRun)
            .where(TaskRun.owner_id == oid, TaskRun.id == run.id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(minutes=10))
        )
    await recover_runs(test_db, oid)
    async with test_db.tenant(oid) as session:
        task = await session.get(Task, run.task_id)
    assert task is not None and task.owner_id == oid
    assert task.status == "uncertain"


async def test_task_event_retention_dry_run_then_apply(test_db):
    oid = await owner(test_db)
    await submit_goal(test_db, goal(oid, key="ret-1"))
    async with test_db.tenant(oid) as session:
        await session.execute(
            update(TaskEvent)
            .where(TaskEvent.owner_id == oid)
            .values(created_at=datetime.now(UTC) - timedelta(days=100))
        )
    dry = await prune_events(test_db, oid, older_than_days=90, limit=500, apply=False)
    assert dry["prunable"] >= 1 and dry["deleted"] == 0
    done = await prune_events(test_db, oid, older_than_days=90, limit=500, apply=True)
    assert done["deleted"] >= 1
    again = await prune_events(test_db, oid, older_than_days=90, limit=500, apply=False)
    assert again["prunable"] == 0


async def test_automation_tick_launches_once_then_idempotent(test_db):
    from jarvis.automation.service import create_definition, tick

    oid = await owner(test_db)
    # Definition harian 00:01 UTC; tick Tepat sesudahnya hanya meluncurkan sekali.
    definition = await create_definition(
        test_db,
        oid,
        title="laporan harian",
        timezone="UTC",
        rrule="FREQ=DAILY;BYHOUR=0;BYMINUTE=1",
        goal_template="buat ringkasan",
    )
    moment = datetime(2026, 10, 8, 0, 2, tzinfo=UTC)
    first = await tick(test_db, oid, now=moment)
    assert len(first) == 1 and first[0]["task_id"]
    assert first[0]["definition_id"] == str(definition.id)
    assert await tick(test_db, oid, now=moment) == []


class _StubRouter:
    """Provider pengganti untuk gate: tanpa network, tanpa biaya."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0

    async def complete(self, plan, messages):
        from decimal import Decimal

        from jarvis.assistant.router import Completion

        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return Completion(text, Decimal(0), 10, 20)


def _plan_stub():
    return {"model": "test/model", "provider": "test", "reserve_usd": "0"}


_GOOD_PROPOSAL = (
    '[{"key": "t0", "title": "Kumpulkan fakta", "role": "research", '
    '"acceptance": {"criteria": ["3 fakta berprovenance"]}, "depends_on": []}, '
    '{"key": "t1", "title": "Tulis ringkasan", "role": "communication", '
    '"acceptance": {"criteria": ["ringkasan <= 200 kata"]}, '
    '"depends_on": ["t0"], "cost_ceiling_usd": 0.5}]'
)


async def test_auto_plan_creates_subtasks_with_stub_router(test_db):
    from jarvis.orchestration.llm_planner import propose_plan

    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, "susun laporan", key="auto-1"))
    out = await propose_plan(
        test_db, oid, root.id, router=_StubRouter([_GOOD_PROPOSAL]), endpoint_plan=_plan_stub()
    )
    assert out["repair_used"] is False and len(out["subtasks"]) == 2


async def test_auto_plan_repair_then_marks_failed(test_db):
    from jarvis.orchestration.llm_planner import PlanProposalError, propose_plan

    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, "susun laporan", key="auto-2"))
    router = _StubRouter(["bukan json sama sekali"])
    with pytest.raises(PlanProposalError):
        await propose_plan(
            test_db, oid, root.id, router=router, endpoint_plan=_plan_stub(), max_attempts=2
        )
    assert router.calls == 2
    async with test_db.tenant(oid) as session:
        stored = await session.get(Task, root.id)
    assert stored.status == "failed"


async def test_parent_rollup_succeeds_when_all_children_done(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="roll-1"))
    kids = await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {
                "key": "a",
                "title": "A",
                "role": "research",
                "acceptance": {"criteria": ["x"]},
            },
            {
                "key": "b",
                "title": "B",
                "role": "research",
                "acceptance": {"criteria": ["x"]},
            },
        ],
    )
    await mark_task(test_db, oid, kids[0].id, "succeeded")
    assert await maybe_complete_parent(test_db, oid, kids[0].id) is None
    await mark_task(test_db, oid, kids[1].id, "succeeded")
    # mark_task auto-rollups; explicit second call is no-op, verify stored root.
    assert await maybe_complete_parent(test_db, oid, kids[1].id) is None
    async with test_db.tenant(oid) as session:
        stored = await session.get(Task, root.id)
    assert stored.status == "succeeded"


async def test_task_budget_ceiling_enforced_without_provider(test_db):
    from jarvis.orchestration.task_inference import dispatch_task_call

    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="bud-1"))
    run = await claim_task(test_db, oid, worker_instance="w1", roles=["planner"])
    async with test_db.tenant(oid) as session:
        await session.execute(
            update(Task).where(Task.owner_id == oid, Task.id == root.id).values(cost_ceiling_usd=0)
        )
    with pytest.raises(TaskError, match="task_budget_exceeded"):
        await dispatch_task_call(test_db, oid, run_id=run.id, plan=_plan_stub())


async def test_rollup_propagates_failed_and_uncertain(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="roll-1"))
    kids = await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {
                "key": "a",
                "title": "A",
                "role": "research",
                "acceptance": {"criteria": ["x"]},
            },
            {
                "key": "b",
                "title": "B",
                "role": "research",
                "acceptance": {"criteria": ["x"]},
            },
        ],
    )
    await mark_task(test_db, oid, kids[0].id, "succeeded")
    await mark_task(test_db, oid, kids[1].id, "uncertain", error_code="ambiguous")
    async with test_db.tenant(oid) as session:
        from jarvis.storage.models import Task

        stored = await session.get(Task, root.id)
    assert stored.status == "uncertain" and stored.error_code == "rollup_uncertain_child"


async def test_rollup_runs_automatically_on_child_completion(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, key="roll-2"))
    kids = await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {
                "key": "a",
                "title": "A",
                "role": "research",
                "acceptance": {"criteria": ["x"]},
            }
        ],
    )
    await mark_task(test_db, oid, kids[0].id, "succeeded")
    async with test_db.tenant(oid) as session:
        from jarvis.storage.models import Task

        stored = await session.get(Task, root.id)
    assert stored.status == "succeeded"
