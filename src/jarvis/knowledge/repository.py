"""PostgreSQL is authoritative; parser output and vector IDs are untrusted inputs."""

import hashlib
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from jarvis.assistant.policy import PolicyError
from jarvis.assistant.repository import ACTIVE, authorized, deliver, now_utc, owner_state
from jarvis.identity.service import audit
from jarvis.knowledge.config import (
    MAX_DOCUMENTS,
    MAX_FILE,
    MAX_OWNER_BYTES,
    PIPELINE,
    KnowledgeError,
    display_name,
    file_kind,
)
from jarvis.knowledge.content import chunk_segments, sourced_messages
from jarvis.storage.models import (
    AssistantRequest,
    ConversationMessage,
    Document,
    DocumentChunk,
    KnowledgeState,
    TelegramReceipt,
)

LEASE = timedelta(minutes=10)


def metadata(row):
    return {
        "id": row.id,
        "title": row.title,
        "kind": row.kind,
        "data_class": row.data_class,
        "status": row.status,
        "bytes": row.byte_size,
        "chunks": row.chunk_count,
        "attempts": row.attempts,
        "ocr": row.ocr,
        "error_code": row.error_code,
        "pipeline": row.pipeline,
    }


async def request_delete(session, owner, document_id):
    """Caller holds AssistantState lock, shared with AI dispatch and finish."""
    row = await session.scalar(
        select(Document)
        .where(Document.owner_id == owner, Document.id == document_id)
        .with_for_update()
    )
    if not row:
        raise KnowledgeError("document_not_found")
    if row.status == "deleted":
        return
    row.status, row.updated_at, row.lease_until = "deleting", now_utc(), None
    row.lease_token, row.error_code = None, None
    requests = (
        await session.scalars(
            select(AssistantRequest).where(
                AssistantRequest.owner_id == owner, AssistantRequest.document_id == document_id
            )
        )
    ).all()
    for req in requests:
        if req.status in ACTIVE:
            req.status, req.finished_at = "cancelled", now_utc()
        req.prompt = req.messages = req.document_sources = req.approval_digest = None
        req.context_hash = None
    request_ids = [r.id for r in requests]
    if request_ids:
        await session.execute(
            delete(ConversationMessage).where(
                ConversationMessage.owner_id == owner,
                ConversationMessage.request_id.in_(request_ids),
            )
        )
    receipt_ids = {n for r in requests for n in (r.source_update_id, r.reply_update_id)}
    # Metadata lists can mention several documents; purge their ephemeral local copies too.
    receipts = (
        await session.scalars(
            select(TelegramReceipt).where(
                TelegramReceipt.owner_id == owner,
                or_(
                    TelegramReceipt.update_id.in_(receipt_ids),
                    TelegramReceipt.reply_kind == "knowledge",
                ),
            )
        )
    ).all()
    for receipt in receipts:
        receipt.reply_text = None
        if receipt.delivery_status != "sending":
            receipt.delivery_status = "blocked"
    audit(session, owner, "document.delete_requested", document_id)


async def validate_document(session, request):
    if request.document_id is None:
        return
    doc = await session.get(Document, request.document_id)
    if (
        not doc
        or doc.owner_id != request.owner_id
        or doc.status != "ready"
        or doc.data_class != "private"
    ):
        raise PolicyError("document_unavailable")
    sources = request.document_sources
    if not sources or not 1 <= len(sources) <= 4:
        raise PolicyError("document_sources_unavailable")
    try:
        ids = [UUID(s["chunk_id"]) for s in sources]
        chunks = {
            c.id: c
            for c in (
                await session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.owner_id == request.owner_id,
                        DocumentChunk.document_id == doc.id,
                        DocumentChunk.id.in_(ids),
                    )
                )
            ).all()
        }
        if len(chunks) != len(ids):
            raise ValueError
        for number, source in enumerate(sources, 1):
            chunk = chunks[UUID(source["chunk_id"])]
            if source != {
                "label": f"S{number}",
                "document_id": str(doc.id),
                "chunk_id": str(chunk.id),
                "title": doc.title,
                "locator": chunk.locator,
                "text": chunk.content,
            }:
                raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise PolicyError("document_sources_changed") from None


