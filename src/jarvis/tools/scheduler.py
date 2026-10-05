"""Bounded scheduler engine for Stage 4 durable actions."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jarvis.tools.execution import ExecutionBroker, ExecutionResult
from jarvis.tools.journal import ActionJournal, ActionJournalError


@dataclass(frozen=True)
class SchedulerPass:
    recovered: int
    processed: int
    results: tuple[ExecutionResult, ...]


class ActionScheduler:
    """Small deterministic scheduler; PostgreSQL remains the queue authority."""

    def __init__(self, journal: ActionJournal, broker: ExecutionBroker):
        self.journal, self.broker = journal, broker

    async def run_pass(self, *, max_actions: int = 10, stop=None) -> SchedulerPass:
        if not 1 <= max_actions <= 100:
            raise ValueError("max_actions must be 1..100")
        await self.journal.heartbeat()
        recovered = await self.journal.recover_expired()
        results: list[ExecutionResult] = []
        for _ in range(max_actions):
            if stop is not None and await stop():
                break
            claimed = await self.journal.claim()
            if claimed is None:
                break
            try:
                results.append(await self.broker.execute_claimed(claimed))
            except ActionJournalError:
                # Cancellation or lease recovery can fence a claim between these awaits.
                # The database status remains authoritative; continue with the next action.
                results.append(ExecutionResult(claimed.id, "fenced", "stale_action_lease"))
        return SchedulerPass(recovered, len(results), tuple(results))

    async def run_forever(
        self,
        *,
        stop: Callable[[], Awaitable[bool]],
        idle_seconds: float = 1.0,
        max_actions_per_pass: int = 10,
    ) -> None:
        if not 0.1 <= idle_seconds <= 60:
            raise ValueError("idle_seconds must be 0.1..60")
        while not await stop():
            result = await self.run_pass(max_actions=max_actions_per_pass, stop=stop)
            if result.processed == 0:
                await asyncio.sleep(idle_seconds)
