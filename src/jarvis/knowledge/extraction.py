"""Run only in the isolated parser container; never execute document instructions."""

import os
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from PIL import Image, UnidentifiedImageError

from jarvis.knowledge.config import (
    MAX_CHARACTERS,
    MAX_FILE,
    MAX_OCR_PAGES,
    MAX_PAGES,
    KnowledgeError,
)
from jarvis.knowledge.content import Segment, clean_text

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def command(argv, timeout=40):
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
            raise KnowledgeError("parser_rejected")
        return result.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        raise KnowledgeError("parser_unavailable_or_timeout") from None


def ocr_image(path):
    languages = os.environ.get("JARVIS_OCR_LANGUAGES", "eng+ind")
    if languages not in {"eng", "ind", "eng+ind"}:
        raise KnowledgeError("invalid_ocr_languages")
    return clean_text(command(["tesseract", str(path), "stdout", "-l", languages, "--psm", "3"]))


def docx(path):
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 512 or sum(e.file_size for e in entries) > 16 * 1024 * 1024:
                raise KnowledgeError("docx_expansion_limit")
            for e in entries:
                name = PurePosixPath(e.filename)
                if (
                    name.is_absolute()
                    or ".." in name.parts
                    or "\\" in e.filename
                    or e.flag_bits & 1
                    or "vbaproject" in e.filename.lower()
                    or (e.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise KnowledgeError("unsafe_docx")
                if e.file_size > 8 * 1024 * 1024 or e.file_size > max(1, e.compress_size) * 200:
                    raise KnowledgeError("docx_expansion_limit")
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        body = root.find(W + "body")
        if body is None:
            raise KnowledgeError("invalid_docx")
        rows, paragraph, table = [], 0, 0
        for node in body:
            if node.tag == W + "p":
                paragraph += 1
                text = "".join(t.text or "" for t in node.iter(W + "t"))
                if text.strip():
                    rows.append(Segment(f"paragraf {paragraph}", clean_text(text)))
            elif node.tag == W + "tbl":
                table += 1
                for n, tr in enumerate(node.findall(W + "tr"), 1):
                    cells = [
                        " ".join(t.text or "" for t in tc.iter(W + "t"))
                        for tc in tr.findall(W + "tc")
                    ]
                    if any(c.strip() for c in cells):
                        rows.append(
                            Segment(f"tabel {table} baris {n}", clean_text(" | ".join(cells)))
                        )
        return rows
    except KnowledgeError:
        raise
    except (BadZipFile, KeyError, ValueError, OSError, ElementTree.ParseError):
        raise KnowledgeError("invalid_docx") from None


def pdf(path, ocr):
    info = command(["pdfinfo", str(path)])
    match = re.search(r"^Pages:\s+(\d+)\s*$", info, re.M)
    if not match or re.search(r"^Encrypted:\s+yes", info, re.M):
        raise KnowledgeError("encrypted_or_invalid_pdf")
    pages = int(match[1])
    if not 1 <= pages <= MAX_PAGES:
        raise KnowledgeError("pdf_page_limit")
    rows, ocr_count, total = [], 0, 0
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, pages + 1):
            text = clean_text(
                command(
                    [
                        "pdftotext",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-layout",
                        "-enc",
                        "UTF-8",
                        str(path),
                        "-",
                    ]
                )
            )
            images = command(["pdfimages", "-f", str(page), "-l", str(page), "-list", str(path)])
            large_image = any(
                len(parts := line.split()) > 4
                and parts[0].isdigit()
                and parts[3].isdigit()
                and parts[4].isdigit()
                and int(parts[3]) >= 100
                and int(parts[4]) >= 100
                for line in images.splitlines()
            )
            used_ocr = ocr == "always" or (ocr == "auto" and (not text or large_image))
            if used_ocr:
                ocr_count += 1
                if ocr_count > MAX_OCR_PAGES:
                    raise KnowledgeError("ocr_page_limit")
                prefix = Path(tmp) / "page"
                command(
                    [
                        "pdftoppm",
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-singlefile",
                        "-scale-to",
                        "2200",
                        "-png",
                        str(path),
                        str(prefix),
                    ]
                )
                image_text = ocr_image(prefix.with_suffix(".png"))
                if image_text:
                    text = image_text if ocr == "always" or not text else text + "\n" + image_text
            if text:
                rows.append(Segment(f"halaman {page}" + (" (OCR)" if used_ocr else ""), text))
                total += len(text)
                if total > MAX_CHARACTERS:
                    raise KnowledgeError("extracted_text_too_large")
    return rows


def extract(path, kind, ocr="auto"):
    path = Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= MAX_FILE:
        raise KnowledgeError("invalid_file_size")
    if ocr not in {"auto", "always", "never"}:
        raise KnowledgeError("invalid_ocr_mode")
    if kind == "docx":
        rows = docx(path)
    elif kind == "pdf":
        rows = pdf(path, ocr)
    elif kind in {"png", "jpg", "jpeg"} and ocr != "never":
        try:
            Image.MAX_IMAGE_PIXELS = 20_000_000
            with Image.open(path) as im:
                if im.width * im.height > 20_000_000 or im.format not in {"PNG", "JPEG"}:
                    raise KnowledgeError("image_limit_or_type")
                im.load()
                im.thumbnail((2200, 2200))
                with tempfile.TemporaryDirectory() as tmp:
                    normalized = Path(tmp) / "image.png"
                    im.convert("RGB").save(normalized)
                    rows = [Segment("gambar 1 (OCR)", ocr_image(normalized))]
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise KnowledgeError("invalid_image") from None
    else:
        raise KnowledgeError("unsupported_file_type")
    if not rows or not any(r.text.strip() for r in rows):
        raise KnowledgeError("no_extractable_text")
    if sum(len(r.text) for r in rows) > MAX_CHARACTERS:
        raise KnowledgeError("extracted_text_too_large")
    return rows
