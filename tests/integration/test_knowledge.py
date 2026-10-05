"""Native PostgreSQL transactions. No real Telegram or paid model calls."""

import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_assistant import fixture, plan
from test_telegram import incoming, receipt

from jarvis.assistant.repository import now_utc
from jarvis.assistant.router import Completion
from jarvis.knowledge.config import KnowledgeError
from jarvis.knowledge.content import Segment
from jarvis.knowledge.repository import KnowledgeRepository
from jarvis.storage.models import (
    AssistantRequest,
    ConversationMessage,
    Document,
    DocumentChunk,
    LLMCall,
)

pytestmark = pytest.mark.integration


async def setup(db, tmp_path, *, premium=False):
    tg, ai = await fixture(db, premium=premium)
    repo = KnowledgeRepository(db, ai.owner, tmp_path)
    await repo.initialize()
    embed, parser, index = AsyncMock(), AsyncMock(), AsyncMock()
    embed.encode.side_effect = lambda texts: [[0.1] * 384 for _ in texts]
    parser.extract.return_value = [
        Segment("paragraf 1", "Kode proyek RAMBUTAN731 selesai Oktober.")
    ]
    return tg, ai, repo, parser, embed, index


async def ready(repo, parser, embed, index, *, data_class="private", data=b"fixture"):
    info = await repo.import_file("catatan.docx", data, data_class, "auto")
    doc = await repo.claim()
    assert doc and doc.id == info["id"]
    await repo.process(doc, parser, embed, index)
    assert (await repo.info(doc.id))["status"] == "ready"
    return doc


async def askdoc(tg, ai, repo, embed, index, doc, number=100):
    async with repo.db.tenant(repo.owner) as s:
        ids = list(
            (
                await s.scalars(select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id))
            ).all()
        )
    index.search.return_value = ids[:4]
    await tg.ingest([incoming(tg, number, f"/askdoc {doc.id} Apa kode proyek?")], "TestBot")
    assert await ai.next_request() is None
    await repo.prepare_query(embed, index)
    return await ai.prepare(await ai.next_request())


async def test_duplicate_policy_path_and_owner_isolation(test_db, tmp_path):
    _, _, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index)
    again = await repo.import_file("../../same.docx", b"fixture", "private", "auto")
    assert again["id"] == doc.id and again["duplicate"]
    with pytest.raises(KnowledgeError, match="duplicate_policy_mismatch"):
        await repo.import_file("same.docx", b"fixture", "restricted", "auto")
    _, _, other, *_ = await setup(test_db, tmp_path)
    with pytest.raises(KnowledgeError, match="document_not_found"):
        await other.info(doc.id)
    async with test_db.tenant(other.owner) as s:
        assert await s.get(Document, doc.id) is None
        assert not (await s.scalars(select(DocumentChunk))).all()
    assert repo.path(doc.id).is_file() and not (tmp_path / "same.docx").exists()


async def test_expired_lease_cannot_publish_stale_work(test_db, tmp_path):
    _, _, repo, parser, embed, index = await setup(test_db, tmp_path)
    info = await repo.import_file("a.pdf", b"fixture", "private", "never")
    old = await repo.claim()
    async with test_db.tenant(repo.owner) as s:
        (await s.get(Document, info["id"])).lease_until = now_utc() - timedelta(seconds=1)
    fresh = await repo.claim()
    assert fresh.lease_token != old.lease_token
    await repo.process(old, parser, embed, index)
    assert (await repo.info(old.id))["status"] == "processing" and not index.upsert.called
    await repo.process(fresh, parser, embed, index)
    assert (await repo.info(old.id))["status"] == "ready"


async def test_delete_during_parse_wins_and_failed_cleanup_retries(test_db, tmp_path):
    _, _, repo, parser, embed, index = await setup(test_db, tmp_path)
    await repo.import_file("a.pdf", b"fixture", "private", "auto")
    doc = await repo.claim()

    async def delete_while_parsing(*args):
        await repo.delete(doc.id)
        return [Segment("halaman 1", "Late result")]

    parser.extract.side_effect = delete_while_parsing
    await repo.process(doc, parser, embed, index)
    assert (await repo.info(doc.id))["status"] == "deleting" and not index.upsert.called
    index.delete.side_effect = KnowledgeError("local_service_unavailable")
    await repo.process(await repo.claim(), parser, embed, index)
    assert (await repo.info(doc.id))["status"] == "deleting"
    async with test_db.tenant(repo.owner) as s:
        (await s.get(Document, doc.id)).lease_until = now_utc() - timedelta(seconds=1)
    index.delete.side_effect = None
    await repo.process(await repo.claim(), parser, embed, index)
    assert (await repo.info(doc.id))["status"] == "deleted" and not repo.path(doc.id).exists()


