"""Native PostgreSQL tests: no real Telegram/model calls and no actual charges."""

import asyncio
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_telegram import incoming, make_repo, receipt

from jarvis.assistant.config import AssistantConfig, Route
from jarvis.assistant.policy import PolicyError
from jarvis.assistant.repository import AssistantRepository, now_utc, owner_state
from jarvis.assistant.router import Completion, RouterError, endpoint_plan
from jarvis.assistant.worker import assistant_lock
from jarvis.core.config import ConfigurationError
from jarvis.storage.models import (
    AssistantRequest,
    AssistantState,
    ConversationMessage,
    ExternalIdentity,
    LLMCall,
    ProfileMemory,
    TelegramReceipt,
)

pytestmark = pytest.mark.integration


async def fixture(db, *, premium=False):
    tg = await make_repo(db, paired=True)
    cfg = AssistantConfig(
        owner_id=tg.config.owner_id,
        account_privacy_confirmed=True,
        free_route=Route(model="qwen/test:free", provider="example"),
        premium_route=Route(model="qwen/paid", provider="example") if premium else None,
        monthly_budget_usd="0.01" if premium else "0",
        per_call_budget_usd="0.005" if premium else "0",
    )
    repo = AssistantRepository(db, cfg)
    await repo.initialize()
    async with db.tenant(repo.owner) as session:
        (await owner_state(session, repo.owner)).enabled = True
    return tg, repo


def plan(repo, kind="free"):
    cfg = repo.config
    route = cfg.free_route if kind == "free" else cfg.premium_route
    endpoint = {
        "model_id": route.model,
        "tag": route.provider,
        "provider_name": "Example",
        "status": 0,
        "context_length": 32768,
        "max_completion_tokens": 4096,
        "supported_parameters": ["max_tokens"],
        "pricing": {"prompt": "0.0000001" if kind == "premium" else "0", "completion": "0"},
    }
    return endpoint_plan(endpoint, route, cfg, kind)


async def ask(tg, repo, number=100):
    await tg.ingest([incoming(tg, number, "/ask Halo Jarvis")], "TestBot")
    request_id = await repo.next_request()
    assert request_id is not None
    row = await repo.prepare(request_id)
    assert row is not None
    return row


async def offer(tg, repo, number=100):
    row = await ask(tg, repo, number)
    p = plan(repo, "premium")
    assert await repo.offer(row.id, p)
    code = re.search(r"/approve ([a-f0-9]+)", (await receipt(tg, number)).reply_text)[1]
    return row, p, code


async def test_free_answer_memory_profile_and_clear(test_db):
    tg, repo = await fixture(test_db)
    await tg.ingest([incoming(tg, 99, "/remember nama Pemilik")], "TestBot")
    row = await ask(tg, repo)
    assert "Pemilik" in str(row.messages)
    call = await repo.dispatch(row.id, plan(repo))
    await repo.finish(row.id, call, Completion("Halo, Pemilik", Decimal(0), 200, 4), None)
    assert (await receipt(tg)).reply_text == "Halo, Pemilik"
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 2
    await tg.ingest([incoming(tg, 101, "/clear")], "TestBot")
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 0
        assert (await session.get(AssistantRequest, row.id)).messages is None
        assert (await session.get(AssistantRequest, row.id)).prompt is None
        assert await session.get(ProfileMemory, (repo.owner, "nama")) is not None
        assert await session.get(LLMCall, call) is not None


async def test_owner_duplicate_update_single_request_and_busy_reply(test_db):
    tg, repo = await fixture(test_db)
    batch = [incoming(tg, 100, "/ask Halo Jarvis")]
    await asyncio.gather(tg.ingest(batch, "TestBot"), tg.ingest(batch, "TestBot"))
    await tg.ingest([incoming(tg, 101, "/ask Kedua")], "TestBot")
    assert "Masih ada" in (await receipt(tg, 101)).reply_text
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(AssistantRequest)) == 1


