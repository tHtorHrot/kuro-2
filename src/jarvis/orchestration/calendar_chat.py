"""Trusted Telegram -> durable Calendar handoff; never holds Google credentials."""

import re
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jarvis.core.calendar_directive import parse_solo_create
from jarvis.integrations.calendar.agent import calendar_tool_specs
from jarvis.orchestration.calendar_display import format_calendar_events
from jarvis.orchestration.trusted_intent import (
    IntentBindingError,
    IntentKind,
    IntentProposal,
    TrustedIngressEnvelope,
    TrustedIntentBinder,
)
from jarvis.storage.models import AssistantRequest, ToolAction, ToolGrant, User
from jarvis.tools.journal import ActionJournal, ActionJournalError, now_utc
from jarvis.tools.registry import ToolRegistry

REGISTRY = ToolRegistry(calendar_tool_specs())
HELP = (
    "Perlu judul, tanggal, jam mulai/selesai, dan zona waktu. Contoh: "
    'buat rapat "Review" pada {day} jam 10:00 sampai 11:00 zona {zone}. '
    'Tambahkan "undang alamat@email.com" untuk undangan yang perlu persetujuan.'
)


def propose(text, *, timezone, received_at):
    """Small deterministic vertical slice; incomplete commands cannot become writes."""
    zone = ZoneInfo(timezone)
    local_day = received_at.astimezone(zone).date()
    read = re.fullmatch(
        r"(?:KURO[, :]\s*)?(?:apa\s+)?jadwal(?:ku)?\s+"
        r"(hari ini|besok|\d{4}-\d{2}-\d{2})\??",
        text.strip(),
        re.I,
    )
    if read:
        day = read[1].lower()
        date = (
            local_day
            if day == "hari ini"
            else local_day + timedelta(days=1)
            if day == "besok"
            else datetime.strptime(day, "%Y-%m-%d").date()
        )
        start = datetime.combine(date, time(), zone)
        end = datetime.combine(date + timedelta(days=1), time(), zone)
        return IntentProposal(
            IntentKind.CALENDAR_LIST, {"time_min": start.isoformat(), "time_max": end.isoformat()}
        )
    raw, separator, attendees = text.partition(" undang ")
    args = parse_solo_create(raw)
    if args:
        if separator:
            return IntentProposal(
                IntentKind.CALENDAR_INVITE,
                {**args, "attendees": [a.strip() for a in attendees.split(",")]},
            )
        return IntentProposal(IntentKind.CALENDAR_CREATE, args)
    delete = re.fullmatch(
        r"(?:KURO[, :]\s*)?hapus\s+(?:acara|event)\s+([A-Za-z0-9_-]{1,1024})", text.strip(), re.I
    )
    if delete:
        return IntentProposal(IntentKind.CALENDAR_DELETE, {"event_id": delete[1]})
    if re.match(
        r"(?:KURO[, :]\s*)?(?:tolong\s+)?(?:buat(?:kan)?|tambahkan|jadwalkan|hapus)\s+"
        r"(?:rapat|meeting|acara|event)\b",
        text.strip(),
        re.I,
    ):
        return HELP.format(day=(local_day + timedelta(days=1)).isoformat(), zone=timezone)
    return None


def approval_text(action):
    args = action.arguments
    detail = (
        f"Hapus event {args['event_id']}"
        if action.tool_name == "calendar_delete_event"
        else f"{args['title']}\n{args['start']} → {args['end']} ({args['timezone']})\n"
        f"Penerima: {', '.join(args.get('attendees', []))}"
    )
    return (
        f"Persetujuan Calendar diperlukan:\n{detail}\n"
        f"Berlaku sampai {action.approval_expires_at.isoformat()}.\n"
        f"/toolapprove {action.id} {action.action_fingerprint}\nAtau /cancel."
    )


