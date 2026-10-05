import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from jarvis.core.errors import ApplicationError
from jarvis.identity.crypto import parse_token
from jarvis.identity.service import (
    ALL_SCOPES,
    authenticate,
    create_pairing_code,
    issue_api_token,
)
from jarvis.identity.service import consume_pairing_code as consume
from jarvis.main import create_app
from jarvis.storage.models import ApiToken, AuditEvent, ExternalIdentity, PairingCode, User

pytestmark = pytest.mark.integration


async def owner(db, scopes=ALL_SCOPES):
    owner_id = uuid4()
    async with db.tenant(owner_id) as session:
        session.add(User(id=owner_id, display_name="Test owner", timezone="Asia/Jakarta"))
        await session.flush()
        token, raw = await issue_api_token(
            session, owner_id, db.settings.token_pepper, "test", scopes
        )
    return owner_id, token.id, raw.get_secret_value()


async def new_pair(db, owner_id, sender):
    async with db.tenant(owner_id) as session:
        raw = await create_pairing_code(session, owner_id, db.settings.token_pepper, sender)
    return raw.get_secret_value()


async def test_rls_reads_writes_and_connection_reuse(test_db):
    a, _, _ = await owner(test_db)
    b, _, _ = await owner(test_db)
    async with test_db.tenant(a) as session:
        users = (await session.scalars(select(User))).all()
        assert [row.id for row in users] == [a]
        assert await session.get(User, b) is None
        assert {row.owner_id for row in (await session.scalars(select(ApiToken))).all()} == {a}
    async with test_db.tenant(b) as session:
        assert {row.id for row in (await session.scalars(select(User))).all()} == {b}
    async with test_db.engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM app.users")) == 0
        assert await connection.scalar(text("SELECT app.current_owner_id()")) is None
    with pytest.raises(DBAPIError):
        async with test_db.tenant(a) as session:
            session.add(User(id=uuid4(), display_name="cross-owner", timezone="Asia/Jakarta"))
            await session.flush()


async def test_rls_blocks_cross_owner_update_and_schema_changes(test_db):
    a, _, _ = await owner(test_db)
    b, _, _ = await owner(test_db)
    async with test_db.tenant(a) as session:
        result = await session.execute(
            text("UPDATE app.users SET display_name='bad' WHERE id=:b"), {"b": b}
        )
        assert result.rowcount == 0
    with pytest.raises(DBAPIError):
        async with test_db.tenant(a) as session:
            await session.execute(text("CREATE TABLE app.forbidden (id integer)"))
    with pytest.raises(DBAPIError):
        async with test_db.tenant(a) as session:
            await session.execute(text("SET ROLE jarvis_migrator"))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.audit_events SET action='forged'",
        "DELETE FROM app.audit_events",
    ],
)
async def test_audit_is_append_only_for_runtime_role(test_db, statement):
    owner_id, _, _ = await owner(test_db)
    with pytest.raises(DBAPIError):
        async with test_db.tenant(owner_id) as session:
            await session.execute(text(statement))


async def test_auth_digest_revocation_expiry_and_suspension(test_db):
    owner_id, token_id, raw = await owner(test_db)
    assert (await authenticate(test_db, f"Bearer {raw}")).owner_id == owner_id
    for wrong in (
        raw[:-1] + ("A" if raw[-1] != "A" else "B"),
        raw.replace(str(owner_id), str(uuid4())),
    ):
        with pytest.raises(ApplicationError) as error:
            await authenticate(test_db, f"Bearer {wrong}")
        assert error.value.status == 401
    async with test_db.tenant(owner_id) as session:
        token = await session.get(ApiToken, token_id)
        assert token.last_used_at is not None
        assert raw.encode() != token.secret_digest
        token.revoked_at = datetime.now(UTC)
    with pytest.raises(ApplicationError):
        await authenticate(test_db, f"Bearer {raw}")
    async with test_db.tenant(owner_id) as session:
        token = await session.get(ApiToken, token_id)
        token.revoked_at = None
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ApplicationError):
        await authenticate(test_db, f"Bearer {raw}")
    async with test_db.tenant(owner_id) as session:
        token = await session.get(ApiToken, token_id)
        token.expires_at = datetime.now(UTC) + timedelta(days=1)
        (await session.get(User, owner_id)).status = "suspended"
    with pytest.raises(ApplicationError):
        await authenticate(test_db, f"Bearer {raw}")