@pytest.mark.parametrize(
    "prompt", ["Halo KURO, balas sistem aktif.", "andi@example.com ini siapa?"]
)
async def test_natural_chat_reaches_existing_queue_and_outbox_once(test_db, prompt):
    tg, repo = await fixture(test_db)
    batch = [incoming(tg, 100, prompt)]
    await asyncio.gather(tg.ingest(batch, "TestBot"), tg.ingest(batch, "TestBot"))
    request_id = await repo.next_request()
    assert request_id is not None
    row = await repo.prepare(request_id)
    assert row.prompt == prompt
    assert row.messages[-1] == {"role": "user", "content": prompt}
    assert (await receipt(tg)).delivery_status == "waiting"
    call_id = await repo.dispatch(request_id, plan(repo))
    await repo.finish(request_id, call_id, Completion("Sistem aktif.", Decimal(0), 10, 3), None)
    assert (await receipt(tg)).reply_text == "Sistem aktif."
    await tg.ingest(batch, "TestBot")
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(AssistantRequest)) == 1
        assert await session.scalar(select(func.count()).select_from(LLMCall)) == 1


async def test_unpaired_natural_chat_is_not_persisted_as_assistant_prompt(test_db):
    tg = await make_repo(test_db, paired=False)
    await tg.ingest([incoming(tg, 100, "PRIVATE-UNPAIRED-TEXT")], "TestBot")
    assert (await receipt(tg)).reply_kind == "unpaired"
    async with test_db.tenant(tg.config.owner_id) as session:
        assert await session.scalar(select(func.count()).select_from(AssistantRequest)) == 0


@pytest.mark.parametrize("prompt", ["password=PRIVATE", "x" * 3001, "/chat Halo"])
async def test_natural_chat_does_not_bypass_existing_safety_or_command_gates(test_db, prompt):
    tg, repo = await fixture(test_db)
    await tg.ingest([incoming(tg, 100, prompt)], "TestBot")
    assert await repo.next_request() is None
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(AssistantRequest)) == 0


async def test_natural_chat_does_not_bypass_premium_consent(test_db):
    tg, repo = await fixture(test_db, premium=True)
    await tg.ingest([incoming(tg, 100, "Halo KURO")], "TestBot")
    request_id = await repo.next_request()
    await repo.prepare(request_id)
    premium_plan = plan(repo, "premium")
    assert await repo.offer(request_id, premium_plan)
    assert await repo.dispatch(request_id, premium_plan) is None
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(LLMCall)) == 0


async def test_consent_once_across_concurrent_replayed_approvals(test_db):
    tg, repo = await fixture(test_db, premium=True)
    row, p, code = await offer(tg, repo)
    commands = [incoming(tg, n, "/approve " + code) for n in (101, 102)]
    await asyncio.gather(*(tg.ingest([c], "TestBot") for c in commands))
    async with test_db.tenant(repo.owner) as session:
        req = await session.get(AssistantRequest, row.id)
        assert req.approval_digest is None and req.status == "approved"
    results = await asyncio.gather(repo.dispatch(row.id, p), repo.dispatch(row.id, p))
    assert sum(x is not None for x in results) == 1
    await repo.finish(
        row.id, next(x for x in results if x), None, RouterError("timeout", uncertain=True)
    )
    await tg.ingest([incoming(tg, 103, "/approve " + code)], "TestBot")
    assert "Tidak ada persetujuan" in (await receipt(tg, 103)).reply_text
    assert Decimal((await repo.status())["month_spent_or_held_usd"]) == Decimal(p["reserve_usd"])


async def test_premium_without_consent_price_change_and_expiry_are_blocked(test_db):
    tg, repo = await fixture(test_db, premium=True)
    row, p, code = await offer(tg, repo)
    assert await repo.dispatch(row.id, p) is None
    await tg.ingest([incoming(tg, 101, "/approve " + code)], "TestBot")
    with pytest.raises(PolicyError, match="fresh_consent"):
        await repo.dispatch(row.id, {**p, "provider": "different"})
    async with test_db.tenant(repo.owner) as session:
        (await session.get(AssistantRequest, row.id)).approval_expires_at = now_utc() - timedelta(
            seconds=1
        )
    with pytest.raises(PolicyError, match="fresh_consent"):
        await repo.dispatch(row.id, p)
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(LLMCall)) == 0


