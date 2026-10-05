import logging
import sys

from jarvis.assistant.config import load_assistant_config
from jarvis.core.config import load_settings
from jarvis.core.logging import configure_logging
from jarvis.knowledge.config import MAX_FILE, MODEL, KnowledgeError, store_root
from jarvis.knowledge.repository import KnowledgeRepository
from jarvis.knowledge.services import Embeddings, Parser, VectorIndex, client
from jarvis.storage.database import Database


async def operate_knowledge(args):
    for name in ("httpx", "httpcore", "huggingface_hub"):
        logging.getLogger(name).disabled = True
    if args.command == "knowledge-model-download":
        model = Embeddings(download=True)
        rows = await model.encode(["Pemeriksaan model lokal."])
        return {
            "model": MODEL,
            "dimensions": len(rows[0]),
            "download_complete": True,
            "inference_sent": False,
            "local_embedding_computed": True,
        }
    settings, config = load_settings(), load_assistant_config()
    configure_logging(settings.log_level, settings.redacted_values())
    db = Database(settings)
    repo = KnowledgeRepository(db, config.owner_id, store_root())
    try:
        if not await db.ready():
            raise KnowledgeError("stage_3_migration_required")
        if args.command == "knowledge-run":
            from jarvis.knowledge.worker import run_worker

            await run_worker(db, config)
            return {"knowledge": "stopped"}
        if args.command in {"knowledge-status", "knowledge-health"}:
            result = await repo.status()
            if args.command == "knowledge-health" and not result["worker_recent"]:
                raise KnowledgeError("knowledge_worker_not_recent")
            return result
        if args.command == "knowledge-check":
            import io
            import zipfile

            model = Embeddings()
            vectors = await model.encode(["Kode proyek RAMBUTAN731"])
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    "<w:body><w:p><w:r><w:t>RAMBUTAN731</w:t></w:r></w:p></w:body></w:document>",
                )
            async with client() as http:
                await VectorIndex(http).ensure()
                segments = await Parser(http).extract(data.getvalue(), "docx", "auto")
            if not segments or "RAMBUTAN731" not in segments[0].text:
                raise KnowledgeError("knowledge_check_failed")
            return {
                "schema": "ready",
                "parser": "ready",
                "vector_collection": "ready",
                "embedding_dimensions": len(vectors[0]),
                "inference_sent": False,
            }
        if args.command == "documents-import":
            return await repo.import_file(
                args.filename, sys.stdin.buffer.read(MAX_FILE + 1), args.data_class, args.ocr
            )
        if args.command == "documents-list":
            return {"documents": await repo.list(), "inference_sent": False}
        if args.command == "documents-info":
            return await repo.info(args.document_id)
        if args.command == "documents-delete":
            return await repo.delete(args.document_id)
        if args.command == "documents-retry":
            return await repo.retry(args.document_id)
        raise KnowledgeError("unknown_knowledge_command")
    finally:
        await db.close()
