import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from jarvis.assistant.graph import AssistantWorkflow
from jarvis.assistant.policy import PolicyError
from jarvis.assistant.router import RouterError
from jarvis.interfaces.telegram.commands import parse_update
from jarvis.interfaces.telegram.config import TelegramConfig

SPEC = importlib.util.spec_from_file_location(
    "setup_assistant_script", Path(__file__).resolve().parents[2] / "scripts/setup_assistant.py"
)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class FakeDB:
    def __init__(self, row):
        self.row = row

    @asynccontextmanager
    async def tenant(self, owner):
        yield SimpleNamespace(get=AsyncMock(return_value=self.row))


def components(status="preparing"):
    row = SimpleNamespace(
        status=status, messages=[{"content": "PRIVATE-QUESTION"}], data_class="private"
    )
    repo = SimpleNamespace(
        db=FakeDB(row),
        owner=uuid4(),
        config=SimpleNamespace(premium_enabled=True),
        prepare=AsyncMock(return_value=row),
        route_tool=AsyncMock(return_value=False),
        dispatch=AsyncMock(return_value=uuid4()),
        finish=AsyncMock(return_value=False),
        offer=AsyncMock(),
        fail=AsyncMock(),
    )
    router = SimpleNamespace(
        plan=AsyncMock(return_value={"kind": "free"}), complete=AsyncMock(return_value=object())
    )
    return repo, router


async def test_graph_awaits_premium_consent_without_calling_premium():
    repo, router = components()
    router.plan.side_effect = [PolicyError("no_free_endpoint"), {"kind": "premium"}]
    workflow = AssistantWorkflow(repo, router, AsyncMock())
    result = await workflow.invoke(uuid4())
    assert "PRIVATE" not in str(result) and set(result) == {"request_id", "action"}
    assert repo.offer.await_count == 1
    router.complete.assert_not_awaited()
    repo.dispatch.assert_not_awaited()


async def test_paid_error_never_retries_or_generates_new_automatic_consent():
    repo, router = components("approved")
    router.complete.side_effect = RouterError("timeout", uncertain=True)
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(uuid4())
    assert router.complete.await_count == router.plan.await_count == repo.dispatch.await_count == 1
    assert repo.finish.call_args.args[2] is None
    repo.offer.assert_not_awaited()


async def test_guard_failure_and_lost_reservation_never_call_provider():
    repo, router = components()
    repo.prepare.side_effect = PolicyError("context_blocked")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(uuid4())
    repo.fail.assert_awaited_once()
    router.plan.assert_not_awaited()
    repo.prepare.side_effect = None
    repo.dispatch.return_value = None
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(uuid4())
    router.complete.assert_not_awaited()


async def test_changed_premium_plan_stops_without_new_charge():
    repo, router = components("approved")
    repo.dispatch.side_effect = PolicyError("fresh_consent_required")
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(uuid4())
    router.complete.assert_not_awaited()
    repo.offer.assert_not_awaited()
    repo.fail.assert_awaited_once()


@pytest.mark.parametrize(
    "error,expected",
    [
        (PolicyError("endpoint_unavailable"), "endpoint_unavailable"),
        (PolicyError("zdr_not_verified"), "zdr_not_verified"),
        (RouterError("request_rejected", http_status=401), "openrouter_http_401"),
        (PolicyError("PRIVATE-PROVIDER-BODY"), "policy_blocked"),
    ],
)
async def test_free_plan_failure_is_not_hidden_by_disabled_premium(error, expected):
    repo, router = components()
    repo.config.premium_enabled = False
    router.plan.side_effect = error
    request_id = uuid4()
    result = await AssistantWorkflow(repo, router, AsyncMock()).invoke(request_id)
    repo.fail.assert_awaited_once_with(request_id, expected)
    assert router.plan.await_count == 1
    router.complete.assert_not_awaited()
    repo.offer.assert_not_awaited()
    assert set(result) == {"request_id", "action"}


async def test_local_dispatch_limit_preserved_without_inference_or_premium():
    repo, router = components()
    repo.config.premium_enabled = False
    repo.dispatch.side_effect = PolicyError("daily_free_limit")
    request_id = uuid4()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(request_id)
    repo.fail.assert_awaited_once_with(request_id, "daily_free_limit")
    router.complete.assert_not_awaited()
    repo.offer.assert_not_awaited()


