from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="user_status"),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("octet_length(secret_digest) = 32", name="token_digest_length"),
        CheckConstraint("cardinality(scopes) > 0", name="token_scopes_not_empty"),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    secret_digest: Mapped[bytes] = mapped_column(BYTEA)
    label: Mapped[str] = mapped_column(String(80))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PairingCode(Base):
    __tablename__ = "pairing_codes"
    __table_args__ = (
        CheckConstraint("attempts >= 0 AND attempts <= 5", name="pair_attempts_range"),
        CheckConstraint("expected_sender_id > 0", name="pair_positive_sender"),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    secret_digest: Mapped[bytes] = mapped_column(BYTEA)
    expected_sender_id: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("channel", "external_user_id", name="identity_channel_user"),
        UniqueConstraint("owner_id", "channel", name="identity_owner_channel"),
        CheckConstraint("channel = 'telegram'", name="identity_supported_channel"),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="telegram")
    external_user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = ({"schema": "app"},)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    actor_id: Mapped[UUID | None]
    action: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID | None]
    metadata_safe: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramState(Base):
    __tablename__ = "telegram_state"
    __table_args__ = (
        UniqueConstraint("bot_id", name="telegram_bot_owner"),
        UniqueConstraint("owner_id", "bot_id", name="telegram_owner_bot"),
        {"schema": "app"},
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    bot_id: Mapped[int] = mapped_column(BigInteger)
    next_offset: Mapped[int | None] = mapped_column(BigInteger)
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_window_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rate_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramReceipt(Base):
    __tablename__ = "telegram_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "bot_id"], ["app.telegram_state.owner_id", "app.telegram_state.bot_id"]
        ),
        {"schema": "app"},
    )
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    reply_kind: Mapped[str | None] = mapped_column(String(32))
    reply_text: Mapped[str | None] = mapped_column(Text)
    requires_pairing: Mapped[bool] = mapped_column(Boolean, default=True)
    delivery_status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantState(Base):
    __tablename__ = "assistant_state"
    __table_args__ = ({"schema": "app"},)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    frozen: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)
    conversation_id: Mapped[UUID] = mapped_column(default=uuid4)
    config_hash: Mapped[str] = mapped_column(String(64))
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileMemory(Base):
    __tablename__ = "profile_memory"
    __table_args__ = ({"schema": "app"},)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    data_class: Mapped[str] = mapped_column(String(16), default="private")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantRequest(Base):
    __tablename__ = "assistant_requests"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        ForeignKeyConstraint(
            ["owner_id", "bot_id"], ["app.telegram_state.owner_id", "app.telegram_state.bot_id"]
        ),
        ForeignKeyConstraint(
            ["owner_id", "document_id"], ["app.documents.owner_id", "app.documents.id"]
        ),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    bot_id: Mapped[int] = mapped_column(BigInteger)
    source_update_id: Mapped[int] = mapped_column(BigInteger)
    reply_update_id: Mapped[int] = mapped_column(BigInteger)
    conversation_id: Mapped[UUID]
    revision: Mapped[int]
    config_hash: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str | None] = mapped_column(Text)
    messages: Mapped[list[dict] | None] = mapped_column(JSONB(none_as_null=True))
    context_hash: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[UUID | None]
    document_sources: Mapped[list[dict] | None] = mapped_column(JSONB(none_as_null=True))
    data_class: Mapped[str] = mapped_column(String(16), default="private")
    status: Mapped[str] = mapped_column(String(24), default="queued")
    plan: Mapped[dict | None] = mapped_column(JSONB)
    approval_digest: Mapped[bytes | None] = mapped_column(BYTEA)
    approval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["app.assistant_requests.owner_id", "app.assistant_requests.id"],
        ),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    conversation_id: Mapped[UUID]
    request_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "request_id"],
            ["app.assistant_requests.owner_id", "app.assistant_requests.id"],
        ),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    request_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(12))
    model: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16))
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(20, 10))
    actual_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeState(Base):
    __tablename__ = "knowledge_state"
    __table_args__ = ({"schema": "app"},)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("owner_id", "id"), {"schema": "app"})
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(8))
    data_class: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str | None] = mapped_column(String(64))
    pipeline: Mapped[str] = mapped_column(String(64))
    ocr: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    byte_size: Mapped[int] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    error_code: Mapped[str | None] = mapped_column(String(80))
    chunk_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_id", "document_id"], ["app.documents.owner_id", "app.documents.id"]
        ),
        UniqueConstraint("owner_id", "document_id", "ordinal"),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"))
    document_id: Mapped[UUID]
    ordinal: Mapped[int]
    locator: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)


class ToolGrant(Base):
    __tablename__ = "tool_grants"
    __table_args__ = ({"schema": "app"},)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), primary_key=True)
    agent: Mapped[str] = mapped_column(String(80), primary_key=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    enabled: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=1)
    binding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolAction(Base):
    __tablename__ = "tool_actions"
    __table_args__ = (
        UniqueConstraint("owner_id", "id"),
        {"schema": "app"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("app.users.id"), index=True)
    request_id: Mapped[UUID | None]
    agent: Mapped[str] = mapped_column(String(80))
    tool_name: Mapped[str] = mapped_column(String(80))
    effect: Mapped[str] = mapped_column(String(24))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    action_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    authorization_reason: Mapped[str] = mapped_column(String(40))
    approval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    attempts: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_key: Mapped[str | None] = mapped_column(String(200))
    grant_revision: Mapped[int | None]
    spec_fingerprint: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict | list | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
