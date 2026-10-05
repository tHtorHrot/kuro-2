import os
from pathlib import Path

MAX_FILE = 20 * 1024 * 1024
MAX_PAGES = 200
MAX_OCR_PAGES = 50
MAX_CHARACTERS = 500_000
MAX_CHUNKS = 1500
MAX_DOCUMENTS = 200
MAX_OWNER_BYTES = 2 * 1024**3
PARSER_SECONDS = 180
MAX_RESULT = 4 * 1024 * 1024
PIPELINE = "knowledge-1-minilm384"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION = "jarvis_knowledge_v1"
DIMENSIONS = 384
KINDS = {"pdf", "docx", "png", "jpg", "jpeg"}


class KnowledgeError(ValueError):
    """Contains a fixed code, never input text or parser stderr."""


def store_root():
    return Path(os.environ.get("JARVIS_DOCUMENT_STORE", "/data/documents"))


def model_cache():
    return Path(os.environ.get("JARVIS_EMBEDDING_CACHE", "/models"))


def file_kind(name: str) -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    if suffix not in KINDS:
        raise KnowledgeError("unsupported_file_type")
    return suffix


def display_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(c for c in name if c.isprintable() and c not in "[]")[:120].strip()
    if not name:
        raise KnowledgeError("invalid_filename")
    return name


MODEL_REPO = "qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
MODEL_REVISION = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
PARSER_CODES = frozenset(
    {
        "unsupported_file_type",
        "parser_busy",
        "file_too_large",
        "upload_timeout",
        "empty_file",
        "parser_timeout",
        "parser_resource_limit",
        "parser_failed",
        "parser_rejected",
        "parser_unavailable_or_timeout",
        "invalid_ocr_languages",
        "docx_expansion_limit",
        "unsafe_docx",
        "invalid_docx",
        "encrypted_or_invalid_pdf",
        "pdf_page_limit",
        "ocr_page_limit",
        "extracted_text_too_large",
        "invalid_file_size",
        "invalid_ocr_mode",
        "image_limit_or_type",
        "invalid_image",
        "no_extractable_text",
    }
)
