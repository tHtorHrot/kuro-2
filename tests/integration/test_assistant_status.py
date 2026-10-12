"""Stage 2B fix: status exposes ledger split + recent terminals (native PG)."""

from decimal import Decimal

import pytest
from test_assistant import fixture, offer
from test_telegram import incoming

from jarvis.assistant.router import RouterError

pytestmark = pytest.mark.integration


async def test_status_shows_held_vs_actual_and_recent_terminals(test_db):
    tg, repo = await fixture(test_db, premium=True)
    row, p, code = await offer(tg, repo)
    await tg.ingest([incoming(tg, 101, "/approve " + code)], "TestBot")
    call = await repo.dispatch(row.id, p)
    await repo.finish(row.id, call, None, RouterError("timeout", uncertain=True))
    status = await repo.status()
    assert status["month_spent_or_held_usd"] == p["reserve_usd"]
    assert Decimal(status["month_held_usd"]) == Decimal(p["reserve_usd"])
    assert Decimal(status["month_actual_usd"]) == 0
    assert status["unreconciled_calls"] == 1
    assert status["calls"].get("uncertain") == 1
    assert status["daily_free_used"] == 0
    assert status["daily_free_limit"] == repo.config.daily_free_calls
    assert {"status", "finished_at"} <= set(status["recent_terminal"][0])
    assert all("prompt" not in item for item in status["recent_terminal"])
