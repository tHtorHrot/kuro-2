import asyncio
import hashlib
import logging
import signal
from contextlib import asynccontextmanager

from sqlalchemy import text

from jarvis.assistant.graph import AssistantWorkflow
from jarvis.assistant.repository import AssistantRepository
from jarvis.core.config import ConfigurationError
from jarvis.interfaces.telegram.worker import LostPollerLock, pause

log = logging.getLogger(__name__)


@asynccontextmanager
async def assistant_lock(db, owner_id):
    key = int.from_bytes(
        hashlib.sha256(f"jarvis:assistant:{owner_id}".encode()).digest()[:8], signed=True
    )
    async with db.engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        await connection.commit()
        if not acquired:
            raise ConfigurationError("Another assistant worker owns this owner")

        async def check():
            try:
                await connection.execute(text("SELECT 1"))
                await connection.commit()
            except Exception:
                raise LostPollerLock("Assistant worker database connection lost") from None

        try:
            yield check
        finally:
            if not connection.invalidated:
                try:
                    await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    await connection.commit()
                except Exception:
                    await connection.invalidate()


async def run_worker(db, config, router):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    if not await db.ready():
        raise ConfigurationError("Database is not ready for assistant")
    repo = AssistantRepository(db, config)
    async with assistant_lock(db, config.owner_id) as check:
        await repo.initialize()
        workflow = AssistantWorkflow(repo, router, check)
        turns = 0
        log.info("assistant_worker_started")
        while not stop.is_set():
            await check()
            await repo.heartbeat()
            request_id = await repo.next_request()
            if request_id:
                await workflow.invoke(request_id)
            if turns % 150 == 0:
                await repo.prune()
            turns += 1
            await pause(stop, 2)
        log.info("assistant_worker_stopped")
