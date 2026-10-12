"""Stage 7 Research slice: eksekusi nyata atas indeks lokal (native PG)."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_tasks import goal, owner
from test_telegram import make_repo

from jarvis.orchestration.intake import process_intake_batch
from jarvis.orchestration.task_manager import create_plan_tasks, submit_goal
from jarvis.storage.models import Artifact, Document, DocumentChunk, TaskEvent

pytestmark = pytest.mark.integration


async def seed_doc(db, oid, *, title, words, data_class="private"):
    doc = uuid4()
    async with db.tenant(oid) as session:
        session.add(
            Document(
                id=doc,
                owner_id=oid,
                title=title,
                kind="pdf",
                data_class=data_class,
                pipeline="knowledge-1-minilm384",
                ocr="never",
                status="ready",
                byte_size=100,
            )
        )
        for n, word in enumerate(words):
            session.add(
                DocumentChunk(
                    id=uuid4(),
                    owner_id=oid,
                    document_id=doc,
                    ordinal=n,
                    locator=f"paragraf {n + 1}",
                    content=f"catatan {word} untuk validasi riset",
                )
            )
    return doc


async def excerpt_of(db, oid, task_id):
    async with db.tenant(oid) as session:
        row = await session.scalar(
            select(TaskEvent)
            .where(
                TaskEvent.owner_id == oid,
                TaskEvent.task_id == task_id,
                TaskEvent.event_type == "research.completed",
            )
            .order_by(TaskEvent.id.desc())
        )
        return row.payload if row else {}


async def test_research_cites_local_evidence_and_ignores_restricted_and_foreign(test_db):
    oid = await owner(test_db)
    await seed_doc(db=test_db, oid=oid, title="Catatan Kopi", words=["kopi tubruk", "kopi seduh"])
    await seed_doc(
        db=test_db, oid=oid, title="Rahasia", words=["kopi tubruk rahasia"], data_class="restricted"
    )
    other = (await make_repo(test_db)).config.owner_id
    await seed_doc(db=test_db, oid=other, title="Asing", words=["kopi tubruk asing"])
    root = await submit_goal(test_db, goal(oid, "riset kopi tubruk", key="rs-1"))
    await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {
                "key": "r0",
                "title": "riset kopi tubruk",
                "role": "research",
                "acceptance": {"criteria": ["sitasi"]},
            }
        ],
    )
    items = await process_intake_batch(test_db, oid, "research-loop", 3)
    assert len(items) == 1 and items[0]["status"] == "succeeded"
    assert items[0]["sources"] >= 1 and items[0]["artifact_id"]
    async with test_db.tenant(oid) as session:
        artifact = await session.get(Artifact, UUID(items[0]["artifact_id"]))
        assert artifact.evaluation_status == "passed"
    payload = await excerpt_of(test_db, oid, UUID(items[0]["task_id"]))
    assert "[S1]" in payload["excerpt"] and payload["cost_usd"] == "0"
    assert "rahasia" not in payload["excerpt"] and "asing" not in payload["excerpt"]
    assert payload["sha256"] == artifact.sha256
    assert payload["skill"] == "research/SKILL.md" and len(payload["skill_sha256"]) == 16
    assert await process_intake_batch(test_db, oid, "research-loop", 3) == []


async def test_research_without_evidence_fails_honestly(test_db):
    oid = await owner(test_db)
    root = await submit_goal(
        test_db, goal(oid, "topik yang tidak ada di mana pun zzzqqq", key="rs-2")
    )
    await create_plan_tasks(
        test_db,
        oid,
        root.id,
        [
            {
                "key": "r0",
                "title": "topik yang tidak ada di mana pun zzzqqq",
                "role": "research",
                "acceptance": {"criteria": ["sitasi"]},
            }
        ],
    )
    items = await process_intake_batch(test_db, oid, "research-loop", 3)
    assert len(items) == 1 and items[0]["status"] == "failed"
    assert items[0]["error"] == "no_evidence"


async def test_task_detail_shows_children_and_research_excerpt_over_bot(test_db):
    from uuid import uuid4 as _uuid4

    from test_assistant import fixture as make_both
    from test_telegram import incoming, receipt

    from jarvis.storage.models import Task, TaskEvent

    tg, repo = await make_both(test_db)
    oid = repo.owner
    async with test_db.tenant(oid) as session:
        root_id, kid_id = _uuid4(), _uuid4()
        session.add(Task(id=root_id, owner_id=oid, title="Riset kopi", root_id=root_id))
        session.add(
            Task(
                id=kid_id,
                owner_id=oid,
                title="kumpulkan fakta",
                parent_id=root_id,
                root_id=root_id,
            )
        )
        session.add(
            TaskEvent(
                owner_id=oid,
                task_id=kid_id,
                event_type="research.completed",
                payload={"excerpt": "[S1] kopi tubruk", "sources": 1},
            )
        )
    short_root = str(root_id).replace("-", "")[:8]
    await tg.ingest([incoming(tg, 200, f"/task {short_root}")], "TestBot")
    text = (await receipt(tg, 200)).reply_text
    assert "Riset kopi [queued]" in text and "kumpulkan fakta [queued]" in text
    short_kid = str(kid_id).replace("-", "")[:8]
    await tg.ingest([incoming(tg, 201, f"/task {short_kid}")], "TestBot")
    text = (await receipt(tg, 201)).reply_text
    assert "Hasil riset (1 sumber):\n[S1] kopi tubruk" in text