async def route_request(repo, request_id):
    """Atomic source request, action and receipt transition. No model/tool HTTP here."""
    from jarvis.assistant.repository import authorized, deliver, owner_state

    async with repo.db.tenant(repo.owner) as session:
        state = await owner_state(session, repo.owner)
        request = await session.get(AssistantRequest, request_id)
        if not request or request.status != "queued" or request.document_id is not None:
            return False
        user = await session.get(User, repo.owner)
        if not repo.valid(state, request) or not await authorized(
            session, repo.owner, request.bot_id
        ):
            return False  # Existing assistant guard owns the denial path.
        try:
            intent = propose(
                request.prompt or "", timezone=user.timezone, received_at=request.created_at
            )
        except ValueError:
            intent = "Tanggal atau zona waktu tidak valid. Mohon tulis ulang jadwal lengkap."
        if intent is None:
            return False
        if isinstance(intent, str):
            request.status, request.finished_at = "succeeded", now_utc()
            await deliver(session, request, intent)
            return True
        grant = await session.get(ToolGrant, (repo.owner, "calendar"))
        if not grant or not grant.enabled:
            request.status, request.finished_at = "failed", now_utc()
            await deliver(
                session,
                request,
                "Calendar belum diaktifkan oleh pemilik. Tidak ada tindakan dijalankan.",
            )
            return True
        ingress = TrustedIngressEnvelope(
            str(repo.owner), "telegram", str(request.id), request.prompt, True, True
        )
        try:
            bound = TrustedIntentBinder(REGISTRY, frozenset(grant.scopes)).bind(ingress, intent)
            action = await ActionJournal(repo.db, repo.owner, REGISTRY).create(
                bound.proposal,
                bound.context,
                request_id=request.id,
                source_key=f"request:{request.id}:calendar",
                session=session,
                due_timezone=user.timezone,
            )
        except (ActionJournalError, IntentBindingError, ValueError):
            request.status, request.finished_at = "failed", now_utc()
            await deliver(
                session, request, "Permintaan Calendar ditolak: argumen atau izin tidak sesuai."
            )
            return True
        # No LLM call is created. The scheduler owns execution and terminal delivery.
        request.status = "dispatching"
        if action.status == "awaiting_approval":
            await deliver(session, request, approval_text(action))
        return True


async def approve_from_chat(session, owner, incoming, receipt):
    from jarvis.assistant.repository import set_reply

    parts = (incoming.argument or "").split()
    try:
        if len(parts) != 2:
            raise ValueError
        action_id = UUID(parts[0])
    except ValueError:
        set_reply(receipt, "Gunakan /toolapprove ID FINGERPRINT dari proposal Calendar.")
        return
    action = await session.scalar(
        select(ToolAction).where(ToolAction.owner_id == owner, ToolAction.id == action_id)
    )
    if (
        not action
        or not action.request_id
        or action.agent != "calendar"
        or action.tool_name not in REGISTRY.names()
    ):
        set_reply(receipt, "Proposal Calendar tidak ditemukan.")
        return
    journal = ActionJournal(None, owner, REGISTRY)
    try:
        await journal.approve(action_id, parts[1], session=session)
    except ActionJournalError:
        set_reply(receipt, "Persetujuan tidak berlaku, telah dipakai, atau izin berubah.")
        return
    request = await session.get(AssistantRequest, action.request_id)
    request.reply_update_id = incoming.update_id
    set_reply(receipt, None)


async def deliver_completed(session, owner, state):
    """Replay-safe terminal notification from committed results, never an LLM claim."""
    from jarvis.assistant.repository import authorized, deliver

    rows = (
        await session.execute(
            select(AssistantRequest, ToolAction)
            .join(
                ToolAction,
                (ToolAction.owner_id == AssistantRequest.owner_id)
                & (ToolAction.request_id == AssistantRequest.id),
            )
            .where(
                AssistantRequest.owner_id == owner,
                AssistantRequest.status == "dispatching",
                ToolAction.status.in_({"succeeded", "failed", "cancelled", "uncertain"}),
            )
            .limit(25)
        )
    ).all()
    for request, action in rows:
        if (
            not state.enabled
            or state.frozen
            or request.revision != state.revision
            or request.config_hash != state.config_hash
            or not await authorized(session, owner, request.bot_id)
        ):
            request.status, request.finished_at = "cancelled", now_utc()
            continue
        if action.status == "succeeded":
            if action.tool_name == "calendar_list_events":
                text = format_calendar_events(
                    action.result or [],
                    time_min=action.arguments.get("time_min"),
                    timezone=action.due_timezone,
                )
            elif action.tool_name == "calendar_delete_event":
                text = f"Calendar mengonfirmasi penghapusan event {action.arguments['event_id']}."
            else:
                text = (
                    f"Calendar mengonfirmasi acara: {action.arguments.get('title', '')}\n"
                    f"{action.arguments.get('start', '')} → {action.arguments.get('end', '')}\n"
                    f"ID: {(action.result or {}).get('id', '(tidak tersedia)')}"
                )
        elif action.status == "uncertain":
            text = (
                f"Hasil Calendar belum dapat dipastikan (aksi {action.id}). "
                "Tidak diulang otomatis; periksa Calendar dan rekonsiliasi terlebih dahulu."
            )
        elif action.status == "cancelled":
            text = "Tindakan Calendar dibatalkan atau persetujuan kedaluwarsa."
        else:
            text = (
                "Tindakan Calendar gagal sebelum berhasil dikonfirmasi. "
                "Periksa izin dan status layanan."
            )
        request.status, request.finished_at = action.status, now_utc()
        await deliver(session, request, text)
