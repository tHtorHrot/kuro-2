import asyncio
import hashlib
import logging
import signal
from contextlib import asynccontextmanager

from sqlalchemy import text

from jarvis.core.config import ConfigurationError
from jarvis.interfaces.telegram.worker import LostPollerLock, pause
from jarvis.knowledge.config import store_root
from jarvis.knowledge.repository import KnowledgeRepository
from jarvis.knowledge.services import Embeddings, Parser, VectorIndex, client

log = logging.getLogger(__name__)


@asynccontextmanager
async def knowledge_lock(db, owner):
    key = int.from_bytes(
        hashlib.sha256(f"jarvis:knowledge:{owner}".encode()).digest()[:8], signed=True
    )
    async with db.engine.connect() as connection:
        acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        pid = await connection.scalar(text("SELECT pg_backend_pid()"))
        await connection.commit()
        if not acquired:
            raise ConfigurationError("Another knowledge worker owns this owner")
        mutex = asyncio.Lock()

        async def check():
            async with mutex:
                try:
                    if connection.invalidated or connection.closed:
                        raise LostPollerLock("Knowledge worker lock lost")
                    current = await connection.scalar(text("SELECT pg_backend_pid()"))
                    await connection.commit()
                    if current != pid:
                        raise LostPollerLock("Knowledge worker lock lost")
                except Exception:
                    raise LostPollerLock("Knowledge worker database connection lost") from None

        try:
            yield check
        finally:
            if not connection.invalidated and not connection.closed:
                try:
                    await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    await connection.commit()
                except Exception:
                    await connection.invalidate()


async def run_worker(db, config):
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    if not await db.ready():
        raise ConfigurationError("Database is not ready for knowledge")
    embed = Embeddings()
    repo = KnowledgeRepository(db, config.owner_id, store_root())
    async with knowledge_lock(db, config.owner_id) as check, client() as http:
        index, parser = VectorIndex(http), Parser(http)
        await index.ensure()
        await repo.initialize()

        async def heartbeat():
            while not stop.is_set():
                await check()
                await repo.heartbeat()
                await pause(stop, 10)

        async def work():
            count = 0
            try:
                while not stop.is_set():
                    await check()
                    await repo.prepare_query(embed, index, check)
                    await repo.process(await repo.claim(), parser, embed, index, check)
                    if count % 600 == 0:
                        await repo.prune_orphans()
                    count += 1
                    await pause(stop, 2)
            finally:
                stop.set()

        log.info("knowledge_worker_started")
        async with asyncio.TaskGroup() as group:
            group.create_task(heartbeat())
            group.create_task(work())
        log.info("knowledge_worker_stopped")
