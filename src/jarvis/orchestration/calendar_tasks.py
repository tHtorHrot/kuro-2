"""Owner-scoped Calendar draft/job transactions. No provider call or LLM authority here."""

from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from jarvis.core.calendar_slots import (
    DRAFT_TTL,
    LATE_WINDOW,
    MAX_OPEN_DRAFTS,
    MAX_PENDING_JOBS,
    MAX_TURNS,
    NEGATION,
    SlotEdit,
    SlotError,
    _apply_tod,
    _strip_tod,
    has_meeting_shape,
    ignored_remainder,
    materialize,
    merge_slots,
    parse_edit,
    salvage_fields,
)
from jarvis.storage.models import (
    CalendarNotification,
    CalendarTask,
    ExternalIdentity,
    ToolAction,
)
from jarvis.tools.contracts import AuthorizationContext, ToolProposal
from jarvis.tools.journal import ActionJournal, ActionJournalError, now_utc

TERMINAL = {"succeeded", "failed", "cancelled", "uncertain"}
CANCELLABLE = {"queued", "claimed", "awaiting_approval"}


def _salvage_edit(raw: str) -> tuple[SlotEdit, str | None] | None:
    """Partial validated fields from a message the strict parser rejected.

    Only verb+noun meeting shapes without negations qualify; bare words are
    never guessed as titles and leftovers are reported, never silently kept.
    """
    import re

    from jarvis.core.calendar_slots import _unquoted

    if not has_meeting_shape(raw) or re.search(rf"\b{NEGATION}\b", _unquoted(raw), re.I):
        return None
    text, tod = _strip_tod(raw)
    try:
        found = salvage_fields(text)
    except SlotError:
        return None
    if tod:
        for key in ("start_clock", "end_clock", "execute_clock"):
            if key in found:
                found[key] = _apply_tod(found[key], tod)
    return SlotEdit(fields=found, initial=True, target=None, short_clock=False), ignored_remainder(
        text, found
    )


async def task_valid(session, task, state, grant=None):
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.owner_id == task.owner_id, ExternalIdentity.channel == "telegram"
        )
    )
    return bool(
        state
        and state.enabled
        and not state.frozen
        and task.state_revision == state.revision
        and task.config_hash == state.config_hash
        and identity
        and identity.enabled
        and identity.id == task.identity_id
        and identity.external_user_id == identity.chat_id == task.chat_id
        and (grant is None or grant.enabled and task.grant_revision == grant.revision)
    )


async def expire_drafts(session, owner, state, grant):
    tasks = (
        await session.scalars(
            select(CalendarTask)
            .where(CalendarTask.owner_id == owner, CalendarTask.status == "draft")
            .with_for_update()
        )
    ).all()
    for task in tasks:
        if task.expires_at <= now_utc():
            task.status = "expired"
        elif not grant or not await task_valid(session, task, state, grant):
            task.status = "cancelled"
        else:
            continue
        task.updated_at = now_utc()
        # Retain bounded field values in task history until explicit /clear; no cloud replay.


