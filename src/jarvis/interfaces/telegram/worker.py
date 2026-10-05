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
    delivery = await repo.claim()
    if delivery is None:
        return False
    try:
        message_id = await client.send(
            delivery.chat_id, delivery.text or REPLIES[delivery.reply_kind]
        )
    except TelegramError as exc:
        await repo.finish(delivery, error=exc)
        log.warning("telegram_delivery_failed", extra={"status": exc.kind})
        if exc.fatal:
            raise
    else:
        await repo.finish(delivery, message_id=message_id)
    return True


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
