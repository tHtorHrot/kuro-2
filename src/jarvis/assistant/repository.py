"""Domain transactions: RLS, immutable context, one-use approval and budget reservation."""

import hmac
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from jarvis.assistant.commands import INFERENCE_COMMANDS, SLASH_COMMANDS
from jarvis.assistant.config import AssistantConfig
from jarvis.assistant.policy import (
    SYSTEM_PROMPT,
    PolicyError,
    consent_digest,
    digest,
    money,
    safe_content,
    validate_messages,
)
from jarvis.assistant.router import Completion, RouterError, request_payload
from jarvis.core.config import ConfigurationError
from jarvis.identity.service import audit
from jarvis.storage.models import (
    AssistantRequest,
    AssistantState,
    ConversationMessage,
    ExternalIdentity,
    LLMCall,
    ProfileMemory,
    TelegramReceipt,
    TelegramState,
    ToolAction,
    User,
)

ACTIVE = ("queued", "preparing", "awaiting_approval", "approved", "dispatching")
COMMANDS = SLASH_COMMANDS  # Compatibility for existing transport consumers.
RETENTION = timedelta(days=30)
TERMINAL_REQUEST_STATUSES = ("succeeded", "failed", "cancelled", "uncertain")


def split_ledger(calls) -> dict:
    """Pure ledger split: actual spend vs held reservation. No DB, no secrets."""
    actual, held, by_status = Decimal(0), Decimal(0), {}
    for status, actual_usd, reserved_usd in calls:
        by_status[status] = by_status.get(status, 0) + 1
        if status == "succeeded" and actual_usd is not None:
            actual += actual_usd
        elif status in {"dispatching", "uncertain"}:
            held += reserved_usd or Decimal(0)
    return {
        "month_actual_usd": str(actual),
        "month_held_usd": str(held),
        "calls": by_status,
        "unreconciled": sum(by_status.get(s, 0) for s in ("dispatching", "uncertain")),
    }


def now_utc():
    return datetime.now(UTC)


def telegram_text(value: str) -> str:
    if len(value.encode("utf-16-le")) <= 7600:
        return value
    return (
        value.encode("utf-16-le")[:7300].decode("utf-16-le", errors="ignore")
        + "\n[Jawaban dipotong.]"
    )


def set_reply(receipt: TelegramReceipt, content: str | None):
    receipt.reply_kind, receipt.requires_pairing = "assistant", True
    receipt.reply_text = telegram_text(content) if content else None
    receipt.delivery_status = "pending" if content else "waiting"
    receipt.next_attempt_at = now_utc()


async def owner_state(session, owner_id):
    return await session.scalar(
        select(AssistantState).where(AssistantState.owner_id == owner_id).with_for_update()
    )


async def authorized(session, owner_id, bot_id=None) -> bool:
    user = await session.get(User, owner_id)
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.owner_id == owner_id, ExternalIdentity.channel == "telegram"
        )
    )
    tg = await session.get(TelegramState, owner_id)
    return bool(
        user
        and user.status == "active"
        and identity
        and identity.enabled
        and identity.chat_id == identity.external_user_id
        and tg
        and (bot_id is None or tg.bot_id == bot_id)
    )


async def deliver(session, request: AssistantRequest, text: str):
    row = await session.get(
        TelegramReceipt, (request.owner_id, request.bot_id, request.reply_update_id)
    )
    # Never turn an already sent/uncertain receipt back into a new send.
    if row and row.delivery_status == "waiting":
        set_reply(row, text)