async def route_draft(session, repo, request, state, user, grant):
    """Return False for unrelated text. State/task/action/turn commit as one transaction."""
    from jarvis.assistant.repository import deliver
    from jarvis.orchestration.calendar_chat import (
        REGISTRY,
        approval_text,
        pending_position,
        route_confirmation,
    )
    from jarvis.storage.models import ToolGrant, User

    # Same lock order as journal dispatch/grants, before locking tasks/actions.
    await session.get(User, repo.owner, with_for_update=True)
    grant = await session.get(
        ToolGrant, (repo.owner, "calendar"), with_for_update=True, populate_existing=True
    )
    await expire_drafts(session, repo.owner, state, grant)
    raw = request.prompt or ""
    ignored_note = None
    try:
        edit = parse_edit(raw, initial=True)
        if edit is None:
            edit = parse_edit(raw)
    except SlotError as error:
        salvaged = _salvage_edit(raw)
        if salvaged is None:
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(session, request, f"Calendar: {error}.")
            return True
        edit, ignored_note = salvaged
    if edit is None:
        return await route_confirmation(session, repo, request)
    if not grant or not grant.enabled or "calendar:write" not in grant.scopes:
        request.status, request.finished_at = "failed", now_utc()
        await deliver(
            session, request, "Calendar write belum diaktifkan; tidak ada tindakan dibuat."
        )
        return True
    task = None
    if edit.target:
        task = await session.get(CalendarTask, UUID(edit.target), with_for_update=True)
        if task and (
            task.bot_id != request.bot_id or task.conversation_id != state.conversation_id
        ):
            task = None
    elif not edit.initial:
        tasks = (
            await session.scalars(
                select(CalendarTask)
                .where(
                    CalendarTask.owner_id == repo.owner,
                    CalendarTask.bot_id == request.bot_id,
                    CalendarTask.conversation_id == state.conversation_id,
                    CalendarTask.status == "draft",
                )
                .with_for_update()
            )
        ).all()
        if len(tasks) > 1:
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(
                session,
                request,
                "Pilih draft: "
                + ", ".join(str(t.id) for t in tasks)
                + '\nJawab: draft ID: judul "..."; durasi 60 menit.',
            )
            return True
        task = tasks[0] if tasks else None
    if task is None and not edit.initial:
        request.status, request.finished_at = "clarified", now_utc()
        await deliver(session, request, "Draft tidak aktif/ditemukan. Mulai dengan buat rapat ...")
        return True
    if task is None:
        count = await session.scalar(
            select(func.count())
            .select_from(CalendarTask)
            .where(CalendarTask.owner_id == repo.owner, CalendarTask.status == "draft")
        )
        if count >= MAX_OPEN_DRAFTS:
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(
                session, request, "Batas 3 draft aktif; batalkan target dengan /cancel ID."
            )
            return True
        identity = await session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.owner_id == repo.owner, ExternalIdentity.channel == "telegram"
            )
        )
        origin = {"source": "owner_timezone", "value": user.timezone}
        task = CalendarTask(
            id=uuid4(),
            owner_id=repo.owner,
            bot_id=request.bot_id,
            chat_id=identity.chat_id,
            identity_id=identity.id,
            conversation_id=request.conversation_id,
            source_request_id=request.id,
            state_revision=state.revision,
            config_hash=state.config_hash,
            grant_revision=grant.revision,
            revision=1,
            channel="telegram",
            anchor_at=request.created_at,
            timezone=user.timezone,
            slots={"timezone": user.timezone, "execute_timezone": user.timezone},
            provenance={"timezone": origin, "execute_timezone": origin},
            status="draft",
            expires_at=request.created_at + DRAFT_TTL,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        session.add(task)
    else:
        if task.status not in {"draft", "submitted"} or not await task_valid(
            session, task, state, grant
        ):
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(
                session, request, "Draft selesai/kedaluwarsa atau authority berubah; buat baru."
            )
            return True
        if task.revision >= MAX_TURNS:
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(session, request, "Batas 20 turn per draft; mulai draft baru.")
            return True
    if not edit.initial and edit.short_clock and not edit.target and "start_clock" in task.slots:
        return False  # An unsolicited bare number is not an implicit time correction.
    try:
        slots, provenance = merge_slots(
            task.slots,
            edit,
            anchor=task.anchor_at,
            source_id=request.id,
            received_at=request.created_at,
            provenance=task.provenance,
        )
    except SlotError as error:
        request.status, request.finished_at = "clarified", now_utc()
        await deliver(
            session, request, f"Calendar: {error}. Draft {task.id} tetap dapat dikoreksi."
        )
        return True
    try:
        args, due, due_zone, missing = materialize(slots, now=now_utc())
    except SlotError as error:
        if task.current_action_id is None:
            task.slots, task.provenance = slots, provenance
            task.revision += 1
            task.updated_at = now_utc()
        request.status, request.finished_at = "clarified", now_utc()
        await deliver(session, request, f"Calendar: {error}. Koreksi draft {task.id}.")
        return True
    # Never cancel the old action until the proposed replacement has been validated.
    if task.current_action_id:
        old = await session.get(ToolAction, task.current_action_id, with_for_update=True)
        if old.status not in CANCELLABLE:
            request.status, request.finished_at = "clarified", now_utc()
            await deliver(
                session,
                request,
                f"Aksi {old.id} sudah {old.status}; tidak diubah/diulang. "
                "Periksa /toolstatus dan rekonsiliasi bila uncertain.",
            )
            return True
        old.status, old.finished_at = "cancelled", now_utc()
        old.lease_token = old.lease_until = None
        await session.execute(
            update(CalendarNotification)
            .where(
                CalendarNotification.owner_id == repo.owner,
                CalendarNotification.action_id == old.id,
                CalendarNotification.delivery_status == "pending",
            )
            .values(delivery_status="blocked", reply_text=None)
        )
        task.current_action_id = None
    task.revision += 1
    task.slots, task.provenance, task.timezone = slots, provenance, slots["timezone"]
    task.updated_at = now_utc()
    task.status = "draft"
    if missing:
        request.status, request.finished_at = "clarified", now_utc()
        known = "; ".join(
            f"{k}: {slots[k]}" for k in ("event_date", "start_clock", "timezone") if k in slots
        )
        text = (
            f"Draft {task.id}\nDiketahui: {known}.\n"
            + "Perlu "
            + "; ".join(missing)
            + f". Berlaku sampai {task.expires_at.isoformat()}."
        )
        if ignored_note:
            text += f"\nAbaikan: '{ignored_note}' — belum paham maksudnya."
        await deliver(session, request, text)
        return True
    count = await session.scalar(
        select(func.count())
        .select_from(CalendarTask)
        .where(CalendarTask.owner_id == repo.owner, CalendarTask.status == "submitted")
    )
    if count >= MAX_PENDING_JOBS:
        request.status, request.finished_at = "clarified", now_utc()
        await deliver(session, request, "Batas 25 job tertunda; batalkan target dahulu.")
        return True
    due = due or now_utc()
    try:
        # Final approval, not a synthetic original instruction, authorizes merged slots.
        action = await ActionJournal(repo.db, repo.owner, REGISTRY).create(
            ToolProposal("calendar_create_event", args),
            AuthorizationContext(frozenset(grant.scopes)),
            request_id=request.id,
            source_key=f"calendar-task:{task.id}:rev:{task.revision}",
            due_at=due,
            due_timezone=due_zone,
            fingerprint_version=2,
            latest_dispatch_at=due + LATE_WINDOW,
            session=session,
        )
    except ActionJournalError:
        request.status, request.finished_at = "failed", now_utc()
        await deliver(
            session, request, "Calendar ditolak karena izin/argumen berubah; koreksi draft."
        )
        return True
    task.current_action_id, task.status = action.id, "submitted"
    # Handed-off is a turn outcome, not a claim that Google has completed the job.
    request.status, request.finished_at = "handed_off", now_utc()
    position, total = await pending_position(session, repo.owner, action.id)
    body = approval_text(action, position=position, total=total)
    await deliver(session, request, f"Draft {task.id}\n" + body)
    return True


async def cancel_target(session, owner, target):
    """Cancel a concrete task/action without revoking unrelated jobs or LLM turns."""
    from jarvis.orchestration.calendar_chat import short_id

    task, action = None, None
    try:
        target_id = UUID(target)
    except (ValueError, AttributeError, TypeError):
        target_id = None
    if target_id is not None:
        task = await session.get(CalendarTask, target_id, with_for_update=True)
    if task is None and target_id is None:
        prefix = str(target or "").strip().lower().replace("-", "")
        if 8 <= len(prefix) <= 32 and all(c in "0123456789abcdef" for c in prefix):
            tasks = (
                await session.scalars(
                    select(CalendarTask).where(
                        CalendarTask.owner_id == owner,
                        CalendarTask.status.in_({"draft", "submitted"}),
                    )
                )
            ).all()
            hits = [t for t in tasks if str(t.id).replace("-", "").startswith(prefix)]
            if len(hits) == 1:
                task = hits[0]
            elif len(hits) > 1:
                return (
                    "Beberapa draft cocok awalan itu; kirim Ref 8 char yang tampil di proposal "
                    f"atau ID penuh. Cocok: {', '.join(short_id(t.id) for t in hits[:5])}."
                )
        if task is None and target_id is None:
            # Prefix action IDs (resolve_action also matches drafts above for tasks).
            from jarvis.orchestration.calendar_chat import resolve_action

            resolved = await resolve_action(session, owner, target)
            if resolved is not None:
                action = resolved
                task = await session.scalar(
                    select(CalendarTask).where(
                        CalendarTask.owner_id == owner,
                        CalendarTask.current_action_id == action.id,
                    )
                )
    if task is None and target_id is not None and action is None:
        task = await session.get(CalendarTask, target_id, with_for_update=True)
    if task:
        if task.current_action_id:
            action = await session.get(ToolAction, task.current_action_id, with_for_update=True)
        elif task.status == "draft":
            task.status, task.updated_at = "cancelled", now_utc()
            return f"Draft {short_id(task.id)} dibatalkan."
    elif action is None and target_id is not None:
        action = await session.get(ToolAction, target_id, with_for_update=True)
        if action:
            task = await session.scalar(
                select(CalendarTask).where(
                    CalendarTask.owner_id == owner, CalendarTask.current_action_id == action.id
                )
            )
    if not action or action.agent != "calendar":
        return "Target tidak ditemukan / sudah selesai. Cek Ref di proposal atau /tasks."
    if action.status not in CANCELLABLE:
        return f"{short_id(action.id)}: {action.status}; yang sudah terkirim tidak ditarik kembali."
    action.status, action.finished_at = "cancelled", now_utc()
    action.lease_token = action.lease_until = None
    if task:
        task.updated_at = now_utc()
    return f"{short_id(action.id)} dibatalkan sebelum jalan."


async def complete_tasks(session, owner, state):
    """Separate event identities for uncertain and reconciled results; receipts never recycled."""
    from jarvis.assistant.repository import authorized, telegram_text
    from jarvis.orchestration.calendar_chat import completion_text

    rows = (
        await session.execute(
            select(CalendarTask, ToolAction)
            .join(
                ToolAction,
                (ToolAction.owner_id == CalendarTask.owner_id)
                & (ToolAction.id == CalendarTask.current_action_id),
            )
            .where(
                CalendarTask.owner_id == owner,
                ToolAction.status.in_(TERMINAL),
                CalendarTask.status != ToolAction.status,
            )
            .limit(25)
        )
    ).all()
    for task, action in rows:
        valid = await task_valid(session, task, state) and await authorized(
            session, owner, task.bot_id
        )
        now = now_utc()
        await session.execute(
            insert(CalendarNotification)
            .values(
                id=uuid4(),
                owner_id=owner,
                bot_id=task.bot_id,
                chat_id=task.chat_id,
                task_id=task.id,
                action_id=action.id,
                event_key=f"{action.id}:{action.status}",
                reply_text=telegram_text(completion_text(action)) if valid else None,
                delivery_status="pending" if valid else "blocked",
                attempts=0,
                next_attempt_at=now,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["owner_id", "event_key"])
        )
        task.status, task.updated_at = action.status, now


async def revoke_tasks(session, owner, *, erase=False):
    """Called by /cancel /new /clear and config changes, under the assistant state lock."""
    await session.execute(
        update(CalendarTask)
        .where(CalendarTask.owner_id == owner, CalendarTask.status == "draft")
        .values(status="cancelled", updated_at=now_utc())
    )
    await session.execute(
        update(CalendarNotification)
        .where(
            CalendarNotification.owner_id == owner,
            CalendarNotification.delivery_status == "pending",
        )
        .values(delivery_status="blocked", reply_text=None)
    )
    if erase:
        await session.execute(
            update(CalendarTask)
            .where(
                CalendarTask.owner_id == owner,
            )
            .values(slots={}, provenance={})
        )
        await session.execute(
            update(CalendarNotification)
            .where(
                CalendarNotification.owner_id == owner,
                CalendarNotification.delivery_status != "sending",
            )
            .values(reply_text=None)
        )
