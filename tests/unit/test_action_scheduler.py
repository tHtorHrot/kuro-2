from unittest.mock import AsyncMock

import pytest

from jarvis.tools.execution import ExecutionResult
from jarvis.tools.scheduler import ActionScheduler


async def test_scheduler_recovers_then_drains_bounded_actions():
    a, b = object(), object()
    journal = AsyncMock()
    journal.recover_expired.return_value = 2
    journal.claim.side_effect = [a, b, None]
    broker = AsyncMock()
    broker.execute_claimed.side_effect = [
        ExecutionResult("a", "succeeded", "ok"),
        ExecutionResult("b", "failed", "handler_unavailable"),
    ]
    result = await ActionScheduler(journal, broker).run_pass(max_actions=10)
    assert result.recovered == 2
    assert result.processed == 2
    assert [x.outcome for x in result.results] == ["succeeded", "failed"]


async def test_scheduler_honors_max_actions():
    journal = AsyncMock()
    journal.recover_expired.return_value = 0
    journal.claim.side_effect = [object(), object(), object()]
    broker = AsyncMock()
    broker.execute_claimed.return_value = ExecutionResult("x", "succeeded", "ok")
    result = await ActionScheduler(journal, broker).run_pass(max_actions=2)
    assert result.processed == 2
    assert journal.claim.await_count == 2


async def test_scheduler_rejects_unbounded_pass_size():
    scheduler = ActionScheduler(AsyncMock(), AsyncMock())
    with pytest.raises(ValueError, match="max_actions"):
        await scheduler.run_pass(max_actions=101)
