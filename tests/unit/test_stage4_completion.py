from datetime import UTC, datetime
from uuid import uuid4

import pytest

from jarvis.tools import AuthorizationContext, ToolEffect, ToolProposal, ToolRegistry, ToolSpec
from jarvis.tools.journal import ActionJournal, ActionJournalError


def _journal():
    registry = ToolRegistry(
        [
            ToolSpec(
                "clock_read",
                "clock",
                "clock",
                frozenset({"clock:read"}),
                ToolEffect.READ,
                argument_keys=frozenset({"value"}),
            )
        ]
    )
    return ActionJournal(None, uuid4(), registry)


async def test_action_rejects_invalid_source_timezone_before_database_access():
    with pytest.raises(ActionJournalError, match="invalid_due_timezone"):
        await _journal().create(
            ToolProposal("clock_read", {"value": "x"}),
            AuthorizationContext(frozenset({"clock:read"})),
            due_at=datetime.now(UTC),
            due_timezone="Mars/Olympus",
        )


def test_calendar_compose_keeps_google_secrets_out_of_assistant():
    import yaml

    compose = yaml.safe_load(open("compose.calendar.yaml", encoding="utf-8"))
    services = compose.get("services", {})
    assert "scheduler" in services
    assert "assistant" not in services
    scheduler = services["scheduler"]
    # Unquoted commas in a YAML flow list must not become relative mount paths.
    mounts = scheduler["tmpfs"]
    if isinstance(mounts, str):
        mounts = [mounts]
    assert mounts and all(isinstance(m, str) and m.startswith("/") for m in mounts)
    assert (
        scheduler.get("environment", {}).get("JARVIS_GOOGLE_REFRESH_TOKEN_FILE")
        == "/run/secrets/google_refresh_token"
    )
    assert "google_refresh_token" in scheduler.get("secrets", [])


def test_stage4_migration_head_records_source_timezone():
    text = open("migrations/versions/0006_tool_action_timezone.py", encoding="utf-8").read()
    assert 'revision = "0006_tool_action_timezone"' in text
    assert "due_timezone" in text
    assert "NEW.due_at IS DISTINCT FROM OLD.due_at" in text


def test_stage4_schema_revision_is_consistent_across_runtime_and_upgrade_gates():
    from jarvis.storage.database import SCHEMA_REVISION

    assert SCHEMA_REVISION == "0017_task_role_documents"
    upgrade = open("scripts/check_test_upgrade.py", encoding="utf-8").read()
    wasm = open("tests/sql/verify_wasm_schema.mjs", encoding="utf-8").read()
    assert '== "0017_task_role_documents"' in upgrade
    assert "=== '0017_task_role_documents'" in wasm
