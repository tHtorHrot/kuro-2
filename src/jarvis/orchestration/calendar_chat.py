"""Trusted Telegram -> durable Calendar handoff; never holds Google credentials."""

import re
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from jarvis.core.calendar_directive import parse_solo_create
from jarvis.integrations.calendar.agent import calendar_tool_specs
from jarvis.orchestration.calendar_display import (
    DAYS,
    ZONE_LABELS,
    _date_label,
    format_calendar_events,
)
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


_CONFIRM_BARE_APPROVE = re.compile(
    r"^(ya|setuju|setujui|setujuin|deal|jadi|lanjut)\s*[.!]?\s*$", re.I
)
_CONFIRM_BARE_CANCEL = re.compile(
    r"^(batal|batalkan|batalin|hapus|hapuskan|gajadi|gak\s*jadi|nggak\s*jadi|tidak\s*jadi)"
    r"\s*[.!]?\s*$",
    re.I,
)
_CONFIRM_BULK_APPROVE = re.compile(
    r"^(setujui|setuju|setujuin|deal)\s+(semua|semuanya|all)\s*[.!]?\s*$", re.I
)
_CONFIRM_BULK_CANCEL = re.compile(
    r"^(batalkan|batal|batalin|hapuskan|hapus)\s+(semua|semuanya|all)\s*[.!]?\s*$", re.I
)
_CONFIRM_RECENT = re.compile(
    r"^(?:rapat(?:nya|ku)?\s+)?(batalkan|batal|batalin|hapus|hapuskan)\s*"
    r"((?:yang\s+)?(?:tadi|itu|ini|tersebut))?\s*(aja|saja)?\s*$",
    re.I,
)
_CONFIRM_NUMBER = re.compile(
    r"^(setujui|setuju|pilih|batalkan|batal)\s+(?:nomor|nomornya|usulan|no\.?|ke)?\s*(\d{1,2})\s*[.!]?\s*$",
    re.I,
)
_CONFIRM_NUMBER_BARE = re.compile(r"^(?:nomor|usulan|no\.?)\s*(\d{1,2})\s*[.!]?\s*$", re.I)


def parse_confirmation(text: str) -> tuple[str, int | None] | None:
    """One-word or numbered reply to a pending proposal.

    Returns (approve|cancel|show, number|None): 'ya' -> (approve, None),
    'setujui nomor 2' -> (approve, 2), 'nomor 2' -> (show, 2).
    None when not a confirmation; other bare numbers stay clock answers.
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 40:
        return None
    if _CONFIRM_BARE_APPROVE.match(raw):
        return ("approve", None)
    if _CONFIRM_BARE_CANCEL.match(raw):
        return ("cancel", None)
    numbered = _CONFIRM_NUMBER.match(raw)
    if numbered:
        number = int(numbered[2])
        if numbered[1].lower() in {"batalkan", "batal"}:
            return ("cancel", number)
        return ("approve", number)
    bare = _CONFIRM_NUMBER_BARE.match(raw)
    if bare:
        return ("show", int(bare[1]))
    if _CONFIRM_RECENT.match(raw):
        return ("cancel", None)
    return None


def parse_bulk(text: str) -> str | None:
    """'batalin semua' -> cancel_all, 'setujui semuanya' -> approve_all."""
    raw = (text or "").strip()
    if not raw or len(raw) > 40:
        return None
    if _CONFIRM_BULK_APPROVE.match(raw):
        return "approve_all"
    if _CONFIRM_BULK_CANCEL.match(raw):
        return "cancel_all"
    return None


_COMPOUND_SPLIT = re.compile(r"\s*(?:dan|serta|lalu|kemudian|terus|trus|,\s*|\;\s*)\s*", re.I)


def parse_compound(text: str) -> list[tuple[str, int | None]] | None:
    """'setujui nomor 2 dan batalkan nomor 1' -> [(approve, 2), (cancel, 1)].

    All-or-nothing: every segment must parse as a confirmation, otherwise None
    (falls through to chat) so nothing is half-executed on vague input.
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 120:
        return None
    parts = [p for p in _COMPOUND_SPLIT.split(raw) if p.strip()]
    if len(parts) < 2:
        return None
    parsed = [parse_confirmation(part) for part in parts]
    if any(item is None for item in parsed):
        return None
    return parsed


