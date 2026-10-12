"""Stage 7 Documents slice: tulis berversi + batas + pulih (native PG)."""

from uuid import UUID

import pytest
from sqlalchemy import select
from test_tasks import goal, owner

from jarvis.orchestration.intake import process_intake_batch
from jarvis.orchestration.task_manager import create_plan_tasks, submit_goal
from jarvis.specialists.documents import list_versions
from jarvis.storage.models import Artifact, TaskEvent

pytestmark = pytest.mark.integration


def node(key, acceptance):
    return {
        "key": key,
        "title": "tulis catatan",
        "role": "documents",
        "acceptance": acceptance,
    }


async def excerpt_of(db, oid, task_id):
    async with db.tenant(oid) as session:
        row = await session.scalar(
            select(TaskEvent)
            .where(
                TaskEvent.owner_id == oid,
                TaskEvent.task_id == task_id,
                TaskEvent.event_type == "documents.completed",
            )
            .order_by(TaskEvent.id.desc())
        )
        return row.payload if row else {}


async def test_write_and_overwrite_keep_versions(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, "arsipkan catatan", key="doc-1"))
    await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [node("w0", {"criteria": ["file ada"], "path": "catatan.md", "content": "versi satu"})],
    )
    items = await process_intake_batch(test_db, oid, "doc-loop", 3)
    assert len(items) == 1 and items[0]["status"] == "succeeded"
    assert items[0]["version"] == 1 and items[0]["artifact_id"]
    payload = await excerpt_of(test_db, oid, UUID(items[0]["task_id"]))
    assert payload["version"] == 1 and payload["skill"] == "documents/SKILL.md"

    root2 = await submit_goal(test_db, goal(oid, "arsipkan catatan", key="doc-2"))
    await create_plan_tasks(
        test_db,
        oid,
        root2.id,
        [node("w0", {"criteria": ["file ada"], "path": "catatan.md", "content": "versi dua"})],
    )
    items = await process_intake_batch(test_db, oid, "doc-loop", 3)
    assert items[0]["status"] == "succeeded" and items[0]["version"] == 2
    async with test_db.tenant(oid) as session:
        versions = await list_versions(session, oid, "catatan.md")
        assert len(versions) == 2
        assert versions[0].evaluation_status == "passed"
    assert await process_intake_batch(test_db, oid, "doc-loop", 3) == []


async def test_invalid_payload_fails_honestly(test_db):
    oid = await owner(test_db)
    root = await submit_goal(test_db, goal(oid, "tulis jahat", key="doc-3"))
    await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [node("w0", {"criteria": ["x"], "path": "../escape.md", "content": "jahat"})],
    )
    items = await process_intake_batch(test_db, oid, "doc-loop", 3)
    assert len(items) == 1 and items[0]["status"] == "failed"
    assert items[0]["error"] == "artifact_path_invalid"
    async with test_db.tenant(oid) as session:
        assert (
            await session.scalars(
                select(Artifact).where(
                    Artifact.owner_id == oid, Artifact.rel_path == "../escape.md"
                )
            )
        ).all() == []


async def test_task_detail_shows_document_version_over_bot(test_db):
    from uuid import uuid4 as _uuid4

    from test_assistant import fixture as make_both
    from test_telegram import incoming, receipt

    from jarvis.storage.models import Task, TaskEvent

    tg, repo = await make_both(test_db)
    oid = repo.owner
    async with test_db.tenant(oid) as session:
        task_id = _uuid4()
        session.add(Task(id=task_id, owner_id=oid, title="tulis catatan", root_id=task_id))
        session.add(
            TaskEvent(
                owner_id=oid,
                task_id=task_id,
                event_type="documents.completed",
                payload={"path": "catatan.md", "version": 2, "sha256": "cd" * 32},
            )
        )
    short = str(task_id).replace("-", "")[:8]
    await tg.ingest([incoming(tg, 210, f"/task {short}")], "TestBot")
    text = (await receipt(tg, 210)).reply_text
    assert "Dokumen: catatan.md (versi 2, sha cdcdcdcd)" in text
