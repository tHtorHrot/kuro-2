import asyncio
import hashlib
import logging
import signal
from contextlib import asynccontextmanager

from sqlalchemy import text

from jarvis.core.config import ConfigurationError
from jarvis.interfaces.telegram.client import TelegramClient, TelegramError
from jarvis.interfaces.telegram.commands import REPLIES
from jarvis.interfaces.telegram.config import TelegramConfig
from jarvis.interfaces.telegram.repository import TelegramRepository
from jarvis.storage.database import Database

log = logging.getLogger(__name__)


def bot_lock_key(bot_id: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"jarvis:telegram:{bot_id}".encode()).digest()[:8], signed=True
    )


class LostPollerLock(RuntimeError):
    pass


@asynccontextmanager
async def poller_lock(db: Database, bot_id: int):
    # A dedicated session owns the lock for the worker lifetime, including network waits.
    async with db.engine.connect() as connection:
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": bot_lock_key(bot_id)}
        )
        await connection.commit()
        if not acquired:
            raise ConfigurationError("Another worker already owns this Telegram bot")

        async def check():
            try:
                await connection.execute(text("SELECT 1"))
                await connection.commit()
            except Exception:
                # Do not reconnect and continue as if a lost session lock still existed.
                raise LostPollerLock("Telegram poller database connection lost") from None

        try:
            yield check
        finally:
            if not connection.invalidated:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": bot_lock_key(bot_id)}
                    )
                    await connection.commit()
                except Exception:
                    await connection.invalidate()


async def send_one(repo: TelegramRepository, client: TelegramClient) -> bool:
    from jarvis.interfaces.telegram.callbacks import proposal_markup

    delivery = await repo.claim()
    if delivery is None:
        return False
    try:
        markup = proposal_markup(delivery.text or REPLIES[delivery.reply_kind])
        if markup is not None and not await _proposal_still_awaiting(repo, delivery.text):
            markup = None
        message_id = await client.send(
            delivery.chat_id,
            delivery.text or REPLIES[delivery.reply_kind],
            protect_content=repo.config.protect_content,
            reply_markup=markup,
        )
    except TelegramError as exc:
        await repo.finish(delivery, error=exc)
        log.warning("telegram_delivery_failed", extra={"status": exc.kind})
        if exc.fatal:
            raise
    else:
        await repo.finish(delivery, message_id=message_id)
    return True


async def _proposal_still_awaiting(repo: TelegramRepository, text: str | None) -> bool:
    """Only fresh proposals get buttons; stale re-sends stay plain text."""
    from jarvis.interfaces.telegram.callbacks import _TOOLAPPROVE_LINE
    from jarvis.storage.models import ToolAction

    if not isinstance(text, str):
        return False
    match = _TOOLAPPROVE_LINE.search(text)
    if not match:
        return False
    try:
        async with repo.db.tenant(repo.config.owner_id) as session:
            action = await session.get(ToolAction, match[1])
            return (
                action is not None
                and action.owner_id == repo.config.owner_id
                and action.status == "awaiting_approval"
            )
    except Exception:
        return False


async def answer_taps(repo: TelegramRepository, client: TelegramClient) -> None:
    """Best-effort tap feedback; a failed popup never blocks polling or delivery."""
    for tap in repo.take_callback_outbox():
        try:
            await client.answer_callback(tap["callback_id"], tap["answer"])
        except (TelegramError, ValueError):
            continue
        if tap.get("message_text"):
            try:
                await client.strip_buttons(tap["chat_id"], tap["message_id"], tap["message_text"])
            except (TelegramError, ValueError):
                continue


async def pause(stop: asyncio.Event, seconds: float):
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def run_worker(db: Database, config: TelegramConfig, client: TelegramClient) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    if not await db.ready():
        raise ConfigurationError("Database is not ready for the Telegram worker")
    repo = TelegramRepository(db, config)
    async with poller_lock(db, config.bot_id) as check_lock:
        username = await client.identity(config.bot_id)
        await check_lock()
        await repo.initialize()
        log.info("telegram_worker_started")
        failures, turns = 0, 0
        while not stop.is_set():
            await check_lock()
            try:
                await send_one(repo, client)
                await check_lock()
                updates = await client.updates(
                    await repo.offset(), limit=config.updates_per_poll, wait=await repo.poll_wait()
                )
                if stop.is_set():
                    break
                await check_lock()
                await repo.ingest(updates, username)
                await answer_taps(repo, client)
                failures = 0
                turns += 1
                if turns == 1 or turns % 100 == 0:
                    await repo.prune()
            except TelegramError as exc:
                log.warning("telegram_poll_failed", extra={"status": exc.kind})
                if exc.fatal:
                    raise
                failures = min(failures + 1, 6)
                await pause(stop, max(exc.retry_after, min(2**failures, 30)))
            # Prevent a busy loop if the upstream repeatedly returns an empty poll early.
            await pause(stop, 0.2)
        log.info("telegram_worker_stopped")