async def _pending_actions(session, owner):
    return (
        await session.scalars(
            select(ToolAction)
            .where(
                ToolAction.owner_id == owner,
                ToolAction.agent == "calendar",
                ToolAction.status == "awaiting_approval",
            )
            .order_by(ToolAction.created_at, ToolAction.id)
        )
    ).all()


def _proposal_line(action, number: int) -> str:
    args = action.arguments or {}
    if action.tool_name == "calendar_delete_event":
        what = f"Hapus event {args.get('event_id', '')}"
    else:
        when = human_range(args.get("start", ""), args.get("end", ""), args.get("timezone", ""))
        what = f"{args.get('title', '')} — {when or args.get('start', '')}"
    return f"{number}. {what} (Ref {short_id(action.id)})"


async def route_confirmation(session, repo, request) -> bool:
    """Handle 'ya' / 'setujui nomor 2 dan batalkan nomor 1' vs antrean live.

    Numbers mean the queue as it stands now. Clauses execute in message order
    with a per-item report; a clause that points nowhere stops everything
    before it, so vague input is never half-executed. Unknown queue state
    falls through to chat (returns False) so plain talk is never stolen.
    """
    from jarvis.assistant.repository import deliver
    from jarvis.orchestration.calendar_tasks import cancel_target
    from jarvis.tools.journal import ActionJournal, ActionJournalError

    compound = parse_compound(request.prompt or "")
    single = parse_confirmation(request.prompt or "") if compound is None else None
    bulk = parse_bulk(request.prompt or "") if compound is None and single is None else None
    items = compound if compound is not None else ([single] if single else None)
    if not items and bulk is None:
        return False
    pendings = await _pending_actions(session, repo.owner)
    if not pendings:
        return False
    if bulk == "approve_all":
        if len(pendings) == 1:
            items = [("approve", None)]
        else:
            lines = [_proposal_line(a, n) for n, a in enumerate(pendings, 1)]
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(
                session,
                request,
                "Setujui massal ditolak agar tidak salah sasaran. Pilih:\n{}\n"
                "Balas: setujui nomor 1.".format("\n".join(lines)),
            )
            return True
    elif bulk == "cancel_all":
        reports = []
        for n, target in enumerate(pendings, 1):
            outcome = await cancel_target(session, repo.owner, str(target.id))
            reports.append(f"{n}. {outcome}")
        request.status, request.finished_at = "succeeded", now_utc()
        await deliver(session, request, "\n".join(reports))
        return True
    if len(items) == 1 and items[0][1] is None and len(pendings) > 1 and items[0][0] != "show":
        lines = [_proposal_line(a, n) for n, a in enumerate(pendings, 1)]
        request.status, request.finished_at = "clarified", now_utc()
        await deliver(
            session,
            request,
            "Ada {} usulan menunggu:\n{}\nBalas: setujui nomor 1. "
            "Batalkan semua: balas batalin semua.".format(len(pendings), "\n".join(lines)),
        )
        return True
    targets = []
    for verb, number in items:
        if number is not None and not 1 <= number <= len(pendings):
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(session, request, f"Nomor 1–{len(pendings)} saja yang menunggu.")
            return True
        targets.append((verb, number, pendings[0] if number is None else pendings[number - 1]))
    reports: list[str] = []
    failed = False
    for verb, number, target in targets:
        label = f"usulan {1 if number is None else number} ({short_id(target.id)})"
        if verb == "show":
            position, total = await pending_position(session, repo.owner, target.id)
            reports.append(approval_text(target, position=position, total=total))
            continue
        if verb == "approve":
            try:
                await ActionJournal(None, repo.owner, REGISTRY).approve(
                    target.id, target.action_fingerprint, session=session
                )
            except ActionJournalError:
                reports.append(f"{label}: gagal — sudah diputuskan / kedaluwarsa.")
                failed = True
                break
            reports.append(f"Menyetujui {label}.\nJalan: {target.due_at.isoformat()} UTC.")
            continue
        outcome = await cancel_target(session, repo.owner, str(target.id))
        reports.append(outcome)
        if "dibatalkan" not in outcome:
            failed = True
            break
    request.status, request.finished_at = ("failed" if failed else "succeeded"), now_utc()
    await deliver(session, request, "\n\n".join(reports))
    return True