async def test_sourced_answer_without_general_memory_contamination(test_db, tmp_path):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index)
    await tg.ingest([incoming(tg, 99, "/remember nama JANGAN_SERTAKAN")], "TestBot")
    row = await askdoc(tg, ai, repo, embed, index, doc)
    assert "JANGAN_SERTAKAN" not in str(row.messages)
    call = await ai.dispatch(row.id, plan(ai))
    await ai.finish(row.id, call, Completion("Kodenya RAMBUTAN731 [S1].", Decimal(0), 10, 5), None)
    assert "catatan.docx — paragraf 1" in (await receipt(tg)).reply_text
    async with test_db.tenant(repo.owner) as s:
        assert await s.scalar(select(func.count()).select_from(ConversationMessage)) == 0
        assert (await s.get(AssistantRequest, row.id)).status == "succeeded"


@pytest.mark.parametrize("answer", ["Tidak ada sumber.", "Salah [S99]."])
async def test_citation_failure_retains_cost_but_blocks_answer(test_db, tmp_path, answer):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index)
    row = await askdoc(tg, ai, repo, embed, index, doc)
    call = await ai.dispatch(row.id, plan(ai))
    await ai.finish(row.id, call, Completion(answer, Decimal(0), 10, 5), None)
    assert answer not in (await receipt(tg)).reply_text
    async with test_db.tenant(repo.owner) as s:
        assert (await s.get(AssistantRequest, row.id)).status == "failed"
        assert (await s.get(LLMCall, call)).status == "succeeded"


async def test_restricted_never_enters_cloud_queue(test_db, tmp_path):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index, data_class="restricted")
    await tg.ingest([incoming(tg, 100, f"/askdoc {doc.id} Apa isi?")], "TestBot")
    assert "restricted" in (await receipt(tg)).reply_text and await ai.next_request() is None
    async with test_db.tenant(repo.owner) as s:
        assert await s.scalar(select(func.count()).select_from(AssistantRequest)) == 0


async def test_forged_foreign_vector_ids_fail_database_validation(test_db, tmp_path):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index)
    _, _, other, p2, e2, i2 = await setup(test_db, tmp_path)
    await ready(other, p2, e2, i2)
    async with test_db.tenant(other.owner) as s:
        index.search.return_value = [await s.scalar(select(DocumentChunk.id)), uuid4()]
    await tg.ingest([incoming(tg, 100, f"/askdoc {doc.id} Apa isi?")], "TestBot")
    await repo.prepare_query(embed, index)
    assert await ai.next_request() is None
    assert "document_sources_unavailable" in (await receipt(tg)).reply_text
    async with test_db.tenant(repo.owner) as s:
        assert await s.scalar(select(func.count()).select_from(LLMCall)) == 0


async def test_delete_after_approval_erases_snapshot_and_cancels_dispatch(test_db, tmp_path):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path, premium=True)
    doc = await ready(repo, parser, embed, index)
    row = await askdoc(tg, ai, repo, embed, index, doc)
    premium = plan(ai, "premium")
    await ai.offer(row.id, premium)
    code = re.search(r"/approve ([a-f0-9]+)", (await receipt(tg)).reply_text)[1]
    await tg.ingest([incoming(tg, 101, "/approve " + code)], "TestBot")
    await repo.delete(doc.id)
    assert await ai.dispatch(row.id, premium) is None
    async with test_db.tenant(repo.owner) as s:
        req = await s.get(AssistantRequest, row.id)
        assert req.messages is None and req.document_sources is None and req.prompt is None
        assert await s.scalar(select(func.count()).select_from(LLMCall)) == 0
    assert (await receipt(tg)).reply_text is None


async def test_delete_inflight_discards_answer_keeps_ledger(test_db, tmp_path):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index)
    row = await askdoc(tg, ai, repo, embed, index, doc)
    call = await ai.dispatch(row.id, plan(ai))
    await tg.ingest([incoming(tg, 101, f"/deldoc {doc.id}")], "TestBot")
    await ai.finish(row.id, call, Completion("Rahasia [S1].", Decimal(0), 10, 5), None)
    assert (await receipt(tg)).reply_text is None
    async with test_db.tenant(repo.owner) as s:
        assert (await s.get(LLMCall, call)).status == "succeeded"
        assert (await s.get(AssistantRequest, row.id)).document_sources is None


async def test_failed_import_requires_explicit_retry_with_attempt_cap(test_db, tmp_path):
    _, _, repo, parser, embed, index = await setup(test_db, tmp_path)
    info = await repo.import_file("bad.pdf", b"invalid", "private", "auto")
    parser.extract.side_effect = KnowledgeError("pdf_invalid")
    for attempt in range(3):
        await repo.process(await repo.claim(), parser, embed, index)
        assert (await repo.info(info["id"]))["status"] == "failed" and await repo.claim() is None
        if attempt < 2:
            await repo.retry(info["id"])
    with pytest.raises(KnowledgeError, match="retry_limit"):
        await repo.retry(info["id"])


async def test_clear_purges_document_sources(test_db, tmp_path):
    tg, ai, repo, parser, embed, index = await setup(test_db, tmp_path)
    doc = await ready(repo, parser, embed, index)
    row = await askdoc(tg, ai, repo, embed, index, doc)
    await tg.ingest([incoming(tg, 101, "/clear")], "TestBot")
    async with test_db.tenant(repo.owner) as s:
        assert (await s.get(AssistantRequest, row.id)).document_sources is None