async def cancel_pending(session, state, *, erase=False):
    from jarvis.orchestration.calendar_tasks import revoke_tasks

    # Detached jobs are outside ACTIVE; cancel them before revoking the revision.
    await session.get(User, state.owner_id, with_for_update=True)
    actions = (
        await session.scalars(
            select(ToolAction)
            .where(
                ToolAction.owner_id == state.owner_id,
                ToolAction.request_id.is_not(None),
                ToolAction.status.in_({"queued", "claimed", "awaiting_approval"}),
            )
            .with_for_update()
        )
    ).all()
    for action in actions:
        action.status, action.finished_at = "cancelled", now_utc()
        action.lease_token = action.lease_until = None
        audit(session, state.owner_id, "tool_action.cancelled", action.id)
    await revoke_tasks(session, state.owner_id, erase=erase)
    rows = (
        await session.scalars(
            select(AssistantRequest).where(
                AssistantRequest.owner_id == state.owner_id, AssistantRequest.status.in_(ACTIVE)
            )
        )
    ).all()
    for row in rows:
        actions = (
            await session.scalars(
                select(ToolAction)
                .where(
                    ToolAction.owner_id == state.owner_id,
                    ToolAction.request_id == row.id,
                    ToolAction.status.in_({"queued", "claimed", "awaiting_approval"}),
                )
                .with_for_update()
            )
        ).all()
        for action in actions:
            action.status, action.finished_at = "cancelled", now_utc()
            action.lease_token = action.lease_until = None
            audit(session, state.owner_id, "tool_action.cancelled", action.id)
        row.status, row.finished_at, row.approval_digest = "cancelled", now_utc(), None
        await deliver(session, row, "Permintaan dibatalkan karena konteks atau pengaturan berubah.")
    state.revision += 1
    if erase:
        await session.execute(
            delete(ConversationMessage).where(ConversationMessage.owner_id == state.owner_id)
        )
        await session.execute(
            update(AssistantRequest)
            .where(AssistantRequest.owner_id == state.owner_id)
            .values(prompt=None, messages=None, document_sources=None)
        )
        # Remove local copies of dynamic replies, including consent codes and profile displays.
        await session.execute(
            update(TelegramReceipt)
            .where(
                TelegramReceipt.owner_id == state.owner_id,
                TelegramReceipt.reply_kind.in_(["assistant", "knowledge"]),
                TelegramReceipt.delivery_status != "sending",
            )
            .values(reply_text=None, delivery_status="blocked")
        )