def propose(text, *, timezone, received_at):
    """Small deterministic vertical slice; incomplete commands cannot become writes."""
    zone = ZoneInfo(timezone)
    local_day = received_at.astimezone(zone).date()
    read = re.fullmatch(
        r"(?:KURO[, :]\s*)?(?:apa\s+)?jadwal(?:ku)?\s+"
        r"(hari ini|besok|\d{4}-\d{2}-\d{2})"
        r"(?:\s+apa)?(?:\s+(?:aja|saja|dong|kok|ya|kah|nih|deh))?\??",
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
        r"(?:KURO[, :]\s*)?(?:tolong\s+)?(?:buat(?:kan)?|bikin|tambahkan|jadwalkan|hapus)\s+"
        r"(?:rapat|meeting|acara|event)\b",
        text.strip(),
        re.I,
    ):
        return HELP.format(day=(local_day + timedelta(days=1)).isoformat(), zone=timezone)
    return None


def short_id(value) -> str:
    """First 8 hex chars for machine IDs; human IDs stay whole for tests and search."""
    import re

    text = str(value)
    compact = text.replace("-", "")
    if re.fullmatch(r"(kuro)?[0-9a-fA-F]{8,}", compact):
        return compact[:8]
    return text


def _iso(value) -> str | None:
    try:
        return value.isoformat()
    except AttributeError:
        return None


