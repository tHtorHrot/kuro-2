"""Stage 6 slice 1: typed memory, precedence, tombstones, expiry (native PG)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_telegram import make_repo

from jarvis.memory.repository import MemoryFact
from jarvis.memory.retention import prune_memory
from jarvis.memory.service import (
    apply_forget,
    forget_fact,
    live_condition,
    propose_fact,
)
from jarvis.storage.models import ProfileMemory

pytestmark = pytest.mark.integration


async def owner(db):
    return (await make_repo(db)).config.owner_id


async def test_kinds_provenance_and_expiry_persist(test_db):
    oid = await owner(test_db)
    await propose_fact(
        test_db,
        oid,
        MemoryFact(
            key="kota",
            value="Jakarta",
            provenance="user:telegram",
            kind="profile",
            source="user",
        ),
    )
    await propose_fact(
        test_db,
        oid,
        MemoryFact(
            key="suka_pagi",
            value="kopi tubruk",
            provenance="user:telegram",
            kind="preference",
            source="user",
        ),
    )
    async with test_db.tenant(oid) as session:
        rows = (
            await session.scalars(
                select(ProfileMemory)
                .where(ProfileMemory.owner_id == oid)
                .where(live_condition())
                .order_by(ProfileMemory.key)
            )
        ).all()
    assert [(r.key, r.kind, r.status) for r in rows] == [
        ("kota", "profile", "active"),
        ("suka_pagi", "preference", "active"),
    ]
    assert all(r.provenance == "user:telegram" and r.expires_at is None for r in rows)


async def test_user_supersedes_inference_but_not_reverse(test_db):
    oid = await owner(test_db)
    await propose_fact(
        test_db,
        oid,
        MemoryFact(key="k", value="tebakan", provenance="model:x", source="inference"),
    )
    await propose_fact(
        test_db,
        oid,
        MemoryFact(key="k", value="pastinya", provenance="user:telegram", source="user"),
    )
    await propose_fact(
        test_db,
        oid,
        MemoryFact(key="k", value="tebakan-lagi", provenance="model:y", source="inference"),
    )
    async with test_db.tenant(oid) as session:
        row = await session.get(ProfileMemory, (oid, "k"))
    assert row.value == "pastinya" and row.status == "active"


async def test_forget_is_tombstone_not_hard_delete(test_db):
    oid = await owner(test_db)
    await propose_fact(
        test_db,
        oid,
        MemoryFact(key="k", value="v", provenance="user:telegram", source="user"),
    )
    assert await forget_fact(test_db, oid, "k") is True
    assert await forget_fact(test_db, oid, "k") is False
    assert await forget_fact(test_db, oid, "missing") is False
    async with test_db.tenant(oid) as session:
        row = await session.get(ProfileMemory, (oid, "k"))
        assert row.status == "deleted"
        assert (
            await session.scalars(
                select(ProfileMemory).where(ProfileMemory.owner_id == oid).where(live_condition())
            )
        ).all() == []
    # Re-learning after forget starts fresh instead of resurrecting.
    await propose_fact(
        test_db, oid, MemoryFact(key="k", value="baru", provenance="user:telegram", source="user")
    )
    async with test_db.tenant(oid) as session:
        row = await session.get(ProfileMemory, (oid, "k"))
    assert row.value == "baru" and row.status == "active"


async def test_expired_facts_stay_out_of_live_reads(test_db):
    oid = await owner(test_db)
    await propose_fact(
        test_db,
        oid,
        MemoryFact(
            key="lama",
            value="basi",
            provenance="model:x",
            source="inference",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        ),
    )
    async with test_db.tenant(oid) as session:
        assert (
            await session.scalars(
                select(ProfileMemory).where(ProfileMemory.owner_id == oid).where(live_condition())
            )
        ).all() == []
        assert (await session.get(ProfileMemory, (oid, "lama"))).status == "active"


async def test_retention_prunes_only_dead_facts(test_db):
    oid = await owner(test_db)
    await propose_fact(
        test_db, oid, MemoryFact(key="hidup", value="v", provenance="user:telegram", source="user")
    )
    await propose_fact(
        test_db, oid, MemoryFact(key="mati", value="v", provenance="user:telegram", source="user")
    )
    async with test_db.tenant(oid) as session:
        await apply_forget(session, oid, "mati")
        row = await session.get(ProfileMemory, (oid, "mati"))
        row.updated_at = datetime.now(UTC) - timedelta(days=60)
    result = await prune_memory(test_db, oid)
    assert result == {"forgotten_hard_deleted": 1, "expired_hard_deleted": 0}
    async with test_db.tenant(oid) as session:
        assert await session.get(ProfileMemory, (oid, "hidup")) is not None
        assert await session.get(ProfileMemory, (oid, "mati")) is None