async def test_wrong_code_five_times_invalidates_authorization(test_db):
    tg, repo = await fixture(test_db, premium=True)
    row, _, code = await offer(tg, repo)
    for n in range(101, 106):
        await tg.ingest([incoming(tg, n, "/approve wrong")], "TestBot")
    await tg.ingest([incoming(tg, 106, "/approve " + code)], "TestBot")
    async with test_db.tenant(repo.owner) as session:
        req = await session.get(AssistantRequest, row.id)
        assert req.status == "cancelled" and req.approval_attempts == 5


async def test_budget_rechecked_at_dispatch_not_only_offer(test_db):
    tg, repo = await fixture(test_db, premium=True)
    old, p, code = await offer(tg, repo)
    await tg.ingest([incoming(tg, 101, "/approve " + code)], "TestBot")
    call = await repo.dispatch(old.id, p)
    await repo.finish(old.id, call, None, RouterError("timeout", uncertain=True))
    row, p, code = await offer(tg, repo, 102)
    await tg.ingest([incoming(tg, 103, "/approve " + code)], "TestBot")
    # Simulate reconciliation revealing more prior spend after quote issuance.
    async with test_db.tenant(repo.owner) as session:
        (await session.get(LLMCall, call)).actual_usd = Decimal("0.009")
    with pytest.raises(PolicyError, match="monthly_budget"):
        await repo.dispatch(row.id, p)


async def test_clear_inflight_discards_output_but_keeps_billing(test_db):
    tg, repo = await fixture(test_db)
    row = await ask(tg, repo)
    call = await repo.dispatch(row.id, plan(repo))
    await tg.ingest([incoming(tg, 101, "/clear")], "TestBot")
    await repo.finish(row.id, call, Completion("OLD PRIVATE ANSWER", Decimal(0), 100, 3), None)
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(ConversationMessage)) == 0
        assert (await session.get(LLMCall, call)).status == "succeeded"
        assert (await session.get(AssistantRequest, row.id)).prompt is None
    assert (await receipt(tg)).reply_text is None


async def test_profile_change_cancels_pending_premium_and_restricted_stops_snapshot(test_db):
    tg, repo = await fixture(test_db, premium=True)
    row, p, code = await offer(tg, repo)
    await tg.ingest([incoming(tg, 101, "/remember nama Baru")], "TestBot")
    await tg.ingest([incoming(tg, 102, "/approve " + code)], "TestBot")
    assert await repo.dispatch(row.id, p) is None
    async with test_db.tenant(repo.owner) as session:
        (await session.get(ProfileMemory, (repo.owner, "nama"))).data_class = "restricted"
    await tg.ingest([incoming(tg, 103, "/ask Halo")], "TestBot")
    with pytest.raises(PolicyError, match="restricted_profile"):
        await repo.prepare(await repo.next_request())


async def test_dispatch_rechecks_disabled_identity(test_db):
    tg, repo = await fixture(test_db)
    row = await ask(tg, repo)
    async with test_db.tenant(repo.owner) as session:
        (await session.scalar(select(ExternalIdentity))).enabled = False
    with pytest.raises(PolicyError, match="authorization_changed"):
        await repo.dispatch(row.id, plan(repo))


async def test_crash_recovery_holds_reservation_never_replays(test_db):
    tg, repo = await fixture(test_db, premium=True)
    row, p, code = await offer(tg, repo)
    await tg.ingest([incoming(tg, 101, "/approve " + code)], "TestBot")
    call = await repo.dispatch(row.id, p)
    await repo.initialize()
    assert await repo.next_request() is None
    async with test_db.tenant(repo.owner) as session:
        assert (await session.get(AssistantRequest, row.id)).status == "uncertain"
        assert (await session.get(LLMCall, call)).actual_usd is None
    assert Decimal((await repo.status())["month_spent_or_held_usd"]) > 0


async def test_unknown_billing_freezes_inference_and_keeps_reservation(test_db):
    tg, repo = await fixture(test_db)
    row = await ask(tg, repo)
    call = await repo.dispatch(row.id, plan(repo))
    await repo.finish(row.id, call, None, RouterError("unverifiable_response", uncertain=True))
    status = await repo.status()
    assert status["frozen"] and not status["enabled"]


async def test_daily_free_limit_and_duplicate_attempt_denied(test_db):
    tg, repo = await fixture(test_db)
    row = await ask(tg, repo)
    call = await repo.dispatch(row.id, plan(repo))
    await repo.finish(row.id, call, None, RouterError("request_rejected", uncertain=False))
    with pytest.raises(PolicyError, match="attempt_already_used"):
        await repo.dispatch(row.id, plan(repo))


