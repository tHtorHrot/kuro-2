"""Persisted operator grants, checked again at the dispatch transaction."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from jarvis.identity.service import audit
from jarvis.storage.models import ToolGrant, User


async def set_grant(
    db, owner, agent: str, scopes: frozenset[str], *, enabled: bool, binding_fingerprint=None
):
    """Trusted operator entry point; not exposed to planners or model tools."""
    if not agent or len(agent) > 80 or any(not s or len(s) > 80 for s in scopes):
        raise ValueError("invalid_tool_grant")
    if enabled and not scopes:
        raise ValueError("empty_tool_grant")
    async with db.tenant(owner) as session:
        user = await session.scalar(select(User).where(User.id == owner).with_for_update())
        if user is None or user.status != "active":
            raise ValueError("active_owner_required")
        await session.execute(
            insert(ToolGrant)
            .values(owner_id=owner, agent=agent, scopes=[], enabled=False)
            .on_conflict_do_nothing()
        )
        grant = await session.get(ToolGrant, (owner, agent), with_for_update=True)
        grant.scopes, grant.enabled = sorted(scopes), enabled
        grant.binding_fingerprint = binding_fingerprint
        grant.revision += 1
        from jarvis.tools.journal import now_utc

        grant.updated_at = now_utc()
        audit(session, owner, "tool_grant.changed", None)
        return {
            "agent": agent,
            "enabled": enabled,
            "scopes": sorted(scopes),
            "revision": grant.revision,
        }
