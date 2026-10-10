"""One-tap approve/cancel for Calendar proposals via inline buttons.

A tap carries only the action UUID. The fingerprint and all authority checks
stay server-side: the button is generated from the proposal the server just
displayed, and journal approval still enforces exact fingerprint, single use,
expiry, grant revision and scope. Stale taps fail closed like typed commands.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select

APPROVE_PREFIX = "approve:"
CANCEL_PREFIX = "cancel:"
_TOOLAPPROVE_LINE = re.compile(r"^/toolapprove ([0-9a-fA-F-]{36}) [0-9a-fA-F]{64}$", re.M)


def proposal_markup(text: str | None) -> dict | None:
    """Inline buttons for a server-generated proposal, else None (plain send)."""
    if not isinstance(text, str):
        return None
    match = _TOOLAPPROVE_LINE.search(text)
    if not match:
        return None
    action_id = match[1]
    return {
        "inline_keyboard": [
            [
                {"text": "Setuju ✓", "callback_data": APPROVE_PREFIX + action_id},
                {"text": "Batal", "callback_data": CANCEL_PREFIX + action_id},
            ]
        ]
    }


async def handle_callback(session, owner, incoming) -> str:
    """Decide a tap inside the ingest transaction. Returns short popup feedback."""
    from jarvis.orchestration.calendar_chat import REGISTRY
    from jarvis.orchestration.calendar_tasks import cancel_target
    from jarvis.storage.models import ToolAction
    from jarvis.tools.journal import ActionJournal, ActionJournalError

    data = incoming.argument or ""
    action_uuid = None
    for prefix in (APPROVE_PREFIX, CANCEL_PREFIX):
        if data.startswith(prefix):
            try:
                action_uuid = UUID(data[len(prefix) :])
            except ValueError:
                return "Perintah tombol tidak valid."
            break
    else:
        return "Tombol tidak dikenal."
    if data.startswith(APPROVE_PREFIX):
        action = await session.scalar(
            select(ToolAction).where(ToolAction.owner_id == owner, ToolAction.id == action_uuid)
        )
        if (
            action is None
            or not action.request_id
            or action.agent != "calendar"
            or action.tool_name not in REGISTRY.names()
        ):
            return "Proposal tidak ditemukan."
        try:
            await ActionJournal(None, owner, REGISTRY).approve(
                action_uuid, action.action_fingerprint, session=session
            )
        except ActionJournalError:
            return "Sudah diputuskan / kedaluwarsa / izin berubah."
        return "Disetujui ✓"
    outcome = await cancel_target(session, owner, str(action_uuid))
    if "dibatalkan" in outcome:
        return "Dibatalkan."
    return outcome
