"""Transactional receipt/cursor/outbox; tenant context is required for every operation."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from jarvis.core.config import ConfigurationError
from jarvis.identity.service import consume_pairing_in_session
from jarvis.interfaces.telegram.client import TelegramError
from jarvis.interfaces.telegram.commands import REPLIES, parse_callback, parse_update
from jarvis.interfaces.telegram.config import TelegramConfig
from jarvis.storage.database import Database
from jarvis.storage.models import (
    CalendarNotification,
    ExternalIdentity,
    TelegramReceipt,
    TelegramState,
    User,
)

MAX_PENDING = 100
MAX_ATTEMPTS = 5
MAX_REPLY_AGE = timedelta(minutes=10)
RECEIPT_RETENTION = timedelta(hours=48)


@dataclass(frozen=True)
class Delivery:
    update_id: int
    chat_id: int
    reply_kind: str
    attempt: int
    text: str | None = field(default=None, repr=False)
    notification_id: UUID | None = None


class TelegramRepository:
    def __init__(self, db: Database, config: TelegramConfig):
        self.db = db
        self.config = config
        self._callback_outbox: list[dict] = []

    def take_callback_outbox(self) -> list[dict]:
        """Ephemeral tap feedback/network edits collected during ingest; best-effort delivery."""
        pending, self._callback_outbox = self._callback_outbox, []
        return pending

    def receipt_filter(self):
        return (
            TelegramReceipt.owner_id == self.config.owner_id,
            TelegramReceipt.bot_id == self.config.bot_id,
        )

    async def state(self, session):
        state = await session.scalar(
            select(TelegramState)
            .where(TelegramState.owner_id == self.config.owner_id)
            .with_for_update()
        )
        if state is None or state.bot_id != self.config.bot_id:
            raise ConfigurationError("Telegram state does not match configured owner/bot")
        return state

    async def identity(self, session):
        return await session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.owner_id == self.config.owner_id,
                ExternalIdentity.channel == "telegram",
            )
        )

    def identity_matches(self, identity: ExternalIdentity | None) -> bool:
        return (
            identity is not None
            and identity.enabled
            and identity.external_user_id == self.config.sender_id
            and identity.chat_id == self.config.sender_id
        )

    async def initialize(self) -> None:
        now = datetime.now(UTC)
        async with self.db.tenant(self.config.owner_id) as session:
            user = await session.get(User, self.config.owner_id)
            if user is None or user.status != "active":
                raise ConfigurationError("Active configured owner not found")
            identity = await self.identity(session)
            if identity and (
                identity.external_user_id != self.config.sender_id
                or identity.chat_id != self.config.sender_id
            ):
                raise ConfigurationError("Existing Telegram identity differs from configuration")
            await session.execute(
                insert(TelegramState)
                .values(
                    owner_id=self.config.owner_id,
                    bot_id=self.config.bot_id,
                    rate_window_at=now,
                    rate_count=0,
                )
                .on_conflict_do_nothing(index_elements=["owner_id"])
            )
            await self.state(session)
            # Called only while holding the exclusive bot advisory lock.
            await session.execute(
                update(TelegramReceipt)
                .where(*self.receipt_filter(), TelegramReceipt.delivery_status == "sending")
                .values(delivery_status="uncertain", reply_text=None)
            )

            await session.execute(
                update(CalendarNotification)
                .where(
                    CalendarNotification.owner_id == self.config.owner_id,
                    CalendarNotification.bot_id == self.config.bot_id,
                    CalendarNotification.delivery_status == "sending",
                )
                .values(delivery_status="uncertain", reply_text=None)
            )

    async def offset(self) -> int | None:
        async with self.db.tenant(self.config.owner_id) as session:
            state = await self.state(session)
            # Telegram may randomize update IDs after at least a week without updates.
            # Re-read the unconfirmed backlog rather than acknowledging a new smaller ID.
            if state.last_update_at and datetime.now(UTC) - state.last_update_at >= timedelta(
                days=6
            ):
                return None
            return state.next_offset

    async def ingest(self, updates: list[dict], bot_username: str) -> None:
        from jarvis.assistant.repository import COMMANDS, handle_command

        now = datetime.now(UTC)
        # Validate before beginning a transaction. Unknown payloads are safely ignored.
        parsed = []
        for row in updates:
            if not isinstance(row, dict) or type(row.get("update_id")) is not int:
                continue
            if isinstance(row.get("callback_query"), dict):
                parsed.append(
                    (
                        row["update_id"],
                        parse_callback(row["update_id"], row["callback_query"], self.config, now),
                    )
                )
            else:
                parsed.append((row["update_id"], parse_update(row, self.config, bot_username, now)))
        async with self.db.tenant(self.config.owner_id) as session:
            state = await self.state(session)
            user = await session.get(User, self.config.owner_id)
            pending = await session.scalar(
                select(func.count())
                .select_from(TelegramReceipt)
                .where(
                    *self.receipt_filter(),
                    TelegramReceipt.delivery_status.in_(["pending", "sending", "waiting"]),
                )
            )
            if now - state.rate_window_at >= timedelta(minutes=1):
                state.rate_window_at, state.rate_count = now, 0
            for update_id, incoming in parsed:
                if incoming is None:
                    continue
                key = (self.config.owner_id, self.config.bot_id, update_id)
                if await session.get(TelegramReceipt, key) is not None:
                    continue
                identity = await self.identity(session)
                blocked = (
                    user is None
                    or user.status != "active"
                    or (identity is not None and not self.identity_matches(identity))
                )
                receipt = TelegramReceipt(
                    owner_id=self.config.owner_id,
                    bot_id=self.config.bot_id,
                    update_id=update_id,
                    chat_id=incoming.chat_id,
                    delivery_status="ignored",
                    next_attempt_at=now,
                    created_at=now,
                    attempts=0,
                    requires_pairing=False,
                )
                session.add(receipt)
                if blocked or state.rate_count >= 20 or pending >= MAX_PENDING:
                    continue
                state.rate_count += 1
                paired = self.identity_matches(identity)
                if incoming.command == "pair":
                    if paired:
                        kind = "already_paired"
                    else:
                        try:
                            async with session.begin_nested():
                                success = await consume_pairing_in_session(
                                    session,
                                    self.config.owner_id,
                                    incoming.pair_code or "",
                                    self.config.sender_id,
                                    incoming.chat_id,
                                    self.db.settings.token_pepper,
                                )
                        except IntegrityError:
                            success = False
                        kind = "paired" if success else "pair_failed"
                elif incoming.command == "privacy":
                    kind = "privacy"
                elif not paired:
                    kind = "unpaired"
                elif incoming.command in ("start", "help"):
                    kind = "help"
                elif incoming.command == "callback":
                    from jarvis.interfaces.telegram.callbacks import handle_callback

                    answer = await handle_callback(session, self.config.owner_id, incoming)
                    self._callback_outbox.append(
                        {
                            "callback_id": incoming.callback_id,
                            "answer": answer,
                            "chat_id": incoming.chat_id,
                            "message_id": incoming.callback_message_id,
                            "message_text": incoming.callback_message_text,
                        }
                    )
                    state.rate_count += 1
                    pending += 1
                    await session.flush()
                    continue
                elif incoming.command in COMMANDS or incoming.command == "chat":
                    await handle_command(
                        session,
                        self.config.owner_id,
                        self.config.bot_id,
                        incoming,
                        receipt,
                        self.db.settings.token_pepper.get_secret_value(),
                    )
                    pending += 1
                    await session.flush()
                    continue
                elif incoming.command == "status":
                    kind = "status"
                else:
                    kind = "unsupported"
                receipt.reply_kind = kind
                receipt.requires_pairing = kind not in ("unpaired", "pair_failed", "privacy")
                receipt.delivery_status = "pending"
                pending += 1
                await session.flush()
            if updates:
                next_offset = max(row["update_id"] for row in updates) + 1
                idle = state.last_update_at and now - state.last_update_at >= timedelta(days=6)
                state.next_offset = (
                    next_offset if idle else max(state.next_offset or 0, next_offset)
                )
                state.last_update_at = now
            state.last_poll_at = now

    async def claim(self) -> Delivery | None:
        now = datetime.now(UTC)
        async with self.db.tenant(self.config.owner_id) as session:
            state = await self.state(session)
            await session.execute(
                update(TelegramReceipt)
                .where(
                    *self.receipt_filter(),
                    TelegramReceipt.delivery_status == "pending",
                    TelegramReceipt.created_at < now - MAX_REPLY_AGE,
                )
                .values(delivery_status="expired", reply_text=None)
            )
            if state.send_not_before and state.send_not_before > now:
                return None
            row = await session.scalar(
                select(TelegramReceipt)
                .where(
                    *self.receipt_filter(),
                    TelegramReceipt.delivery_status == "pending",
                    TelegramReceipt.next_attempt_at <= now,
                )
                .order_by(TelegramReceipt.created_at, TelegramReceipt.update_id)
                .limit(1)
                .with_for_update()
            )
            if row is None:
                from jarvis.interfaces.telegram.notifications import claim_notification

                delivery = await claim_notification(self, session, now)
                if delivery:
                    state.send_not_before = now + timedelta(seconds=1)
                return delivery
            user, identity = (
                await session.get(User, self.config.owner_id),
                await self.identity(session),
            )
            if (
                user is None
                or user.status != "active"
                or row.chat_id != self.config.sender_id
                or (identity is not None and not self.identity_matches(identity))
                or (row.requires_pairing and not self.identity_matches(identity))
            ):
                row.delivery_status = "blocked"
                return None
            if row.attempts >= MAX_ATTEMPTS or row.reply_kind not in REPLIES:
                row.delivery_status = "failed"
                return None
            row.attempts += 1
            row.delivery_status = "sending"
            state.send_not_before = now + timedelta(seconds=1)
            return Delivery(
                row.update_id, row.chat_id, row.reply_kind, row.attempts, row.reply_text
            )

    async def finish(
        self,
        delivery: Delivery,
        *,
        message_id: int | None = None,
        error: TelegramError | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with self.db.tenant(self.config.owner_id) as session:
            state = await self.state(session)
            if delivery.notification_id is not None:
                from jarvis.interfaces.telegram.notifications import finish_notification

                if error is not None and error.retry_after:
                    state.send_not_before = max(
                        state.send_not_before or now, now + timedelta(seconds=error.retry_after)
                    )
                await finish_notification(self, session, delivery, now, message_id, error)
                return
            row = await session.get(
                TelegramReceipt, (self.config.owner_id, self.config.bot_id, delivery.update_id)
            )
            if row is None or row.delivery_status != "sending" or row.attempts != delivery.attempt:
                raise ConfigurationError("Telegram delivery claim was lost")
            # A 429 pauses all sends, even if this particular receipt has no retries left.
            if error is not None and error.retry_after:
                state.send_not_before = max(
                    state.send_not_before or now, now + timedelta(seconds=error.retry_after)
                )
            if error is None and message_id is not None:
                row.delivery_status, row.telegram_message_id = "sent", message_id
            elif error is None or error.ambiguous:
                row.delivery_status = "uncertain"
            elif error.retryable and row.attempts < MAX_ATTEMPTS:
                delay = max(error.retry_after, min(2**row.attempts, 60))
                deadline = now + timedelta(seconds=delay)
                row.next_attempt_at = deadline
                row.delivery_status = (
                    "pending" if deadline < row.created_at + MAX_REPLY_AGE else "expired"
                )
            else:
                row.delivery_status = "failed"
            if row.delivery_status != "pending":
                row.reply_text = None

    async def poll_wait(self) -> int:
        async with self.db.tenant(self.config.owner_id) as session:
            earliest = await session.scalar(
                select(func.min(TelegramReceipt.next_attempt_at)).where(
                    *self.receipt_filter(), TelegramReceipt.delivery_status == "pending"
                )
            )
            notification_due = await session.scalar(
                select(func.min(CalendarNotification.next_attempt_at)).where(
                    CalendarNotification.owner_id == self.config.owner_id,
                    CalendarNotification.bot_id == self.config.bot_id,
                    CalendarNotification.delivery_status == "pending",
                )
            )
            if notification_due is not None:
                earliest = min(earliest, notification_due) if earliest else notification_due
            state = await self.state(session)
            if earliest is None:
                return self.config.poll_seconds
            due = max(earliest, state.send_not_before or earliest)
            return max(
                1, min(self.config.poll_seconds, int((due - datetime.now(UTC)).total_seconds()))
            )

    async def prune(self) -> None:
        async with self.db.tenant(self.config.owner_id) as session:
            # Bound each cleanup statement; never delete state or identity records.
            old = (
                select(TelegramReceipt.update_id)
                .where(
                    *self.receipt_filter(),
                    TelegramReceipt.created_at < datetime.now(UTC) - RECEIPT_RETENTION,
                    TelegramReceipt.delivery_status.not_in(["pending", "sending", "waiting"]),
                )
                .limit(1000)
            )
            await session.execute(
                delete(TelegramReceipt).where(
                    *self.receipt_filter(), TelegramReceipt.update_id.in_(old)
                )
            )

    async def status(self) -> dict:
        async with self.db.tenant(self.config.owner_id) as session:
            state = await session.get(TelegramState, self.config.owner_id)
            identity = await self.identity(session)
            user = await session.get(User, self.config.owner_id)
            rows = (
                await session.execute(
                    select(TelegramReceipt.delivery_status, func.count())
                    .where(*self.receipt_filter())
                    .group_by(TelegramReceipt.delivery_status)
                )
            ).all()
            recent = bool(
                state
                and state.bot_id == self.config.bot_id
                and state.last_poll_at
                and datetime.now(UTC) - state.last_poll_at < timedelta(seconds=120)
            )
            from jarvis.storage.models import AssistantState

            ai = await session.get(AssistantState, self.config.owner_id)
            return {
                "stage": "3",
                "owner_active": bool(user and user.status == "active"),
                "paired": identity is not None,
                "identity_enabled": self.identity_matches(identity),
                "worker_recently_polled": recent,
                "last_poll_at": state.last_poll_at.isoformat()
                if state and state.last_poll_at
                else None,
                "deliveries": dict(rows),
                "llm_active": bool(
                    ai
                    and ai.enabled
                    and not ai.frozen
                    and ai.last_poll_at
                    and datetime.now(UTC) - ai.last_poll_at < timedelta(seconds=120)
                ),
            }
