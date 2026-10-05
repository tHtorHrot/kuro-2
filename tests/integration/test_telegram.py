"""Native PostgreSQL boundaries; never uses a real Telegram token or network endpoint."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from jarvis.core.config import ConfigurationError
from jarvis.identity.crypto import parse_token
from jarvis.identity.service import create_pairing_code
from jarvis.interfaces.telegram import repository as repository_module
from jarvis.interfaces.telegram.client import TelegramError
from jarvis.interfaces.telegram.config import TelegramConfig
from jarvis.interfaces.telegram.repository import TelegramRepository
from jarvis.interfaces.telegram.worker import poller_lock
from jarvis.storage.models import (
    ExternalIdentity,
    PairingCode,
    TelegramReceipt,
    TelegramState,
    User,
)

pytestmark = pytest.mark.integration


async def make_repo(db, paired=False):
    owner_id = uuid4()
    config = TelegramConfig(
        owner_id=owner_id,
        sender_id=secrets.randbelow(2**50) + 1,
        bot_id=secrets.randbelow(2**50) + 1,
    )
    async with db.tenant(owner_id) as session:
        session.add(User(id=owner_id, display_name="Telegram test", timezone="Asia/Jakarta"))
        await session.flush()
        if paired:
            session.add(
                ExternalIdentity(
                    owner_id=owner_id,
                    external_user_id=config.sender_id,
                    chat_id=config.sender_id,
                )
            )
    repo = TelegramRepository(db, config)
    await repo.initialize()
    return repo


def incoming(repo, identifier=100, command="/status", sender=None):
    sender = sender or repo.config.sender_id
    return {
        "update_id": identifier,
        "message": {
            "date": int(datetime.now(UTC).timestamp()),
            "text": command,
            "from": {"id": sender, "is_bot": False},
            "chat": {"id": sender, "type": "private"},
        },
    }


async def pair_code(repo):
    async with repo.db.tenant(repo.config.owner_id) as session:
        raw = await create_pairing_code(
            session,
            repo.config.owner_id,
            repo.db.settings.token_pepper,
            repo.config.sender_id,
        )
    return raw.get_secret_value()


async def receipt(repo, identifier=100):
    async with repo.db.tenant(repo.config.owner_id) as session:
        return await session.get(
            TelegramReceipt, (repo.config.owner_id, repo.config.bot_id, identifier)
        )


async def allow_send_now(repo):
    async with repo.db.tenant(repo.config.owner_id) as session:
        (await session.get(TelegramState, repo.config.owner_id)).send_not_before = None


async def test_pairing_receipt_offset_atomic_and_duplicate_serialization(test_db):
    repo = await make_repo(test_db)
    raw = await pair_code(repo)
    batch = [incoming(repo, command="/pair " + raw)]
    await asyncio.gather(repo.ingest(batch, "TestBot"), repo.ingest(batch, "TestBot"))
    assert await repo.offset() == 101
    assert (await receipt(repo)).reply_kind == "paired"
    async with test_db.tenant(repo.config.owner_id) as session:
        assert len((await session.scalars(select(TelegramReceipt))).all()) == 1
        assert len((await session.scalars(select(ExternalIdentity))).all()) == 1
        code = await session.get(PairingCode, parse_token(raw, "jvp1").record_id)
        assert code.consumed_at is not None
        rows = await session.scalar(text("SELECT json_agg(t)::text FROM app.telegram_receipts t"))
        assert raw not in rows and "/pair" not in rows
    await repo.ingest([incoming(repo, identifier=99)], "TestBot")
    assert await repo.offset() == 101


async def test_ingest_rollback_does_not_commit_pair_or_ack(test_db, monkeypatch):
    repo = await make_repo(test_db)
    raw = await pair_code(repo)
    real = repository_module.consume_pairing_in_session

    async def fail_after_pair(*args, **kwargs):
        assert await real(*args, **kwargs)
        raise RuntimeError("simulate transaction failure")

    monkeypatch.setattr(repository_module, "consume_pairing_in_session", fail_after_pair)
    with pytest.raises(RuntimeError):
        await repo.ingest([incoming(repo, command="/pair " + raw)], "TestBot")
    assert await repo.offset() is None and await receipt(repo) is None
    async with test_db.tenant(repo.config.owner_id) as session:
        assert (await session.scalars(select(ExternalIdentity))).all() == []
        code = await session.get(PairingCode, parse_token(raw, "jvp1").record_id)
        assert code.consumed_at is None


async def test_foreign_user_is_ignored_but_cursor_advances(test_db):
    repo = await make_repo(test_db)
    await repo.ingest([incoming(repo, sender=repo.config.sender_id + 1)], "TestBot")
    assert await receipt(repo) is None and await repo.offset() == 101
    await repo.ingest([incoming(repo, identifier=101)], "TestBot")
    assert (await receipt(repo, 101)).reply_kind == "unpaired"


async def test_wrong_pair_attempt_commits_once_despite_update_replay(test_db):
    repo = await make_repo(test_db)
    raw = await pair_code(repo)
    wrong = raw[:-1] + ("A" if raw[-1] != "A" else "B")
    batch = [incoming(repo, command="/pair " + wrong)]
    await repo.ingest(batch, "TestBot")
    await repo.ingest(batch, "TestBot")
    async with test_db.tenant(repo.config.owner_id) as session:
        code = await session.get(PairingCode, parse_token(raw, "jvp1").record_id)
        assert code.attempts == 1 and code.consumed_at is None
    assert (await receipt(repo)).reply_kind == "pair_failed"


@pytest.mark.parametrize("action", ["disable", "suspend"])
async def test_authorization_rechecked_before_sending_existing_queue(test_db, action):
    repo = await make_repo(test_db, paired=True)
    await repo.ingest([incoming(repo)], "TestBot")
    async with test_db.tenant(repo.config.owner_id) as session:
        if action == "disable":
            (await session.scalar(select(ExternalIdentity))).enabled = False
        else:
            (await session.get(User, repo.config.owner_id)).status = "suspended"
    assert await repo.claim() is None
    assert (await receipt(repo)).delivery_status == "blocked"


async def test_delivery_success_ambiguous_and_crash_recovery(test_db):
    repo = await make_repo(test_db, paired=True)
    await repo.ingest([incoming(repo, n) for n in range(100, 103)], "TestBot")
    first = await repo.claim()
    await repo.finish(first, message_id=900)
    assert (await receipt(repo)).delivery_status == "sent"
    await allow_send_now(repo)
    second = await repo.claim()
    await repo.finish(second, error=TelegramError("timeout", ambiguous=True))
    assert (await receipt(repo, 101)).delivery_status == "uncertain"
    await allow_send_now(repo)
    assert (await repo.claim()).update_id == 102
    await repo.initialize()  # startup after process died between claim and result persistence
    assert (await receipt(repo, 102)).delivery_status == "uncertain"
    await allow_send_now(repo)
    assert await repo.claim() is None


async def test_safe_retry_limit_and_global_429_pause_at_final_attempt(test_db):
    repo = await make_repo(test_db, paired=True)
    await repo.ingest([incoming(repo), incoming(repo, 101)], "TestBot")
    for attempt in range(1, 6):
        await allow_send_now(repo)
        async with test_db.tenant(repo.config.owner_id) as session:
            row = await session.get(
                TelegramReceipt,
                (
                    repo.config.owner_id,
                    repo.config.bot_id,
                    100,
                ),
            )
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        delivery = await repo.claim()
        assert delivery.update_id == 100 and delivery.attempt == attempt
        error = TelegramError("rate_limited", retryable=True, retry_after=37)
        await repo.finish(delivery, error=error)
        assert await repo.claim() is None  # global cooldown also blocks the next receipt
    assert (await receipt(repo)).delivery_status == "failed"
    assert (await receipt(repo, 101)).delivery_status == "pending"


async def test_owner_rate_limit_and_reply_age_are_bounded(test_db):
    repo = await make_repo(test_db, paired=True)
    await repo.ingest([incoming(repo, n) for n in range(100, 125)], "TestBot")
    status = await repo.status()
    assert status["deliveries"] == {"ignored": 5, "pending": 20}
    async with test_db.tenant(repo.config.owner_id) as session:
        rows = (await session.scalars(select(TelegramReceipt))).all()
        for row in rows:
            row.created_at = datetime.now(UTC) - timedelta(minutes=11)
    assert await repo.claim() is None
    assert (await repo.status())["deliveries"]["expired"] == 20


async def test_receipt_retention_and_idle_update_id_reset(test_db):
    repo = await make_repo(test_db, paired=True)
    await repo.ingest([incoming(repo)], "TestBot")
    async with test_db.tenant(repo.config.owner_id) as session:
        row = await session.get(
            TelegramReceipt,
            (
                repo.config.owner_id,
                repo.config.bot_id,
                100,
            ),
        )
        row.created_at = datetime.now(UTC) - timedelta(days=3)
        row.delivery_status = "sent"
        state = await session.get(TelegramState, repo.config.owner_id)
        state.last_update_at = datetime.now(UTC) - timedelta(days=8)
    await repo.prune()
    assert await receipt(repo) is None and await repo.offset() is None
    await repo.ingest([incoming(repo, 10)], "TestBot")
    assert await repo.offset() == 11
    assert (await repo.status())["identity_enabled"] is True


async def test_telegram_tables_force_rls_and_cross_owner_writes_fail(test_db):
    a, b = await make_repo(test_db), await make_repo(test_db)
    await b.ingest([incoming(b)], "TestBot")
    async with test_db.tenant(a.config.owner_id) as session:
        assert await session.get(TelegramState, b.config.owner_id) is None
        assert (await session.scalars(select(TelegramReceipt))).all() == []
    with pytest.raises(DBAPIError):
        async with test_db.tenant(a.config.owner_id) as session:
            session.add(
                TelegramReceipt(
                    owner_id=b.config.owner_id,
                    bot_id=b.config.bot_id,
                    update_id=200,
                    chat_id=b.config.sender_id,
                    next_attempt_at=datetime.now(UTC),
                )
            )
    async with test_db.engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM app.telegram_state")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM app.telegram_receipts")) == 0


async def test_only_one_poller_per_bot_and_lock_released_after_exit(test_db):
    bot_id = secrets.randbelow(2**50) + 1
    async with poller_lock(test_db, bot_id) as check:
        await check()
        with pytest.raises(ConfigurationError, match="Another worker"):
            async with poller_lock(test_db, bot_id):
                pytest.fail("second poller must not acquire lock")
    async with poller_lock(test_db, bot_id) as check:
        await check()