async def handle_command(session, owner_id, bot_id, incoming, receipt, pepper: str):
    """Called inside Telegram cursor/receipt transaction, after owner and sender checks."""
    state = await owner_state(session, owner_id)
    cmd, arg = incoming.command, incoming.argument or ""
    if cmd == "restricted":
        set_reply(
            receipt,
            (
                "Data restricted tidak diproses lewat cloud. Jangan kirim data "
                "sensitif melalui Telegram."
            ),
        )
        return
    if state is None:
        set_reply(receipt, "AI belum disiapkan. Jalankan setup dan assistant-enable di komputer.")
        return
    if cmd in {"docs", "doc", "askdoc", "deldoc"}:
        from jarvis.knowledge.commands import handle_document_command

        await handle_document_command(session, owner_id, bot_id, incoming, receipt, state)
        return
    if cmd == "ai":
        set_reply(
            receipt,
            f"AI {'aktif' if state.enabled and not state.frozen else 'nonaktif'}. "
            "Kirim pesan biasa atau /ask TEKS. Premium meminta persetujuan per panggilan.",
        )
        return
    active = await session.scalar(
        select(AssistantRequest).where(
            AssistantRequest.owner_id == owner_id, AssistantRequest.status.in_(ACTIVE)
        )
    )
    if cmd == "cancel" and arg:
        from jarvis.orchestration.calendar_tasks import cancel_target

        await session.get(User, owner_id, with_for_update=True)
        set_reply(receipt, await cancel_target(session, owner_id, arg))
        return
    if cmd in {"new", "clear", "cancel"}:
        await cancel_pending(session, state, erase=cmd == "clear")
        if cmd in {"new", "clear"}:
            state.conversation_id = uuid4()
        set_reply(
            receipt,
            {
                "new": "Percakapan baru dimulai. Profil tersimpan tetap digunakan.",
                "clear": (
                    "Isi percakapan, snapshot dan balasan AI lokal dibersihkan. "
                    "Profil, audit biaya, backup dan salinan Telegram tetap ada."
                ),
                "cancel": (
                    "Permintaan tertunda dibatalkan. Panggilan yang sudah terkirim "
                    "tidak dapat ditarik kembali."
                ),
            }[cmd],
        )
        return
    if cmd == "memory":
        from jarvis.memory.service import active_project, live_condition

        current = await active_project(session, owner_id)
        rows = (
            await session.scalars(
                select(ProfileMemory)
                .where(ProfileMemory.owner_id == owner_id)
                .where(live_condition())
                .order_by(ProfileMemory.kind, ProfileMemory.key)
            )
        ).all()

        def show(row):
            scope = row.project or "global"
            value = row.value if row.data_class == "private" else "[restricted]"
            return f"{row.key} [{row.kind}/{scope}]: {value}"

        if current:
            mine = [r for r in rows if r.project == current]
            other = [r for r in rows if r.project not in (None, current)]
            body = "Proyek {}:\n{}\n\nGlobal:\n{}".format(
                current,
                "\n".join(show(r) for r in mine) if mine else "(kosong)",
                "\n".join(show(r) for r in rows if r.project is None) or "(kosong)",
            )
            if other:
                body += "\n\nProyek lain: " + ", ".join(
                    sorted({r.project for r in other if r.project})
                )
        else:
            body = "Profil tersimpan:\n" + "\n".join(show(r) for r in rows)
        set_reply(
            receipt,
            body if rows else "Profil belum berisi fakta. /remember kunci nilai untuk menyimpan.",
        )
        return
    if cmd in {"remember", "forget"}:
        from jarvis.memory.service import active_project

        scope = arg
        project = None
        if scope.startswith("@"):
            head, _, tail = scope[1:].partition(" ")
            project, scope = head, tail
        parts = scope.split(maxsplit=1)
        key = parts[0] if parts else ""
        if project is None and cmd == "remember":
            project = await active_project(session, owner_id)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key):
            set_reply(
                receipt, "Kunci harus huruf kecil/angka/underscore, diawali huruf (maks. 40)."
            )
            return
        if cmd == "forget":
            from jarvis.memory.service import apply_forget

            await apply_forget(session, owner_id, key)
            await cancel_pending(session, state)
            set_reply(
                receipt,
                (
                    "Fakta profil dihapus; riwayat lama masih ada. Gunakan /clear "
                    "untuk membersihkan riwayat lokal."
                ),
            )
            return
        value = parts[1] if len(parts) == 2 else ""
        if not safe_content(value) or len(value) > 500:
            set_reply(
                receipt, "Nilai profil harus 1–500 karakter tanpa kredensial atau data restricted."
            )
            return
        from jarvis.memory.repository import MemoryFact, MemoryPolicyError
        from jarvis.memory.service import apply_fact, live_condition

        count = await session.scalar(
            select(func.count())
            .select_from(ProfileMemory)
            .where(ProfileMemory.owner_id == owner_id)
            .where(live_condition())
        )
        row = await session.get(ProfileMemory, (owner_id, key))
        if row is None and count >= 20:
            set_reply(receipt, "Batas 20 fakta profil tercapai. Hapus dengan /forget kunci.")
            return
        try:
            await apply_fact(
                session,
                owner_id,
                MemoryFact(
                    key=key, value=value, provenance="user:telegram", source="user", project=project
                ),
            )
        except MemoryPolicyError:
            set_reply(receipt, "Proyek tidak terdaftar. Daftarkan dulu: /project-add nama.")
            return
        await cancel_pending(session, state)
        where = f" di proyek {project}" if project else ""
        set_reply(
            receipt,
            f"Fakta disimpan{where}. Nilainya akan disertakan dalam percakapan AI berikutnya.",
        )
        audit(session, owner_id, "memory.updated", None)
        return
    if cmd in {"project", "project-add", "project-del"}:
        from jarvis.memory.service import (
            active_project,
            delete_project,
            list_projects,
            register_project,
            set_active_project,
        )

        if cmd == "project" and not arg:
            names = await list_projects(session, owner_id)
            current = await active_project(session, owner_id)
            text = "Proyek aktif: {}\nDaftar: {}\nGanti: /project nama.".format(
                current or "(tidak ada — semua global)",
                ", ".join(names) if names else "(belum ada)",
            )
            set_reply(receipt, text + " Baru: /project-add nama.")
            return
        if cmd == "project-add":
            try:
                await register_project(session, owner_id, arg)
            except ValueError:
                set_reply(receipt, "Nama tidak valid / sudah ada / batas 20 tercapai.")
                return
            set_reply(receipt, f"Proyek {arg} terdaftar.")
            return
        if cmd == "project-del":
            try:
                await delete_project(session, owner_id, arg)
            except ValueError as exc:
                set_reply(
                    receipt,
                    {
                        "project_is_active": "Masih aktif; pindah dulu.",
                        "project_has_facts": "Masih ada fakta; /forget dulu.",
                    }.get(
                        str(exc),
                        "Proyek tidak ditemukan.",
                    ),
                )
                return
            set_reply(receipt, f"Proyek {arg} dihapus.")
            return
        try:
            await set_active_project(session, owner_id, arg)
        except ValueError:
            set_reply(receipt, "Proyek tidak terdaftar. Lihat: /project.")
            return
        set_reply(receipt, f"Proyek aktif: {arg}. /memory kini memilah ruang ini.")
        return
    if (
        not state.enabled
        or state.frozen
        or not state.last_poll_at
        or now_utc() - state.last_poll_at > timedelta(seconds=120)
    ):
        set_reply(receipt, "Worker AI belum aktif/siap. Periksa assistant-status di komputer.")
        return
    if cmd == "approve":
        if not active or active.status != "awaiting_approval" or not active.approval_digest:
            set_reply(receipt, "Tidak ada persetujuan premium yang dapat digunakan.")
            return
        if (
            active.approval_expires_at <= now_utc()
            or active.revision != state.revision
            or active.config_hash != state.config_hash
            or active.approval_attempts >= 5
        ):
            active.status, active.approval_digest = "cancelled", None
            active.finished_at = now_utc()
            set_reply(receipt, "Persetujuan kedaluwarsa atau konteks berubah. Kirim /ask baru.")
            return
        expected = consent_digest(arg, active.id, active.context_hash, digest(active.plan), pepper)
        if not hmac.compare_digest(expected, active.approval_digest):
            active.approval_attempts += 1
            if active.approval_attempts >= 5:
                active.status, active.approval_digest = "cancelled", None
                active.finished_at = now_utc()
            set_reply(receipt, "Kode persetujuan tidak sah.")
            return
        active.status, active.approved_at = "approved", now_utc()
        active.reply_update_id = incoming.update_id
        active.approval_digest = None  # consumes code; POST consumes authorization separately
        set_reply(receipt, None)
        audit(session, owner_id, "inference.approved", active.id)
        return
    if cmd == "toolapprove":
        from jarvis.orchestration.calendar_chat import approve_from_chat

        await approve_from_chat(session, owner_id, incoming, receipt)
        return
    if cmd == "toolstatus":
        from jarvis.orchestration.calendar_chat import resolve_action, short_id

        action = await resolve_action(session, owner_id, arg)
        if not action or action.agent != "calendar":
            set_reply(
                receipt,
                "Tindakan tidak ditemukan. Cek Ref 8 char di proposal, atau /toolstatus ID penuh.",
            )
        else:
            event_id = (action.result or {}).get("id") if isinstance(action.result, dict) else None
            set_reply(
                receipt,
                f"{short_id(action.id)}: {action.status}."
                + (f" Event: {short_id(event_id)}." if event_id else ""),
            )
        return
    if cmd in {"tasks", "task", "goal"}:
        from jarvis.interfaces.telegram.task_commands import handle_task_command

        await handle_task_command(session, owner_id, incoming, receipt)
        return
    if cmd in INFERENCE_COMMANDS:
        if active:
            set_reply(receipt, "Masih ada satu permintaan berjalan. Tunggu atau gunakan /cancel.")
        elif not safe_content(arg) or len(arg) > 3000:
            set_reply(receipt, "Pertanyaan harus 1–3000 karakter tanpa kredensial/data restricted.")
        else:
            session.add(
                AssistantRequest(
                    owner_id=owner_id,
                    bot_id=bot_id,
                    source_update_id=incoming.update_id,
                    reply_update_id=incoming.update_id,
                    conversation_id=state.conversation_id,
                    revision=state.revision,
                    config_hash=state.config_hash,
                    prompt=arg,
                    created_at=now_utc(),
                    status="queued",
                )
            )
            set_reply(receipt, None)
        return
    set_reply(receipt, "Perintah AI tidak dikenali. Gunakan /help.")