def human_range(start_raw, end_raw, timezone: str) -> str | None:
    """'Sabtu, 10 Oktober 10.00–10.15 (WIB)'. None when unparseable (caller falls back)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        zone = ZoneInfo(timezone)
        start = datetime.fromisoformat(start_raw)
        end = datetime.fromisoformat(end_raw)
        if start.tzinfo is None or end.tzinfo is None:
            return None
        start, end = start.astimezone(zone), end.astimezone(zone)
    except (TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        return None
    label = ZONE_LABELS.get(zone.key, zone.key)
    return (
        f"{DAYS[start.weekday()]}, {_date_label(start.date())} "
        f"{start.strftime('%H.%M')}–{end.strftime('%H.%M')} ({label})"
    )


async def pending_position(session, owner, action_id) -> tuple[int | None, int]:
    """1-based queue number of this proposal among awaiting approvals (voice ordinal bridge)."""
    rows = (
        await session.scalars(
            select(ToolAction.id)
            .where(
                ToolAction.owner_id == owner,
                ToolAction.agent == "calendar",
                ToolAction.status == "awaiting_approval",
            )
            .order_by(ToolAction.created_at, ToolAction.id)
        )
    ).all()
    ids = [str(i) for i in rows]
    try:
        return ids.index(str(action_id)) + 1, len(ids)
    except ValueError:
        return None, len(ids)


async def resolve_action(session, owner, ref):
    """Full UUID or unique 8+ char prefix within owner calendar actions. None if ambiguous."""
    from uuid import UUID

    try:
        action_id = UUID(str(ref))
    except (ValueError, AttributeError, TypeError):
        action_id = None
    if action_id is not None:
        action = await session.get(ToolAction, action_id)
        return action if action is not None and action.owner_id == owner else None
    prefix = str(ref or "").strip().lower().replace("-", "")
    if not 8 <= len(prefix) <= 32 or any(c not in "0123456789abcdef" for c in prefix):
        return None
    rows = (
        await session.scalars(
            select(ToolAction).where(ToolAction.owner_id == owner, ToolAction.agent == "calendar")
        )
    ).all()
    matches = [a for a in rows if str(a.id).replace("-", "").startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


def approval_text(action, *, position=None, total=None):
    args = action.arguments
    if action.tool_name == "calendar_delete_event":
        detail = f"Hapus event {args['event_id']}"
    else:
        when = human_range(args.get("start", ""), args.get("end", ""), args.get("timezone", ""))
        raw_when = args.get("start", "") + " → " + args.get("end", "")
        detail = f"{args.get('title', '')}\n{when or raw_when}"
        guests = ", ".join(args.get("attendees", []))
        if guests:
            detail += f"\nUndang: {guests}"
    schedule = ""
    if action.fingerprint_version == 2:
        due, latest = _iso(action.due_at), _iso(action.latest_dispatch_at)
        if due:
            schedule += f"Jalan: {due} UTC.\n"
        if latest:
            schedule += f"Batas telat: {latest}.\n"
    validity = ""
    if _iso(action.approval_expires_at):
        validity = f"Berlaku sampai {_iso(action.approval_expires_at)}."
    header = "Kalender — perlu persetujuan:"
    if position and total:
        header = f"Kalender — usulan {position} dari {total} menunggu:"
    return (
        f"{header}\n{detail}\n{schedule}"
        f"Ref: {short_id(action.id)}\n"
        f"/toolapprove {action.id} {action.action_fingerprint}\n"
        f"Batal: /cancel {short_id(action.id)}.\n{validity}"
        f"\nKetuk Setuju/Batal di bawah, atau pakai perintah."
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
        grant = await session.get(ToolGrant, (repo.owner, "calendar"))
        if intent is None or isinstance(intent, str):
            from jarvis.orchestration.calendar_tasks import route_draft

            if await route_draft(session, repo, request, state, user, grant):
                return True
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
            position, total = await pending_position(session, repo.owner, action.id)
            await deliver(session, request, approval_text(action, position=position, total=total))
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
    if request.status == "handed_off":
        set_reply(
            receipt,
            f"Aksi {short_id(action.id)} disetujui, jalan {action.due_at.isoformat()} UTC.\n"
            "Chat tetap bisa dipakai; hasil dikirim setelah provider konfirmasi.\n"
            f"Cek: /toolstatus {short_id(action.id)} — Batal: /cancel {short_id(action.id)}",
        )
    else:
        request.reply_update_id = incoming.update_id
        set_reply(receipt, None)


async def deliver_completed(session, owner, state):
    """Replay-safe terminal notification from committed results, never an LLM claim."""
    from jarvis.assistant.repository import authorized, deliver
    from jarvis.orchestration.calendar_tasks import complete_tasks

    await complete_tasks(session, owner, state)
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
        text = completion_text(action)
        request.status, request.finished_at = action.status, now_utc()
        await deliver(session, request, text)


def completion_text(action):
    if action.status == "succeeded":
        if action.tool_name == "calendar_list_events":
            text = format_calendar_events(
                action.result or [],
                time_min=action.arguments.get("time_min"),
                timezone=action.due_timezone,
            )
        elif action.tool_name == "calendar_delete_event":
            text = f"Kalender: event {action.arguments['event_id']} sudah dihapus."
        else:
            when = human_range(
                action.arguments.get("start", ""),
                action.arguments.get("end", ""),
                action.arguments.get("timezone", ""),
            )
            event_id = (action.result or {}).get("id", "(tidak tersedia)")
            raw_when = action.arguments.get("start", "") + " → " + action.arguments.get("end", "")
            # Full event ID stays visible: users need it for delete and Google lookup.
            text = (
                f"Kalender: {action.arguments.get('title', '')} tersimpan.\n"
                f"{when or raw_when}\n"
                f"ID: {event_id}"
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
    return text
