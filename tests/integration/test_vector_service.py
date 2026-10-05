"""Real Qdrant REST gate in isolated compose.test.yaml; no cloud inference."""

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from jarvis.knowledge.config import COLLECTION, KnowledgeError
from jarvis.knowledge.services import VectorIndex, client

pytestmark = pytest.mark.integration


async def test_real_qdrant_owner_document_scope_and_completed_deletion():
    if os.environ.get("JARVIS_TEST_QDRANT") != "1":
        if os.environ.get("JARVIS_REQUIRE_INTEGRATION") == "1":
            pytest.fail("JARVIS_TEST_QDRANT=1 and isolated qdrant service are required")
        pytest.skip("Isolated native Qdrant not configured")
    owner, other, doc, foreign_doc = uuid4(), uuid4(), uuid4(), uuid4()
    chunks = [SimpleNamespace(id=uuid4()) for _ in range(3)]
    vector = [1.0] + [0.0] * 383
    async with client() as http:
        index = VectorIndex(http)
        if url := os.environ.get("JARVIS_TEST_QDRANT_URL"):
            index.base = url.rstrip("/") + "/collections/" + COLLECTION
        for attempt in range(40):
            try:
                await index.ensure()
                break
            except (httpx.HTTPError, KnowledgeError):
                if attempt == 39:
                    raise
                await asyncio.sleep(0.5)
        try:
            await index.upsert(owner, doc, chunks[:1], [vector])
            await index.upsert(other, doc, chunks[1:2], [vector])
            await index.upsert(owner, foreign_doc, chunks[2:], [vector])
            assert await index.search(owner, doc, vector) == [chunks[0].id]
            await index.delete(owner, doc)
            assert await index.search(owner, doc, vector) == []
            assert await index.search(other, doc, vector) == [chunks[1].id]
        finally:
            await index.delete(owner, doc)
            await index.delete(other, doc)
            await index.delete(owner, foreign_doc)
