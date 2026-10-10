"""Memory service — learning hanya dari validated outputs.

Jangan membuat semua transcript masuk memory otomatis (Bagian 7.1).
Memory hasil model diberi label inference sampai diverifikasi.
Precedence: user eksplisit > validated > inference; konflik diam-diam
tidak pernah menimpa nilai otoritatif. Forget adalah tombstone, bukan hapus.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from jarvis.memory.repository import MemoryFact, default_expiry, validate_fact

_PRECEDENCE = {"user": 3, "validated": 2, "inference": 1}


def live_condition():
    """Only active, unexpired facts may enter prompts, listings, or restores."""
    from jarvis.storage.models import ProfileMemory

    now = datetime.now(UTC)
    return (ProfileMemory.status == "active") & (
        ProfileMemory.expires_at.is_(None) | (ProfileMemory.expires_at > now)
    )


async def propose_fact(db, owner: UUID, fact: MemoryFact) -> None:
    validate_fact(fact)
    async with db.tenant(owner) as session:
        await apply_fact(session, owner, fact)


async def apply_fact(session, owner: UUID, fact: MemoryFact) -> str:
    """Core upsert on a caller-owned session. Returns inserted|kept|superseded."""
    from jarvis.storage.models import ProfileMemory

    expires = fact.expires_at
    if expires is None and fact.source != "user":
        expires = default_expiry()
    existing = await session.get(ProfileMemory, (owner, fact.key))
    if existing is None:
        session.add(
            ProfileMemory(
                owner_id=owner,
                key=fact.key,
                value=fact.value,
                data_class="private",
                kind=fact.kind,
                provenance=fact.provenance,
                expires_at=expires,
                status="active",
                importance=fact.importance,
            )
        )
        return "inserted"
    if _is_gone(existing):
        # Re-learn after forget/expiry overwrites in place; the PK row persists.
        existing.value = fact.value
        existing.kind = fact.kind
        existing.provenance = fact.provenance
        existing.expires_at = expires
        existing.status = "active"
        existing.importance = fact.importance
        existing.updated_at = datetime.now(UTC)
        return "inserted"
    if existing.value == fact.value:
        return "kept"
    if _PRECEDENCE[fact.source] <= _PRECEDENCE[_source_of(existing)]:
        # Tandai konflik di audit, pertahankan authoritative value.
        from jarvis.identity.service import audit

        audit(
            session,
            owner,
            "memory.conflict_kept_user_value",
            None,
            request_id=fact.provenance[:36],
        )
        return "kept"
    existing.value = fact.value
    existing.kind = fact.kind
    existing.provenance = fact.provenance
    existing.expires_at = expires
    existing.status = "active"
    existing.importance = fact.importance
    existing.updated_at = datetime.now(UTC)
    from jarvis.identity.service import audit

    audit(session, owner, "memory.superseded", None, request_id=fact.provenance[:36])
    return "superseded"


def _is_gone(row) -> bool:
    if row.status == "deleted":
        return True
    return row.expires_at is not None and row.expires_at <= datetime.now(UTC)


def _source_of(row) -> str:
    if not row.provenance or row.provenance == "user" or row.provenance.startswith("user:"):
        return "user"
    if row.provenance.startswith("task-intake:"):
        return "validated"
    return "inference"


async def forget_fact(db, owner: UUID, key: str) -> bool:
    """Tombstone; restore tidak menghidupkan kembali tanpa proses yang benar."""
    async with db.tenant(owner) as session:
        return await apply_forget(session, owner, key)


async def apply_forget(session, owner: UUID, key: str) -> bool:
    from jarvis.identity.service import audit
    from jarvis.storage.models import ProfileMemory

    existing = await session.get(ProfileMemory, (owner, key))
    if existing is None or existing.status == "deleted":
        return False
    existing.status = "deleted"
    existing.updated_at = datetime.now(UTC)
    audit(session, owner, "memory.forgotten", None)
    return True


async def validated_task_summary(
    db, owner: UUID, *, task_id: UUID, summary: str, provenance: str
) -> None:
    """Simpan ringkasan task berprovenance setelah hasil tervalidasi."""
    if not summary or len(summary) > 2000:
        raise ValueError("summary_invalid")
    await propose_fact(
        db,
        owner,
        MemoryFact(
            key=f"task:{task_id.hex[:12]}",
            value=summary,
            provenance=provenance,
            kind="task",
            source="validated",
        ),
    )
