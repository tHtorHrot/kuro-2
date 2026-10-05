import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from jarvis.assistant import cli
from jarvis.assistant.diagnostics import DIAGNOSTICS_VERSION, error_code, report_error
from jarvis.assistant.policy import PolicyError
from jarvis.assistant.router import RouterError
from jarvis.core.config import ConfigurationError
from jarvis.core.logging import SafeJsonFormatter


@pytest.mark.parametrize(
    "error,expected",
    [
        (PolicyError("zdr_not_verified"), "zdr_not_verified"),
        (PolicyError("sk-or-PRIVATE-CREDENTIAL"), "policy_blocked"),
        (RouterError("PRIVATE-RESPONSE"), "openrouter_unavailable"),
        (RouterError("request_rejected", http_status=429), "openrouter_http_429"),
        (
            RouterError("transport_or_format_error", uncertain=True),
            "openrouter_transport_or_format_error",
        ),
        (ValueError("PRIVATE-EXCEPTION"), "unexpected_error"),
    ],
)
def test_diagnostic_output_is_allowlisted_and_contains_no_exception_content(error, expected):
    assert error_code(error) == expected


@pytest.mark.parametrize("status", [True, "429 PRIVATE", -1, 600, None])
def test_invalid_http_diagnostic_status_is_discarded(status):
    error = RouterError("request_rejected", http_status=status)
    assert error.http_status is None
    assert error_code(error) == "openrouter_request_rejected"


def test_json_log_excludes_private_exception_data_and_unrecognized_fields(caplog):
    request_id = uuid4()
    error = PolicyError("PRIVATE-PROMPT Bearer PRIVATE-KEY https://private.invalid")
    assert report_error(error, phase="plan", kind="free", request_id=request_id) == "policy_blocked"
    record = caplog.records[-1]
    record.response_body = "PRIVATE-RESPONSE"
    raw = SafeJsonFormatter().format(record)
    assert "PRIVATE" not in raw and "Bearer" not in raw and "https" not in raw
    value = json.loads(raw)
    assert value["event"] == "assistant.plan" and value["route"] == "free"
    assert value["error_type"] == "policy_blocked"
    assert value["request_id"] == str(request_id)
    assert "exc_info" not in value and "response_body" not in value


def fake_cli(monkeypatch, settings):
    db = SimpleNamespace(ready=AsyncMock(return_value=True), close=AsyncMock())
    router = SimpleNamespace(plan=AsyncMock(), close=AsyncMock(), complete=AsyncMock())
    repo = SimpleNamespace(status=AsyncMock(return_value={"enabled": True}))
    config = SimpleNamespace(owner_id=uuid4())
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "load_assistant_config", lambda: config)
    monkeypatch.setattr(cli, "load_router_key", lambda: SecretStr("PRIVATE-KEY"))
    monkeypatch.setattr(cli, "configure_logging", lambda *args: None)
    monkeypatch.setattr(cli, "Database", lambda _: db)
    monkeypatch.setattr(cli, "OpenRouter", lambda _: router)
    monkeypatch.setattr(cli, "AssistantRepository", lambda *args: repo)
    return db, router, repo


@pytest.mark.parametrize(
    "error,expected",
    [
        (PolicyError("catalog_changed"), "catalog_changed"),
        (RouterError("request_rejected", http_status=401), "openrouter_http_401"),
    ],
)
async def test_catalog_exposes_specific_safe_failure_without_inference_or_db_writes(
    monkeypatch, settings, error, expected
):
    db, router, repo = fake_cli(monkeypatch, settings)
    router.plan.side_effect = error
    with pytest.raises(ConfigurationError, match=expected) as caught:
        await cli.operate_assistant("assistant-catalog")
    assert "No inference sent" in str(caught.value) and "PRIVATE" not in str(caught.value)
    router.complete.assert_not_awaited()
    repo.status.assert_not_awaited()
    router.close.assert_awaited_once()
    db.close.assert_awaited_once()


async def test_catalog_success_preserves_metadata_only_contract(monkeypatch, settings):
    _, router, _ = fake_cli(monkeypatch, settings)
    router.plan.return_value = {"kind": "free", "reserve_usd": "0E-10"}
    result = await cli.operate_assistant("assistant-catalog")
    assert result == {
        "metadata_only": True,
        "inference_sent": False,
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "free_plan": router.plan.return_value,
    }
    router.complete.assert_not_awaited()


async def test_status_reports_hotfix_without_loading_router_key(monkeypatch, settings):
    db, router, _ = fake_cli(monkeypatch, settings)

    def no_key():
        pytest.fail("status must not read OpenRouter credentials")

    monkeypatch.setattr(cli, "load_router_key", no_key)
    result = await cli.operate_assistant("assistant-status")
    assert result["diagnostics_version"] == DIAGNOSTICS_VERSION
    router.plan.assert_not_awaited()
    db.close.assert_awaited_once()
