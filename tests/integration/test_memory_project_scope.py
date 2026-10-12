"""Stage 6 slice 3: project registry + scoped memory (native PG)."""

import pytest
from sqlalchemy import select
from test_telegram import make_repo

from jarvis.memory.repository import MemoryFact
from jarvis.memory.service import (
    active_project,
    apply_fact,
    delete_project,
    list_projects,
    propose_fact,
    register_project,
    set_active_project,
)
from jarvis.storage.models import ProfileMemory

pytestmark = pytest.mark.integration


async def owner(db):
    return (await make_repo(db)).config.owner_id


async def test_project_registry_and_active_switch(test_db):
    oid = await owner(test_db)
    async with test_db.tenant(oid) as session:
        assert await list_projects(session, oid) == []
        assert await active_project(session, oid) is None
        await register_project(session, oid, "proyek-a")
        await register_project(session, oid, "proyek-b")
        assert await list_projects(session, oid) == ["proyek-a", "proyek-b"]
        await set_active_project(session, oid, "proyek-a")
        assert await active_project(session, oid) == "proyek-a"
        await set_active_project(session, oid, "proyek-b")
        assert await active_project(session, oid) == "proyek-b"


async def test_project_scoped_facts_isolated_by_project(test_db):
    oid = await owner(test_db)
    async with test_db.tenant(oid) as session:
        await register_project(session, oid, "proyek-a")
        await register_project(session, oid, "proyek-b")
        await set_active_project(session, oid, "proyek-a")
    await propose_fact(
        test_db,
        oid,
        MemoryFact(
            key="global-fakta",
            value="semua",
            provenance="user:telegram",
            source="user",
        ),
    )
    async with test_db.tenant(oid) as session:
        await apply_fact(
            session,
            oid,
            MemoryFact(
                key="rahasia-a",
                value="hanya-a",
                provenance="user:telegram",
                source="user",
                project="proyek-a",
            ),
        )
        await apply_fact(
            session,
            oid,
            MemoryFact(
                key="rahasia-b",
                value="hanya-b",
                provenance="user:telegram",
                source="user",
                project="proyek-b",
            ),
        )
    from jarvis.memory.repository import rank_facts
    from jarvis.memory.service import live_condition

    async with test_db.tenant(oid) as session:
        rows = (
            await session.scalars(
                select(ProfileMemory).where(ProfileMemory.owner_id == oid).where(live_condition())
            )
        ).all()
        as_dicts = [
            {
                "key": r.key,
                "value": r.value,
                "kind": r.kind,
                "importance": r.importance,
                "updated_at": r.updated_at,
                "data_class": r.data_class,
                "project": r.project,
                "status": r.status,
                "expires_at": r.expires_at,
            }
            for r in rows
        ]
    picked_a = {f["key"] for f in rank_facts(as_dicts, budget_chars=10**9, project="proyek-a")}
    picked_b = {f["key"] for f in rank_facts(as_dicts, budget_chars=10**9, project="proyek-b")}
    picked_none = {f["key"] for f in rank_facts(as_dicts, budget_chars=10**9, project=None)}
    assert "global-fakta" in picked_a and "rahasia-a" in picked_a
    assert "rahasia-b" not in picked_a
    assert "global-fakta" in picked_b and "rahasia-b" in picked_b
    assert "rahasia-a" not in picked_b
    assert picked_none == {"global-fakta"}


async def test_delete_project_guarded_until_empty_and_inactive(test_db):
    oid = await owner(test_db)
    async with test_db.tenant(oid) as session:
        await register_project(session, oid, "proyek-a")
        await set_active_project(session, oid, "proyek-a")
        await apply_fact(
            session,
            oid,
            MemoryFact(
                key="k",
                value="v",
                provenance="user:telegram",
                source="user",
                project="proyek-a",
            ),
        )
        with pytest.raises(ValueError, match="project_is_active"):
            await delete_project(session, oid, "proyek-a")
        await set_active_project(session, oid, None)
        with pytest.raises(ValueError, match="project_has_facts"):
            await delete_project(session, oid, "proyek-a")
