from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.core.errors import ApplicationError
from jarvis.identity.crypto import issue_material, matches, parse_token
from jarvis.storage.database import Database
from jarvis.storage.models import ApiToken, AuditEvent, ExternalIdentity, PairingCode, User

ALL_SCOPES = frozenset(
    {"profile:read", "tokens:read", "tokens:revoke", "policy:read", "audit:read", "ops:metrics"}
)


@dataclass(frozen=True)
class Principal:
    owner_id: UUID
    token_id: UUID
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise ApplicationError(
                403, "insufficient_scope", "Scope yang diperlukan tidak tersedia."
            )


def audit(
    session: AsyncSession,
    owner_id: UUID,
    action: str,
    resource_id: UUID | None = None,
    actor_id: UUID | None = None,
    request_id: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            owner_id=owner_id,
            actor_id=actor_id,
            action=action,
            resource_id=resource_id,
            request_id=request_id,
            metadata_safe={},
        )
    )


async def issue_api_token(
    session: AsyncSession,
    owner_id: UUID,
    pepper: SecretStr,
    label: str,
    scopes: set[str] | frozenset[str],
    ttl_days: int = 30,
) -> tuple[ApiToken, SecretStr]:
    if not scopes or not scopes.issubset(ALL_SCOPES):
        raise ValueError("Unknown or empty token scopes")
    if not 1 <= ttl_days <= 90 or not 1 <= len(label) <= 80:
        raise ValueError("Token lifetime must be 1..90 days and label 1..80 characters")
    user = await session.get(User, owner_id)
    if user is None or user.status != "active":
        raise ValueError("Active owner not found")
    record_id, raw, hashed = issue_material(owner_id, pepper)
    token = ApiToken(
        id=record_id,
        owner_id=owner_id,
        secret_digest=hashed,
        label=label,
        scopes=sorted(scopes),
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
    )
    session.add(token)
    audit(session, owner_id, "token.created", record_id)
    await session.flush()
    return token, raw


async def authenticate(db: Database, authorization: str | None) -> Principal:
    unauthorized = ApplicationError(401, "invalid_credentials", "Token tidak sah atau kedaluwarsa.")
    try:
        scheme, raw = (authorization or "").split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError
        parts = parse_token(raw)
    except ValueError:
        raise unauthorized from None
    now = datetime.now(UTC)
    # Candidate owner in an opaque token is untrusted until the digest is verified.
    # No user data is returned from this transaction before verification.
    async with db.tenant(parts.owner_id) as session:
        token = await session.get(ApiToken, parts.record_id)
        if (
            token is None
            or token.owner_id != parts.owner_id
            or token.revoked_at is not None
            or token.expires_at <= now
            or not matches(raw, token.secret_digest, db.settings.token_pepper)
        ):
            raise unauthorized
        user = await session.get(User, parts.owner_id)
        if user is None or user.status != "active":
            raise unauthorized
        if token.last_used_at is None or (now - token.last_used_at).total_seconds() > 300:
            token.last_used_at = now
        return Principal(parts.owner_id, token.id, frozenset(token.scopes))


async def create_pairing_code(
    session: AsyncSession,
    owner_id: UUID,
    pepper: SecretStr,
    expected_sender_id: int,
) -> SecretStr:
    if not 0 < expected_sender_id < 2**63:
        raise ValueError("A positive numeric Telegram sender ID is required")
    user = await session.get(User, owner_id)
    if user is None or user.status != "active":
        raise ValueError("Active owner not found")
    record_id, raw, hashed = issue_material(owner_id, pepper, "jvp1")
    session.add(
        PairingCode(
            id=record_id,
            owner_id=owner_id,
            secret_digest=hashed,
            expected_sender_id=expected_sender_id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            attempts=0,
        )
    )
    audit(session, owner_id, "pairing.created", record_id)
    return raw


async def consume_pairing_in_session(
    session: AsyncSession, owner_id: UUID, raw: str, sender_id: int, chat_id: int, pepper: SecretStr
) -> bool:
    """Consume within the caller's transaction, including its update receipt and cursor."""
    try:
        parts = parse_token(raw, "jvp1")
    except ValueError:
        return False
    if parts.owner_id != owner_id or sender_id <= 0 or sender_id != chat_id:
        return False
    code = await session.scalar(
        select(PairingCode).where(PairingCode.id == parts.record_id).with_for_update()
    )
    now = datetime.now(UTC)
    user = await session.get(User, owner_id)
    if (
        code is None
        or code.consumed_at is not None
        or code.expires_at <= now
        or code.attempts >= 5
        or user is None
        or user.status != "active"
    ):
        return False
    code.attempts += 1
    if code.expected_sender_id != sender_id or not matches(raw, code.secret_digest, pepper):
        return False
    existing = await session.scalar(
        select(ExternalIdentity).where(ExternalIdentity.owner_id == owner_id)
    )
    if existing is not None:
        return False
    session.add(
        ExternalIdentity(
            owner_id=owner_id,
            channel="telegram",
            external_user_id=sender_id,
            chat_id=chat_id,
            enabled=True,
        )
    )
    code.consumed_at = now
    audit(session, owner_id, "pairing.consumed", code.id)
    await session.flush()
    return True


async def consume_pairing_code(db: Database, raw: str, sender_id: int, chat_id: int) -> bool:
    """Adapter boundary; caller must verify private-chat provenance first."""
    try:
        parts = parse_token(raw, "jvp1")
    except ValueError:
        return False
    try:
        async with db.tenant(parts.owner_id) as session:
            return await consume_pairing_in_session(
                session, parts.owner_id, raw, sender_id, chat_id, db.settings.token_pepper
            )
    except IntegrityError:
        return False
