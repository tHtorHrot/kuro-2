import asyncio
import hashlib
import json as json_module
import math
from importlib.resources import files
from pathlib import Path
from uuid import UUID

import httpx

from jarvis.knowledge.config import (
    COLLECTION,
    DIMENSIONS,
    MAX_RESULT,
    MODEL,
    MODEL_REPO,
    MODEL_REVISION,
    PARSER_CODES,
    KnowledgeError,
    model_cache,
)
from jarvis.knowledge.content import Segment


def client():
    return httpx.AsyncClient(
        timeout=httpx.Timeout(200, connect=5), trust_env=False, follow_redirects=False
    )


class Embeddings:
    def __init__(self, *, download=False):
        from fastembed import TextEmbedding
        from huggingface_hub import snapshot_download

        try:
            manifest = json_module.loads(
                files("jarvis.knowledge").joinpath("model_manifest.json").read_text()
            )
            path = snapshot_download(
                repo_id=MODEL_REPO,
                revision=MODEL_REVISION,
                cache_dir=str(model_cache()),
                allow_patterns=list(manifest),
                local_files_only=not download,
            )
            for name, expected in manifest.items():
                with (Path(path) / name).open("rb") as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != expected:
                    raise KnowledgeError("embedding_model_checksum_mismatch")
            self.model = TextEmbedding(
                model_name=MODEL,
                cache_dir=str(model_cache()),
                specific_model_path=path,
                local_files_only=True,
                threads=1,
                providers=["CPUExecutionProvider"],
            )
        except KnowledgeError:
            raise
        except Exception:
            raise KnowledgeError("embedding_model_unavailable_run_model_download") from None

    async def encode(self, texts):
        def run():
            return [row.tolist() for row in self.model.embed(texts, batch_size=8, parallel=None)]

        try:
            rows = await asyncio.to_thread(run)
            if len(rows) != len(texts):
                raise KnowledgeError("embedding_invalid")
            for row in rows:
                validate_vector(row)
            return rows
        except KnowledgeError:
            raise
        except Exception:
            raise KnowledgeError("embedding_failed") from None


def validate_vector(vector):
    if len(vector) != DIMENSIONS or any(
        type(v) not in {int, float} or not math.isfinite(v) for v in vector
    ):
        raise KnowledgeError("embedding_invalid")


async def request_json(http, method, url, *, json=None, content=None, error_codes=frozenset()):
    try:
        async with http.stream(method, url, json=json, content=content) as response:
            raw = bytearray()
            async for part in response.aiter_bytes():
                raw.extend(part)
                if len(raw) > MAX_RESULT:
                    raise KnowledgeError("local_service_response_too_large")
            result = json_module.loads(raw)
            if response.status_code != 200:
                code = result.get("code") if isinstance(result, dict) else None
                if isinstance(code, str) and code in error_codes:
                    raise KnowledgeError(code)
                raise KnowledgeError("local_service_unavailable")
            return result
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, KnowledgeError):
            raise
        raise KnowledgeError("local_service_invalid_response") from None


class Parser:
    def __init__(self, http):
        self.http = http

    async def extract(self, data, kind, ocr):
        result = await request_json(
            self.http,
            "POST",
            f"http://document-parser:8080/extract?kind={kind}&ocr={ocr}",
            content=data,
            error_codes=PARSER_CODES,
        )
        try:
            rows = result["segments"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= 10_000:
                raise ValueError
            segments = [Segment(r["locator"], r["text"]) for r in rows]
            if any(
                type(s.locator) is not str
                or not 1 <= len(s.locator) <= 120
                or type(s.text) is not str
                for s in segments
            ):
                raise ValueError
            return segments
        except (KeyError, TypeError, ValueError):
            raise KnowledgeError("parser_invalid_response") from None


class VectorIndex:
    def __init__(self, http):
        self.http = http
        self.base = f"http://qdrant:6333/collections/{COLLECTION}"

    @staticmethod
    def scope(owner, document):
        return {
            "must": [
                {"key": "owner_id", "match": {"value": str(owner)}},
                {"key": "document_id", "match": {"value": str(document)}},
            ]
        }

    async def ensure(self):
        # Deterministic collection name and shape; an existing different shape is rejected.
        async with self.http.stream("GET", self.base) as response:
            status = response.status_code
        if status == 404:
            await request_json(
                self.http,
                "PUT",
                self.base,
                json={"vectors": {"size": DIMENSIONS, "distance": "Cosine"}},
            )
        result = await request_json(self.http, "GET", self.base)
        try:
            params = result["result"]["config"]["params"]["vectors"]
            if params["size"] != DIMENSIONS or params["distance"] != "Cosine":
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise KnowledgeError("vector_schema_mismatch") from None

    async def upsert(self, owner, document, chunks, vectors):
        if len(chunks) != len(vectors):
            raise KnowledgeError("embedding_invalid")
        for start in range(0, len(chunks), 32):
            points = []
            for chunk, vector in zip(
                chunks[start : start + 32], vectors[start : start + 32], strict=True
            ):
                validate_vector(vector)
                points.append(
                    {
                        "id": str(chunk.id),
                        "vector": vector,
                        "payload": {"owner_id": str(owner), "document_id": str(document)},
                    }
                )
            result = await request_json(
                self.http, "PUT", self.base + "/points?wait=true", json={"points": points}
            )
            self.completed(result)

    @staticmethod
    def completed(result):
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("result"), dict)
            or result["result"].get("status") != "completed"
        ):
            raise KnowledgeError("vector_write_incomplete")

    async def delete(self, owner, document):
        result = await request_json(
            self.http,
            "POST",
            self.base + "/points/delete?wait=true",
            json={"filter": self.scope(owner, document)},
        )
        self.completed(result)

    async def search(self, owner, document, vector):
        validate_vector(vector)
        result = await request_json(
            self.http,
            "POST",
            self.base + "/points/search",
            json={
                "vector": vector,
                "filter": self.scope(owner, document),
                "limit": 4,
                "with_payload": False,
                "with_vector": False,
                "score_threshold": 0.25,
            },
        )
        try:
            rows = result["result"]
            if not isinstance(rows, list) or len(rows) > 4:
                raise ValueError
            ids = []
            for row in rows:
                if type(row["score"]) not in {int, float} or not math.isfinite(row["score"]):
                    raise ValueError
                ids.append(UUID(row["id"]))
            return list(dict.fromkeys(ids))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise KnowledgeError("vector_response_invalid") from None
