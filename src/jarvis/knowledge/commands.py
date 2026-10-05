from datetime import timedelta
from uuid import UUID

from sqlalchemy import select

from jarvis.assistant.policy import safe_content
from jarvis.assistant.repository import ACTIVE, now_utc, set_reply
from jarvis.knowledge.repository import request_delete
from jarvis.storage.models import AssistantRequest, Document, KnowledgeState


def reply(receipt, value):
    set_reply(receipt, value)
    receipt.reply_kind = "knowledge"


async def handle_document_command(session, owner, bot_id, incoming, receipt, state):
    command, arg = incoming.command, incoming.argument or ""
    if command == "docs":
        rows = (
            await session.scalars(
                select(Document)
                .where(Document.owner_id == owner, Document.status != "deleted")
                .order_by(Document.created_at.desc())
                .limit(20)
            )
        ).all()
        lines = [
            f"{r.id}\n{r.title if r.data_class == 'private' else '[restricted]'} — {r.status}"
            for r in rows
        ]
        reply(
            receipt,
            "Dokumen (maks. 20 terbaru):\n" + "\n".join(lines) + "\n/doc UUID untuk detail."
            if rows
            else "Belum ada dokumen. Impor dari komputer memakai scripts/documents.py.",
        )
        return
    parts = arg.split(maxsplit=1)
    try:
        document_id = UUID(parts[0])
    except (IndexError, ValueError):
        reply(
            receipt, "Gunakan /doc UUID, /deldoc UUID, atau /askdoc UUID PERTANYAAN. ID di /docs."
        )
        return
    doc = await session.get(Document, document_id)
    if not doc or doc.owner_id != owner or doc.status == "deleted":
        reply(receipt, "Dokumen tidak ditemukan.")
        return
    if command == "deldoc":
        await request_delete(session, owner, document_id)
        reply(
            receipt,
            "Dokumen dikeluarkan dari pencarian; penghapusan file dan indeks mengantre. "
            "Cek status di komputer. Salinan Telegram, provider, dan backup tidak terhapus.",
        )
        return
    if command == "doc":
        title = doc.title if doc.data_class == "private" else "[restricted]"
        reply(
            receipt,
            f"{doc.id}\n{title}\nStatus: {doc.status}; kelas: {doc.data_class}; "
            f"chunk: {doc.chunk_count}; OCR: {doc.ocr}.\nKode: {doc.error_code or 'none'}.\n"
            f"/askdoc {doc.id} PERTANYAAN",
        )
        return
    if doc.data_class != "private":
        reply(receipt, "Dokumen restricted tidak dikirim ke AI cloud. Tidak ada panggilan AI.")
        return
    knowledge = await session.get(KnowledgeState, owner)
    cutoff = now_utc() - timedelta(seconds=120)
    if (
        doc.status != "ready"
        or not knowledge
        or not knowledge.last_poll_at
        or knowledge.last_poll_at < cutoff
        or not state.enabled
        or state.frozen
        or not state.last_poll_at
        or state.last_poll_at < cutoff
    ):
        reply(
            receipt,
            "Dokumen atau worker belum siap. Cek /doc UUID dan knowledge-status di komputer.",
        )
        return
    question = parts[1].strip() if len(parts) == 2 else ""
    if not safe_content(question) or len(question) > 3000:
        reply(receipt, "Pertanyaan harus 1–3000 karakter tanpa kredensial/data restricted.")
        return
    active = await session.scalar(
        select(AssistantRequest.id)
        .where(AssistantRequest.owner_id == owner, AssistantRequest.status.in_(ACTIVE))
        .limit(1)
    )
    if active:
        reply(receipt, "Masih ada satu permintaan berjalan. Tunggu atau gunakan /cancel.")
        return
    session.add(
        AssistantRequest(
            owner_id=owner,
            bot_id=bot_id,
            source_update_id=incoming.update_id,
            reply_update_id=incoming.update_id,
            conversation_id=state.conversation_id,
            revision=state.revision,
            config_hash=state.config_hash,
            prompt=question,
            document_id=document_id,
            created_at=now_utc(),
            status="queued",
        )
    )
    set_reply(receipt, None)
