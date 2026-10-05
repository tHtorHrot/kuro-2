from uuid import uuid4

import httpx
import pytest


async def test_qdrant_search_filters_owner_and_document_and_returns_ids_only():
    from jarvis.knowledge.services import VectorIndex

    owner, doc, chunk = uuid4(), uuid4(), uuid4()

    def handler(request):
        import json

        payload = json.loads(request.content)
        assert payload["filter"]["must"] == [
            {"key": "owner_id", "match": {"value": str(owner)}},
            {"key": "document_id", "match": {"value": str(doc)}},
        ]
        assert payload["with_payload"] is False
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": [
                    {"id": str(chunk), "version": 1, "score": 0.7, "payload": None, "vector": None}
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await VectorIndex(client).search(owner, doc, [0.0] * 384) == [chunk]


@pytest.mark.parametrize(
    "result", [[{"id": "not-a-uuid", "score": 0.9}], [{"id": str(uuid4()), "score": "NaN"}], "bad"]
)
async def test_malformed_search_fails_closed(result):
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.services import VectorIndex

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"status": "ok", "result": result})
        )
    ) as client:
        with pytest.raises(KnowledgeError):
            await VectorIndex(client).search(uuid4(), uuid4(), [0.0] * 384)


async def test_qdrant_delete_waits_for_completion_and_rejects_incomplete():
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.services import VectorIndex

    def handler(request):
        assert request.url.params["wait"] == "true"
        return httpx.Response(200, json={"status": "ok", "result": {"status": "acknowledged"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KnowledgeError):
            await VectorIndex(client).delete(uuid4(), uuid4())


@pytest.mark.parametrize("result", [None, {"result": None}, {"result": []}, {"result": "private"}])
def test_vector_write_malformed_is_safe_failure(result):
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.services import VectorIndex

    with pytest.raises(KnowledgeError, match="vector_write_incomplete"):
        VectorIndex.completed(result)


@pytest.mark.parametrize(
    "code, expected",
    [("ocr_page_limit", "ocr_page_limit"), ("PRIVATE CONTENT", "local_service_unavailable")],
)
async def test_parser_error_allowlist(code, expected):
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.services import Parser

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(422, json={"code": code}))
    ) as client:
        with pytest.raises(KnowledgeError, match=expected):
            await Parser(client).extract(b"fixture", "pdf", "auto")


def test_tampered_model_is_rejected_before_loading(tmp_path, monkeypatch):
    import huggingface_hub

    from jarvis.knowledge.config import MODEL_REVISION, KnowledgeError
    from jarvis.knowledge.services import Embeddings

    (tmp_path / "config.json").write_text("tampered")

    def snapshot(**kwargs):
        assert kwargs["revision"] == MODEL_REVISION and kwargs["local_files_only"] is True
        return str(tmp_path)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)
    with pytest.raises(KnowledgeError, match="checksum_mismatch"):
        Embeddings()


async def test_parser_http_returns_docx_text_and_rejects_unknown_type():
    from test_knowledge_extraction import docx_bytes

    from jarvis.knowledge.parser_app import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://parser"
    ) as c:
        assert (await c.post("/extract?kind=exe", content=b"bad")).status_code == 400
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Hello source</w:t></w:r></w:p></w:body></w:document>"
        )
        response = await c.post("/extract?kind=docx", content=docx_bytes(xml))
        assert response.status_code == 200
        assert response.json()["segments"] == [{"locator": "paragraf 1", "text": "Hello source"}]