class KnowledgeRepository:
    def __init__(self, db, owner, store):
        self.db, self.owner, self.store = db, owner, Path(store)

    def path(self, document_id):
        if not isinstance(document_id, UUID):
            raise KnowledgeError("invalid_document_id")
        folder = self.store / str(self.owner)
        result = folder / str(document_id)
        if self.store.is_symlink() or folder.is_symlink() or result.is_symlink():
            raise KnowledgeError("unsafe_document_path")
        return result

    async def initialize(self):
        async with self.db.tenant(self.owner) as session:
            if not await authorized(session, self.owner):
                raise KnowledgeError("active_paired_owner_required")
            if await owner_state(session, self.owner) is None:
                raise KnowledgeError("assistant_setup_required")
            await session.execute(
                insert(KnowledgeState).values(owner_id=self.owner).on_conflict_do_nothing()
            )
        await self.heartbeat()

    async def heartbeat(self):
        async with self.db.tenant(self.owner) as session:
            await session.execute(
                update(KnowledgeState)
                .where(KnowledgeState.owner_id == self.owner)
                .values(last_poll_at=now_utc())
            )

    async def import_file(self, filename, data, data_class, ocr):
        kind, title = file_kind(filename), display_name(filename)
        if data_class not in {"private", "restricted"} or ocr not in {"auto", "always", "never"}:
            raise KnowledgeError("invalid_document_policy")
        if not 0 < len(data) <= MAX_FILE:
            raise KnowledgeError("file_size_invalid")
        sha, created_path = hashlib.sha256(data).hexdigest(), None
        try:
            async with self.db.tenant(self.owner) as session:
                if await owner_state(session, self.owner) is None or not await authorized(
                    session, self.owner
                ):
                    raise KnowledgeError("active_paired_owner_required")
                existing = await session.scalar(
                    select(Document).where(
                        Document.owner_id == self.owner,
                        Document.sha256 == sha,
                        Document.pipeline == PIPELINE,
                        Document.status != "deleted",
                    )
                )
                if existing:
                    if (existing.data_class, existing.ocr, existing.kind) != (
                        data_class,
                        ocr,
                        kind,
                    ):
                        raise KnowledgeError("duplicate_policy_mismatch")
                    return {**metadata(existing), "duplicate": True}
                count, size = (
                    await session.execute(
                        select(func.count(), func.coalesce(func.sum(Document.byte_size), 0)).where(
                            Document.owner_id == self.owner, Document.status != "deleted"
                        )
                    )
                ).one()
                if count >= MAX_DOCUMENTS or size + len(data) > MAX_OWNER_BYTES:
                    raise KnowledgeError("document_storage_quota")
                doc = Document(
                    id=uuid4(),
                    owner_id=self.owner,
                    title=title,
                    kind=kind,
                    data_class=data_class,
                    sha256=sha,
                    pipeline=PIPELINE,
                    ocr=ocr,
                    status="queued",
                    byte_size=len(data),
                    attempts=0,
                    chunk_count=0,
                )
                path = self.path(doc.id)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                created_path = path
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                session.add(doc)
                await session.flush()
                audit(session, self.owner, "document.imported", doc.id)
                result = {**metadata(doc), "duplicate": False}
            return result
        except BaseException:
            if created_path:
                created_path.unlink(missing_ok=True)
            raise

    async def info(self, document_id):
        async with self.db.tenant(self.owner) as session:
            row = await session.get(Document, document_id)
            if not row:
                raise KnowledgeError("document_not_found")
            return metadata(row)

    async def list(self):
        async with self.db.tenant(self.owner) as session:
            return [
                metadata(row)
                for row in (
                    await session.scalars(
                        select(Document)
                        .where(Document.owner_id == self.owner, Document.status != "deleted")
                        .order_by(Document.created_at.desc())
                        .limit(MAX_DOCUMENTS)
                    )
                ).all()
            ]

    async def status(self):
        async with self.db.tenant(self.owner) as session:
            state = await session.get(KnowledgeState, self.owner)
            counts = (
                await session.execute(
                    select(Document.status, func.count())
                    .where(Document.owner_id == self.owner)
                    .group_by(Document.status)
                )
            ).all()
            return {
                "stage": "3",
                "worker_recent": bool(
                    state
                    and state.last_poll_at
                    and now_utc() - state.last_poll_at < timedelta(seconds=120)
                ),
                "documents": dict(counts),
                "pipeline": PIPELINE,
                "inference_sent": False,
            }

    async def delete(self, document_id):
        async with self.db.tenant(self.owner) as session:
            await owner_state(session, self.owner)
            await request_delete(session, self.owner, document_id)
        return await self.info(document_id)

    async def retry(self, document_id):
        async with self.db.tenant(self.owner) as session:
            await owner_state(session, self.owner)
            row = await session.get(Document, document_id)
            if not row:
                raise KnowledgeError("document_not_found")
            if row.attempts >= 3:
                raise KnowledgeError("retry_limit")
            if row.status != "failed":
                raise KnowledgeError("document_not_failed")
            row.status, row.error_code, row.lease_until = "queued", None, None
        return await self.info(document_id)

    async def claim(self):
        async with self.db.tenant(self.owner) as session:
            await owner_state(session, self.owner)
            due = or_(Document.lease_until.is_(None), Document.lease_until < now_utc())
            row = await session.scalar(
                select(Document)
                .where(
                    Document.owner_id == self.owner,
                    or_(
                        and_(Document.status == "deleting", due),
                        Document.status == "queued",
                        and_(Document.status == "processing", due),
                    ),
                )
                .order_by((Document.status == "deleting").desc(), Document.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not row:
                return None
            if row.status != "deleting":
                if not await authorized(session, self.owner):
                    return None
                if row.attempts >= 3:
                    row.status, row.error_code = "failed", "retry_limit"
                    return None
                row.status, row.attempts = "processing", row.attempts + 1
            row.lease_token, row.lease_until, row.updated_at = uuid4(), now_utc() + LEASE, now_utc()
            await session.flush()
            return row

    async def current(self, doc):
        async with self.db.tenant(self.owner) as session:
            row = await session.get(Document, doc.id)
            return bool(
                row
                and row.status == doc.status
                and row.lease_token == doc.lease_token
                and row.lease_until
                and row.lease_until > now_utc()
            )

    async def process(self, doc, parser, embed, index, check=None):
        if doc is None or not await self.current(doc):
            return
        try:
            if check:
                await check()
            if doc.status == "deleting":
                await index.delete(self.owner, doc.id)
                self.path(doc.id).unlink(missing_ok=True)
                async with self.db.tenant(self.owner) as session:
                    await owner_state(session, self.owner)
                    row = await session.get(Document, doc.id)
                    if row.status != "deleting" or row.lease_token != doc.lease_token:
                        return
                    await session.execute(
                        delete(DocumentChunk).where(
                            DocumentChunk.owner_id == self.owner,
                            DocumentChunk.document_id == doc.id,
                        )
                    )
                    row.status, row.title, row.sha256 = "deleted", "[deleted]", None
                    row.byte_size = row.chunk_count = 0
                    row.lease_until = row.lease_token = row.error_code = None
                    row.updated_at = now_utc()
                return
            with self.path(doc.id).open("rb") as stream:
                data = stream.read(MAX_FILE + 1)
            if len(data) != doc.byte_size or hashlib.sha256(data).hexdigest() != doc.sha256:
                raise KnowledgeError("document_source_changed")
            chunks = chunk_segments(await parser.extract(data, doc.kind, doc.ocr))
            if not await self.current(doc):
                return
            vectors = await embed.encode([c.text for c in chunks])
            if check:
                await check()
            rows = [
                DocumentChunk(
                    id=uuid5(doc.id, f"{doc.lease_token}:{n}"),
                    owner_id=self.owner,
                    document_id=doc.id,
                    ordinal=n,
                    locator=c.locator,
                    content=c.text,
                )
                for n, c in enumerate(chunks)
            ]
            async with self.db.tenant(self.owner) as session:
                await owner_state(session, self.owner)
                row = await session.get(Document, doc.id)
                if row.status != "processing" or row.lease_token != doc.lease_token:
                    return
                await session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.owner_id == self.owner, DocumentChunk.document_id == doc.id
                    )
                )
                session.add_all(rows)
            await index.delete(self.owner, doc.id)
            if not await self.current(doc):
                return
            await index.upsert(self.owner, doc.id, rows, vectors)
            if check:
                await check()
            async with self.db.tenant(self.owner) as session:
                await owner_state(session, self.owner)
                row = await session.get(Document, doc.id)
                if (
                    row.status == "processing"
                    and row.lease_token == doc.lease_token
                    and row.lease_until > now_utc()
                ):
                    row.status, row.chunk_count, row.error_code = "ready", len(rows), None
                    row.lease_until = row.lease_token = None
                    row.updated_at = now_utc()
                    audit(session, self.owner, "document.ready", doc.id)
        except (KnowledgeError, OSError) as exc:
            code = str(exc) if isinstance(exc, KnowledgeError) else "document_storage_unavailable"
            async with self.db.tenant(self.owner) as session:
                await owner_state(session, self.owner)
                row = await session.get(Document, doc.id)
                if row.lease_token == doc.lease_token:
                    row.error_code, row.updated_at = code, now_utc()
                    row.lease_until = now_utc() + timedelta(seconds=30)
                    if row.status == "processing":
                        row.status = "failed"

    @staticmethod
    def query_allowed(state, req):
        return bool(
            state
            and state.enabled
            and not state.frozen
            and state.config_hash == req.config_hash
            and state.revision == req.revision
        )

    async def prepare_query(self, embed, index, check=None):
        async with self.db.tenant(self.owner) as session:
            state = await owner_state(session, self.owner)
            req = await session.scalar(
                select(AssistantRequest)
                .where(
                    AssistantRequest.owner_id == self.owner,
                    AssistantRequest.status == "queued",
                    AssistantRequest.document_id.is_not(None),
                    AssistantRequest.document_sources.is_(None),
                )
                .order_by(AssistantRequest.created_at)
                .limit(1)
            )
            if not req or not self.query_allowed(state, req):
                return
            doc = await session.get(Document, req.document_id)
            permitted = (
                doc
                and doc.status == "ready"
                and doc.data_class == "private"
                and await authorized(session, self.owner, req.bot_id)
            )
            question, request_id, document_id = req.prompt, req.id, req.document_id
        try:
            if not permitted:
                raise KnowledgeError("document_unavailable")
            vectors = await embed.encode([question])
            ids = await index.search(self.owner, document_id, vectors[0])
            if check:
                await check()
            async with self.db.tenant(self.owner) as session:
                state = await owner_state(session, self.owner)
                req, doc = (
                    await session.get(AssistantRequest, request_id),
                    await session.get(Document, document_id),
                )
                if (
                    req.status != "queued"
                    or req.document_sources is not None
                    or not self.query_allowed(state, req)
                ):
                    return
                if (
                    not doc
                    or doc.status != "ready"
                    or doc.data_class != "private"
                    or not await authorized(session, self.owner, req.bot_id)
                ):
                    raise KnowledgeError("document_unavailable")
                chunks = {
                    c.id: c
                    for c in (
                        await session.scalars(
                            select(DocumentChunk).where(
                                DocumentChunk.owner_id == self.owner,
                                DocumentChunk.document_id == document_id,
                                DocumentChunk.id.in_(ids),
                            )
                        )
                    ).all()
                }
                if not ids or any(i not in chunks for i in ids):
                    raise KnowledgeError("document_sources_unavailable")
                sources = [
                    {
                        "label": f"S{n}",
                        "document_id": str(document_id),
                        "chunk_id": str(i),
                        "title": doc.title,
                        "locator": chunks[i].locator,
                        "text": chunks[i].content,
                    }
                    for n, i in enumerate(ids, 1)
                ]
                sourced_messages(question, sources)
                req.document_sources = sources
        except (KnowledgeError, PolicyError) as exc:
            async with self.db.tenant(self.owner) as session:
                await owner_state(session, self.owner)
                req = await session.get(AssistantRequest, request_id)
                if req.status == "queued":
                    req.status, req.finished_at = "failed", now_utc()
                    await deliver(
                        session,
                        req,
                        f"Dokumen belum dapat digunakan. Kode: {exc}. Tidak ada panggilan AI.",
                    )

    async def prune_orphans(self):
        folder = self.path(uuid4()).parent
        if not folder.exists():
            return
        cutoff = (now_utc() - timedelta(days=1)).timestamp()
        for number, path in enumerate(folder.iterdir()):
            if number >= 1000:
                break
            try:
                doc_id = UUID(path.name)
            except ValueError:
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            async with self.db.tenant(self.owner) as session:
                if await session.get(Document, doc_id) is None:
                    path.unlink(missing_ok=True)