async def test_http_owner_isolation_revoke_and_audit(test_db):
    a, token_a, raw_a = await owner(test_db)
    b, token_b, _ = await owner(test_db)
    app = create_app(test_db.settings, test_db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {raw_a}"},
    ) as client:
        assert (await client.get("/api/v1/me")).json()["id"] == str(a)
        tokens = (await client.get("/api/v1/auth/tokens")).json()
        assert [row["id"] for row in tokens] == [str(token_a)]
        assert "secret_digest" not in tokens[0]
        assert (await client.post(f"/api/v1/auth/tokens/{token_b}/revoke")).status_code == 404
        response = await client.post(f"/api/v1/auth/tokens/{token_a}/revoke")
        assert response.status_code == 204
        assert (await client.get("/api/v1/me")).status_code == 401
    async with test_db.tenant(a) as session:
        events = (await session.scalars(select(AuditEvent))).all()
        revoked = [e for e in events if e.action == "token.revoked"]
        assert len(revoked) == 1 and revoked[0].actor_id == token_a
        assert all(e.metadata_safe == {} for e in events)
    async with test_db.tenant(b) as session:
        assert (await session.get(ApiToken, token_b)).revoked_at is None


async def test_read_only_scope_cannot_revoke(test_db):
    _, token_id, raw = await owner(test_db, frozenset({"profile:read"}))
    async with AsyncClient(
        transport=ASGITransport(app=create_app(test_db.settings, test_db)),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {raw}"},
    ) as client:
        assert (await client.get("/api/v1/me")).status_code == 200
        assert (await client.post(f"/api/v1/auth/tokens/{token_id}/revoke")).status_code == 403
        assert (await client.get("/metrics")).status_code == 403


async def test_pairing_sender_binding_atomic_consumption_and_no_replay(test_db):
    owner_id, _, _ = await owner(test_db)
    sender = secrets.randbelow(2**52) + 1
    raw = await new_pair(test_db, owner_id, sender)
    assert not await consume(test_db, raw, sender, -100)
    assert not await consume(test_db, raw, sender + 1, sender + 1)
    async with test_db.tenant(owner_id) as session:
        assert (await session.get(PairingCode, parse_token(raw, "jvp1").record_id)).attempts == 1
    results = await asyncio.gather(
        consume(test_db, raw, sender, sender), consume(test_db, raw, sender, sender)
    )
    assert sorted(results) == [False, True]
    assert not await consume(test_db, raw, sender, sender)
    async with test_db.tenant(owner_id) as session:
        identities = (await session.scalars(select(ExternalIdentity))).all()
        assert len(identities) == 1 and identities[0].external_user_id == sender


async def test_pairing_failed_attempts_persist_and_expired_code_fails(test_db):
    owner_id, _, _ = await owner(test_db)
    sender = secrets.randbelow(2**52) + 1
    raw = await new_pair(test_db, owner_id, sender)
    wrong = raw[:-1] + ("A" if raw[-1] != "A" else "B")
    for _ in range(5):
        assert not await consume(test_db, wrong, sender, sender)
    assert not await consume(test_db, raw, sender, sender)
    async with test_db.tenant(owner_id) as session:
        assert (await session.get(PairingCode, parse_token(raw, "jvp1").record_id)).attempts == 5
    second = await new_pair(test_db, owner_id, sender)
    async with test_db.tenant(owner_id) as session:
        code = await session.get(PairingCode, parse_token(second, "jvp1").record_id)
        code.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert not await consume(test_db, second, sender, sender)


async def test_same_telegram_identity_cannot_belong_to_two_owners(test_db):
    a, _, _ = await owner(test_db)
    b, _, _ = await owner(test_db)
    sender = secrets.randbelow(2**52) + 1
    assert await consume(test_db, await new_pair(test_db, a, sender), sender, sender)
    assert not await consume(test_db, await new_pair(test_db, b, sender), sender, sender)
    async with test_db.tenant(b) as session:
        assert (await session.scalars(select(ExternalIdentity))).all() == []


async def test_transaction_rollback_does_not_leak_tenant(test_db):
    owner_id, _, _ = await owner(test_db)
    with pytest.raises(RuntimeError):
        async with test_db.tenant(owner_id) as session:
            (await session.get(User, owner_id)).display_name = "rollback-me"
            await session.flush()
            raise RuntimeError("Intentional rollback")
    async with test_db.tenant(owner_id) as session:
        assert (await session.get(User, owner_id)).display_name == "Test owner"
    async with test_db.engine.connect() as connection:
        assert await connection.scalar(text("SELECT app.current_owner_id()")) is None