class AssistantRepository:
    def __init__(self, db, config: AssistantConfig):
        self.db, self.config, self.owner = db, config, config.owner_id

    async def route_tool(self, request_id):
        from jarvis.orchestration.calendar_chat import route_request

        return await route_request(self, request_id)

    def valid(self, state, request):
        return (
            state
            and state.enabled
            and not state.frozen
            and state.config_hash == self.config.fingerprint
            and request.config_hash == state.config_hash
            and request.revision == state.revision
        )

    async def initialize(self):
        async with self.db.tenant(self.owner) as session:
            if not await authorized(session, self.owner):
                raise ConfigurationError("Active owner with paired Telegram identity required")
            await session.execute(
                insert(AssistantState)
                .values(
                    owner_id=self.owner,
                    conversation_id=uuid4(),
                    config_hash=self.config.fingerprint,
                    revision=1,
                    enabled=False,
                    frozen=False,
                )
                .on_conflict_do_nothing()
            )
            state = await owner_state(session, self.owner)
            if state.config_hash != self.config.fingerprint:
                await cancel_pending(session, state)
                state.config_hash, state.enabled = self.config.fingerprint, False
            # Only called with exclusive assistant lock. Never replay an in-flight POST.
            calls = (
                await session.scalars(
                    select(LLMCall).where(
                        LLMCall.owner_id == self.owner, LLMCall.status == "dispatching"
                    )
                )
            ).all()
            for call in calls:
                call.status, call.finished_at = "uncertain", now_utc()
                req = await session.get(AssistantRequest, call.request_id)
                if req.status in ACTIVE:
                    req.status, req.finished_at = "uncertain", now_utc()
                    await deliver(
                        session,
                        req,
                        (
                            "Panggilan sebelumnya terputus; hasil/biaya belum pasti. Tidak "
                            "dikirim ulang otomatis."
                        ),
                    )
            await session.execute(
                update(AssistantRequest)
                .where(
                    AssistantRequest.owner_id == self.owner, AssistantRequest.status == "preparing"
                )
                .values(status="queued")
            )
            state.last_poll_at = now_utc()
            from jarvis.orchestration.calendar_chat import deliver_completed

            await deliver_completed(session, self.owner, state)

    async def heartbeat(self):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            if state is None or state.config_hash != self.config.fingerprint:
                raise ConfigurationError("Assistant configuration changed; restart worker")
            state.last_poll_at = now_utc()
            from jarvis.orchestration.calendar_chat import deliver_completed

            await deliver_completed(session, self.owner, state)
            from jarvis.orchestration.calendar_tasks import expire_drafts
            from jarvis.storage.models import ToolGrant

            grant = await session.get(ToolGrant, (self.owner, "calendar"))
            await expire_drafts(session, self.owner, state, grant)
            expired = (
                await session.scalars(
                    select(AssistantRequest).where(
                        AssistantRequest.owner_id == self.owner,
                        AssistantRequest.status.in_(
                            ["queued", "preparing", "awaiting_approval", "approved"]
                        ),
                        AssistantRequest.created_at < now_utc() - timedelta(minutes=8),
                    )
                )
            ).all()
            for row in expired:
                row.status, row.finished_at, row.approval_digest = "cancelled", now_utc(), None
                await deliver(
                    session, row, "Permintaan kedaluwarsa; kirim /ask baru bila masih diperlukan."
                )

    async def next_request(self):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            if not state or not state.enabled or state.frozen:
                return None
            return await session.scalar(
                select(AssistantRequest.id)
                .where(
                    AssistantRequest.owner_id == self.owner,
                    AssistantRequest.status.in_(["queued", "approved"]),
                    or_(
                        AssistantRequest.document_id.is_(None),
                        AssistantRequest.document_sources.is_not(None),
                    ),
                )
                .order_by(AssistantRequest.created_at)
                .limit(1)
            )

    async def prepare(self, request_id):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            row = await session.get(AssistantRequest, request_id)
            if not row or row.status not in {"queued", "approved"}:
                return None
            if not self.valid(state, row) or not await authorized(session, self.owner, row.bot_id):
                row.status, row.finished_at = "cancelled", now_utc()
                await deliver(session, row, "Permintaan dibatalkan: izin atau konteks berubah.")
                return None
            if row.document_id is not None:
                from jarvis.knowledge.content import sourced_messages
                from jarvis.knowledge.repository import validate_document

                await validate_document(session, row)
                if row.messages is None:
                    messages = sourced_messages(row.prompt, row.document_sources)
                    row.messages, row.context_hash = messages, digest(messages)
            if row.messages is None:
                from jarvis.memory.repository import MAX_CONTEXT_CHARS, rank_facts
                from jarvis.memory.service import active_project, live_condition

                current_project = await active_project(session, self.owner)
                profile = (
                    await session.scalars(
                        select(ProfileMemory)
                        .where(ProfileMemory.owner_id == self.owner)
                        .where(live_condition())
                        .order_by(ProfileMemory.key)
                    )
                ).all()
                if any(p.data_class != "private" for p in profile):
                    # Fail closed rather than silently downgrading a restricted fact.
                    raise PolicyError("restricted_profile")
                selected = rank_facts(
                    [
                        {
                            "key": p.key,
                            "value": p.value,
                            "kind": p.kind,
                            "importance": p.importance,
                            "updated_at": p.updated_at,
                            "data_class": p.data_class,
                            "project": p.project,
                            "status": p.status,
                            "expires_at": p.expires_at,
                        }
                        for p in profile
                    ],
                    budget_chars=MAX_CONTEXT_CHARS,
                    project=current_project,
                )
                history = (
                    await session.scalars(
                        select(ConversationMessage)
                        .where(
                            ConversationMessage.owner_id == self.owner,
                            ConversationMessage.conversation_id == row.conversation_id,
                            ConversationMessage.created_at > now_utc() - RETENTION,
                        )
                        .order_by(
                            ConversationMessage.created_at.desc(), ConversationMessage.id.desc()
                        )
                        .limit(12)
                    )
                ).all()
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                if selected:
                    messages.append(
                        {
                            "role": "user",
                            "content": "Fakta profil yang saya simpan: "
                            + json.dumps(
                                {f["key"]: f["value"] for f in selected}, ensure_ascii=False
                            ),
                        }
                    )
                messages.extend({"role": r.role, "content": r.content} for r in reversed(history))
                messages.append({"role": "user", "content": row.prompt})
                validate_messages(messages, row.data_class)
                row.messages, row.context_hash = messages, digest(messages)
            if row.status == "queued":
                row.status = "preparing"
            return row

    async def spent(self, session):
        month = now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return await session.scalar(
            select(
                func.coalesce(func.sum(func.coalesce(LLMCall.actual_usd, LLMCall.reserved_usd)), 0)
            ).where(LLMCall.owner_id == self.owner, LLMCall.created_at >= month)
        )

    async def offer(self, request_id, plan):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            row = await session.get(AssistantRequest, request_id)
            if not row or row.status != "preparing" or not self.valid(state, row):
                return False
            from jarvis.knowledge.repository import validate_document

            await validate_document(session, row)
            if (
                await self.spent(session) + money(plan["reserve_usd"])
                > self.config.monthly_budget_usd
            ):
                raise PolicyError("monthly_budget_exceeded")
            request_payload(plan, row.messages, row.data_class)
            code = secrets.token_hex(12)
            row.plan, row.status = plan, "awaiting_approval"
            row.approval_expires_at = now_utc() + timedelta(minutes=5)
            row.approval_digest = consent_digest(
                code,
                row.id,
                row.context_hash,
                digest(plan),
                self.db.settings.token_pepper.get_secret_value(),
            )
            await deliver(
                session,
                row,
                "Model gratis tidak tersedia dengan syarat saat ini.\n"
                f"Premium: {plan['model']} via {plan['provider']}\n"
                f"Reservasi maksimum: USD {plan['reserve_usd']} (bukan perkiraan tagihan).\n"
                f"Output maksimum: {plan['max_tokens']} token. Konteks tetap sama.\n"
                f"Setujui SATU panggilan dalam 5 menit: /approve {code}\n"
                "Atau /cancel. Kegagalan tidak diulang otomatis.",
            )
            audit(session, self.owner, "inference.consent_requested", row.id)
            return True

    async def dispatch(self, request_id, plan):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            row = await session.get(AssistantRequest, request_id)
            if not row or row.status not in {"preparing", "approved"} or not self.valid(state, row):
                return None
            if not await authorized(session, self.owner, row.bot_id):
                raise PolicyError("authorization_changed")
            from jarvis.knowledge.repository import validate_document

            await validate_document(session, row)
            if (
                row.context_hash != digest(row.messages)
                or plan["config_hash"] != self.config.fingerprint
            ):
                raise PolicyError("context_changed")
            request_payload(plan, row.messages, row.data_class)
            kind = plan["kind"]
            existing = await session.scalar(
                select(LLMCall).where(
                    LLMCall.owner_id == self.owner,
                    LLMCall.request_id == row.id,
                    LLMCall.kind == kind,
                )
            )
            if existing:
                raise PolicyError("attempt_already_used")
            cap = money(plan["reserve_usd"])
            if kind == "premium":
                if (
                    not self.config.premium_enabled
                    or row.status != "approved"
                    or not row.approved_at
                    or row.consumed_at
                    or row.approval_expires_at <= now_utc()
                    or plan != row.plan
                    or cap > self.config.per_call_budget_usd
                ):
                    raise PolicyError("fresh_consent_required")
                if await self.spent(session) + cap > self.config.monthly_budget_usd:
                    raise PolicyError("monthly_budget_exceeded")
                row.consumed_at = now_utc()
            else:
                if row.status != "preparing" or cap != 0:
                    raise PolicyError("free_route_has_cost")
                day = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
                count = await session.scalar(
                    select(func.count())
                    .select_from(LLMCall)
                    .where(
                        LLMCall.owner_id == self.owner,
                        LLMCall.kind == "free",
                        LLMCall.created_at >= day,
                    )
                )
                if count >= self.config.daily_free_calls:
                    raise PolicyError("daily_free_limit")
            call = LLMCall(
                owner_id=self.owner,
                request_id=row.id,
                kind=kind,
                model=plan["model"],
                provider=plan["provider"],
                status="dispatching",
                reserved_usd=cap,
                created_at=now_utc(),
            )
            session.add(call)
            row.plan, row.status = plan, "dispatching"
            await session.flush()
            audit(session, self.owner, "inference.dispatched", call.id)
            return call.id

    async def finish(
        self, request_id, call_id, result: Completion | None, error: RouterError | None
    ):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            row = await session.get(AssistantRequest, request_id)
            call = await session.get(LLMCall, call_id)
            if not call or call.status != "dispatching":
                return False
            call.finished_at = now_utc()
            if result:
                call.status, call.actual_usd = "succeeded", result.cost
                call.prompt_tokens, call.completion_tokens = (
                    result.prompt_tokens,
                    result.completion_tokens,
                )
            else:
                call.status = "uncertain" if error is None or error.uncertain else "rejected"
                # Only known pre-inference rejections release budget.
                if call.status == "rejected":
                    call.actual_usd = Decimal(0)
                if error and error.kind in {"policy_violation", "unverifiable_response"}:
                    state.frozen, state.enabled = True, False
            if not self.valid(state, row) or row.status != "dispatching":
                if row.status == "dispatching":
                    row.status, row.finished_at = "failed", now_utc()
                    await deliver(
                        session,
                        row,
                        (
                            "AI dihentikan karena hasil/biaya tidak dapat diverifikasi. "
                            "Periksa assistant-status."
                        ),
                    )
                return False
            if result:
                output = telegram_text(result.content)
                if row.document_id is not None:
                    from jarvis.knowledge.content import format_answer
                    from jarvis.knowledge.repository import validate_document

                    try:
                        await validate_document(session, row)
                        output = format_answer(result.content, row.document_sources)
                        if not safe_content(output):
                            raise PolicyError("document_context_blocked")
                    except PolicyError as exc:
                        row.status, row.finished_at = "failed", now_utc()
                        await deliver(
                            session,
                            row,
                            f"Jawaban dokumen diblokir. Kode: {exc}. "
                            "Tidak ada pengulangan otomatis.",
                        )
                        return False
                    row.status, row.finished_at = "succeeded", now_utc()
                    await deliver(session, row, output)
                    audit(session, self.owner, "inference.succeeded", row.id)
                    return False
                if not safe_content(output):
                    row.status, row.finished_at = "failed", now_utc()
                    await deliver(
                        session,
                        row,
                        (
                            "Jawaban diblokir karena menyerupai kredensial. Tidak disimpan "
                            "sebagai memory."
                        ),
                    )
                    return False
                row.status, row.finished_at = "succeeded", now_utc()
                for role, content, order in (("user", row.prompt, 0), ("assistant", output, 1)):
                    session.add(
                        ConversationMessage(
                            owner_id=self.owner,
                            conversation_id=row.conversation_id,
                            request_id=row.id,
                            role=role,
                            content=content,
                            created_at=now_utc() + timedelta(microseconds=order),
                        )
                    )
                await deliver(session, row, output)
                audit(session, self.owner, "inference.succeeded", row.id)
                return False
            if call.kind == "free" and call.status == "rejected":
                row.status = "preparing"
                return True  # May offer a fresh premium quote; never execute it here.
            row.status, row.finished_at = (
                call.status if call.status == "uncertain" else "failed",
                now_utc(),
            )
            await deliver(
                session,
                row,
                (
                    "Panggilan gagal atau hasilnya belum pasti. Tidak diulang "
                    "otomatis; reservasi biaya yang belum pasti tetap ditahan."
                ),
            )
            return False

    async def fail(self, request_id, reason="unavailable"):
        async with self.db.tenant(self.owner) as session:
            await owner_state(session, self.owner)
            row = await session.get(AssistantRequest, request_id)
            if row and row.status in {"queued", "preparing", "approved", "awaiting_approval"}:
                row.status, row.finished_at, row.approval_digest = "failed", now_utc(), None
                if reason == "daily_free_limit":
                    day = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
                    used = (
                        await session.scalar(
                            select(func.count())
                            .select_from(LLMCall)
                            .where(
                                LLMCall.owner_id == self.owner,
                                LLMCall.kind == "free",
                                LLMCall.created_at >= day,
                            )
                        )
                        or 0
                    )
                    limit = self.config.daily_free_calls
                    reset = (day + timedelta(days=1)).strftime("%H:%M UTC")
                    text = (
                        "Jatah gratis harian habis "
                        f"({used}/{limit}). Reset {reset} (~07:00 WIB). "
                        f"Kode: {reason}. Tidak ada panggilan premium otomatis."
                    )
                else:
                    text = (
                        "AI belum dapat memproses permintaan dengan aturan privasi/biaya "
                        f"saat ini. Kode: {reason}. Tidak ada panggilan premium otomatis."
                    )
                await deliver(session, row, text)

    async def prune(self):
        async with self.db.tenant(self.owner) as session:
            await owner_state(session, self.owner)
            cutoff = now_utc() - RETENTION
            old = (
                select(ConversationMessage.id)
                .where(
                    ConversationMessage.owner_id == self.owner,
                    ConversationMessage.created_at < cutoff,
                )
                .limit(1000)
            )
            await session.execute(
                delete(ConversationMessage).where(ConversationMessage.id.in_(old))
            )
            old_requests = (
                select(AssistantRequest.id)
                .where(
                    AssistantRequest.owner_id == self.owner,
                    AssistantRequest.created_at < cutoff,
                    AssistantRequest.status.not_in(ACTIVE),
                    or_(
                        AssistantRequest.messages.is_not(None),
                        AssistantRequest.prompt.is_not(None),
                        AssistantRequest.document_sources.is_not(None),
                    ),
                )
                .limit(1000)
            )
            await session.execute(
                update(AssistantRequest)
                .where(AssistantRequest.id.in_(old_requests))
                .values(prompt=None, messages=None, document_sources=None, approval_digest=None)
            )

    async def status(self):
        async with self.db.tenant(self.owner) as session:
            state = await session.get(AssistantState, self.owner)
            recent = bool(
                state
                and state.last_poll_at
                and now_utc() - state.last_poll_at < timedelta(seconds=120)
            )
            counts = (
                await session.execute(
                    select(AssistantRequest.status, func.count())
                    .where(AssistantRequest.owner_id == self.owner)
                    .group_by(AssistantRequest.status)
                )
            ).all()
            month = now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            call_rows = (
                await session.execute(
                    select(LLMCall.status, LLMCall.actual_usd, LLMCall.reserved_usd).where(
                        LLMCall.owner_id == self.owner, LLMCall.created_at >= month
                    )
                )
            ).all()
            ledger = split_ledger(call_rows)
            day = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_free_used = (
                await session.scalar(
                    select(func.count())
                    .select_from(LLMCall)
                    .where(
                        LLMCall.owner_id == self.owner,
                        LLMCall.kind == "free",
                        LLMCall.created_at >= day,
                    )
                )
                or 0
            )
            recent_terminal = (
                await session.scalars(
                    select(AssistantRequest)
                    .where(
                        AssistantRequest.owner_id == self.owner,
                        AssistantRequest.status.in_(TERMINAL_REQUEST_STATUSES),
                    )
                    .order_by(AssistantRequest.finished_at.desc())
                    .limit(5)
                )
            ).all()
            return {
                "stage": "3",
                "configured": state is not None,
                "enabled": bool(state and state.enabled),
                "frozen": bool(state and state.frozen),
                "worker_recent": recent,
                "config_matches": bool(state and state.config_hash == self.config.fingerprint),
                "premium_enabled": self.config.premium_enabled,
                "premium_mode": "confirm_each_use",
                "monthly_budget_usd": str(self.config.monthly_budget_usd),
                "month_spent_or_held_usd": str(await self.spent(session)),
                "month_actual_usd": ledger["month_actual_usd"],
                "month_held_usd": ledger["month_held_usd"],
                "unreconciled_calls": ledger["unreconciled"],
                "calls": ledger["calls"],
                "daily_free_used": daily_free_used,
                "daily_free_limit": self.config.daily_free_calls,
                "recent_terminal": [
                    {
                        "status": row.status,
                        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    }
                    for row in recent_terminal
                ],
                "requests": dict(counts),
            }