@pytest.mark.parametrize("http_status", [400, 401, 402, 403, 404, 422, 429])
async def test_rejected_free_call_keeps_http_code_without_second_attempt(http_status, caplog):
    repo, router = components()
    repo.config.premium_enabled = False
    error = RouterError("request_rejected", http_status=http_status)
    router.complete.side_effect = error
    repo.finish.return_value = True
    request_id = uuid4()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(request_id)
    repo.fail.assert_awaited_once_with(request_id, f"openrouter_http_{http_status}")
    assert router.plan.await_count == router.complete.await_count == 1
    repo.finish.assert_awaited_once_with(request_id, repo.dispatch.return_value, None, error)
    repo.offer.assert_not_awaited()
    record = next(r for r in caplog.records if r.event == "assistant.complete")
    assert record.status == http_status
    assert record.request_id == str(request_id)
    assert "PRIVATE" not in str(record.__dict__)


async def test_uncertain_free_call_retains_no_retry_path_and_does_not_call_fail():
    repo, router = components()
    repo.config.premium_enabled = False
    error = RouterError("transport_or_format_error", uncertain=True)
    router.complete.side_effect = error
    repo.finish.return_value = False
    request_id = uuid4()
    await AssistantWorkflow(repo, router, AsyncMock()).invoke(request_id)
    repo.finish.assert_awaited_once_with(request_id, repo.dispatch.return_value, None, error)
    repo.fail.assert_not_awaited()
    repo.offer.assert_not_awaited()
    assert router.plan.await_count == router.complete.await_count == 1


def test_setup_assistant_generator_uses_portable_newlines_and_never_overwrites(tmp_path):
    folder = tmp_path / ".secrets"
    folder.mkdir()
    key = "sk-or-fake-test-only-value"
    cfg = {"owner_id": str(uuid4()), "monthly_budget_usd": "0"}
    setup.write_config(folder, cfg, key)
    assert (folder / "openrouter_key").read_bytes() == key.encode() + b"\n"
    assert b"\r" not in (folder / "assistant_config.json").read_bytes()
    assert json.loads((folder / "assistant_config.json").read_bytes()) == cfg
    with pytest.raises(setup.SetupError):
        setup.private_folder(tmp_path)
    with pytest.raises(setup.SetupError):
        setup.write_config(folder, {"owner_id": "changed"}, "wrong-key")
    assert (folder / "openrouter_key").read_bytes() == key.encode() + b"\n"


def test_setup_assistant_rolls_back_partial_write_without_touching_existing_key(tmp_path):
    (tmp_path / "openrouter_key").write_bytes(b"already-private\n")
    with pytest.raises(setup.SetupError):
        setup.write_config(tmp_path, {"owner_id": "test"}, "new-key")
    assert not (tmp_path / "assistant_config.json").exists()
    assert (tmp_path / "openrouter_key").read_bytes() == b"already-private\n"


def test_wizard_filters_paid_unknown_and_nontext_endpoints():
    models = [
        {"id": "qwen/test:free", "architecture": {"output_modalities": ["text"]}},
        {"id": "other/image:free", "architecture": {"output_modalities": ["image"]}},
    ]
    e = {
        "model_id": "qwen/test:free",
        "tag": "example/fp8",
        "status": 0,
        "supported_parameters": ["max_tokens"],
        "pricing": {"prompt": "0", "completion": "0"},
    }
    candidates = setup.free_candidates(
        models,
        [
            e,
            {**e, "model_id": "other/image:free"},
            {**e, "pricing": {"prompt": "0.1", "completion": "0"}},
            {**e, "pricing": {"prompt": "0", "completion": "0", "new_fee": "1"}},
        ],
    )
    assert candidates == [{"model": "qwen/test:free", "provider": "example/fp8"}]


def test_assistant_command_argument_never_in_repr_and_restricted_discarded():
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    cfg = TelegramConfig(owner_id=uuid4(), bot_id=99999999, sender_id=12345)

    def message(value):
        return {
            "update_id": 1,
            "message": {
                "date": int(now.timestamp()),
                "text": value,
                "from": {"id": 12345, "is_bot": False},
                "chat": {"id": 12345, "type": "private"},
            },
        }

    command = parse_update(message("/ask PRIVATE-QUESTION"), cfg, "MyBot", now)
    assert command.argument == "PRIVATE-QUESTION" and "PRIVATE" not in repr(command)
    command = parse_update(message("/restricted PRIVATE-DOCUMENT"), cfg, "MyBot", now)
    assert command.argument is None
