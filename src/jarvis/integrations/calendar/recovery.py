"""Read-only reconciliation of uncertain solo creates. Never repeats a POST."""

from sqlalchemy import select

from jarvis.identity.service import audit
from jarvis.integrations.calendar.validation import timestamp
from jarvis.storage.models import ToolAction
from jarvis.tools.journal import ActionJournalError, now_utc


def verify_solo_result(action_id, arguments, result):
    try:
        return (
            result["id"] == "kuro" + action_id.hex
            and result.get("status") != "cancelled"
            and result["summary"] == arguments["title"]
            and timestamp(result["start"]["dateTime"]) == timestamp(arguments["start"])
            and timestamp(result["end"]["dateTime"]) == timestamp(arguments["end"])
        )
    except (KeyError, TypeError, ValueError):
        return False


async def reconcile_solo_create(journal, provider, action_id):
    spec = journal.registry.get("calendar_list_events")
    async with journal.db.tenant(journal.owner) as session:
        _, reason = await journal._authority(session, spec)
        if reason:
            raise ActionJournalError(reason)
        row = await session.get(ToolAction, action_id)
        if not row or row.status != "uncertain" or row.tool_name != "calendar_create_event":
            raise ActionJournalError("action_not_reconcilable")
        arguments = dict(row.arguments)
    result = await provider.get_event(event_id="kuro" + action_id.hex)
    if not verify_solo_result(action_id, arguments, result):
        raise ActionJournalError("reconciliation_mismatch")
    async with journal.db.tenant(journal.owner) as session:
        _, reason = await journal._authority(session, spec)
        if reason:
            raise ActionJournalError(reason)
        row = await session.scalar(
            select(ToolAction)
            .where(ToolAction.owner_id == journal.owner, ToolAction.id == action_id)
            .with_for_update()
        )
        if row.status != "uncertain":
            raise ActionJournalError("action_not_reconcilable")
        row.status, row.result, row.finished_at = "succeeded", result, now_utc()
        row.error_code = "reconciled_from_provider"
        audit(session, journal.owner, "tool_action.reconciled", row.id)
    return {"action_id": str(action_id), "status": "succeeded", "provider_write_repeated": False}