async def test_memory_request_and_ledger_force_rls(test_db):
    tg, repo = await fixture(test_db)
    _, other = await fixture(test_db)
    row = await ask(tg, repo)
    call = await repo.dispatch(row.id, plan(repo))
    async with test_db.tenant(other.owner) as session:
        assert await session.get(AssistantRequest, row.id) is None
        assert await session.get(LLMCall, call) is None
        assert await session.get(AssistantState, repo.owner) is None
    with pytest.raises(DBAPIError):
        async with test_db.tenant(other.owner) as session:
            session.add(ProfileMemory(owner_id=repo.owner, key="foreign", value="forbidden"))
    async with test_db.engine.connect() as connection:
        for table in (
            "assistant_state",
            "profile_memory",
            "assistant_requests",
            "conversation_messages",
            "llm_calls",
        ):
            assert await connection.scalar(text(f"SELECT count(*) FROM app.{table}")) == 0


async def test_secret_restricted_and_foreign_ask_not_persisted(test_db):
    tg, repo = await fixture(test_db)
    for n, command in enumerate(("/ask password=VERYPRIVATE", "/restricted VERYPRIVATE"), 100):
        await tg.ingest([incoming(tg, n, command)], "TestBot")
    await tg.ingest(
        [incoming(tg, 102, "/ask VERYPRIVATE", sender=tg.config.sender_id + 1)], "TestBot"
    )
    async with test_db.tenant(repo.owner) as session:
        assert await session.scalar(select(func.count()).select_from(AssistantRequest)) == 0
        rows = (await session.scalars(select(TelegramReceipt))).all()
        assert all("VERYPRIVATE" not in (r.reply_text or "") for r in rows)


async def test_only_one_assistant_worker_per_owner(test_db):
    _, repo = await fixture(test_db)
    async with assistant_lock(test_db, repo.owner) as check:
        await check()
        with pytest.raises(ConfigurationError, match="Another assistant"):
            async with assistant_lock(test_db, repo.owner):
                pytest.fail("second worker acquired lock")


async def test_retention_removes_failed_unsnapshotted_prompts_and_old_context(test_db):
    tg, repo = await fixture(test_db)
    row = await ask(tg, repo)
    await repo.fail(row.id)
    async with test_db.tenant(repo.owner) as session:
        req = await session.get(AssistantRequest, row.id)
        req.messages = None
        req.created_at = now_utc() - timedelta(days=31)
    await repo.prune()
    async with test_db.tenant(repo.owner) as session:
        req = await session.get(AssistantRequest, row.id)
        assert req.prompt is None and req.messages is None
        assert await session.scalar(
            text("SELECT messages IS NULL FROM app.assistant_requests WHERE id=:id"), {"id": row.id}
        )


async def test_full_langgraph_free_flow_uses_real_transactions_without_network(test_db):
    from unittest.mock import AsyncMock

    from jarvis.assistant.graph import AssistantWorkflow

    tg, repo = await fixture(test_db)
    await tg.ingest([incoming(tg, 100, "/ask Halo")], "TestBot")
    router = AsyncMock()
    router.plan.return_value = plan(repo)
    router.complete.return_value = Completion("Halo kembali", Decimal(0), 100, 3)
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(await repo.next_request())
    assert (await receipt(tg)).reply_text == "Halo kembali"
    assert router.complete.await_count == 1


async def test_daily_free_quota_stops_second_request(test_db):
    tg, old = await fixture(test_db)
    repo = AssistantRepository(test_db, old.config.model_copy(update={"daily_free_calls": 1}))
    await repo.initialize()
    async with test_db.tenant(repo.owner) as session:
        (await owner_state(session, repo.owner)).enabled = True
    row = await ask(tg, repo)
    call = await repo.dispatch(row.id, plan(repo))
    await repo.finish(row.id, call, Completion("Selesai", Decimal(0), 100, 2), None)
    row2 = await ask(tg, repo, 101)
    with pytest.raises(PolicyError, match="daily_free_limit"):
        await repo.dispatch(row2.id, plan(repo))
