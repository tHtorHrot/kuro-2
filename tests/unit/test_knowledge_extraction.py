import io
import os
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


def docx_bytes(xml, extra=None):
    data = io.BytesIO()
    with ZipFile(data, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
        if extra:
            z.writestr(*extra)
    return data.getvalue()


def test_docx_has_paragraph_and_table_sources(tmp_path):
    from jarvis.knowledge.extraction import extract

    path = tmp_path / "input.docx"
    path.write_bytes(
        docx_bytes(
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>Rencana kegiatan</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Biaya</w:t></w:r></w:p></w:tc>
<w:tc><w:p><w:r><w:t>5000</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
        )
    )
    rows = extract(path, "docx", "auto")
    assert [(r.locator, r.text) for r in rows] == [
        ("paragraf 1", "Rencana kegiatan"),
        ("tabel 1 baris 1", "Biaya | 5000"),
    ]


@pytest.mark.parametrize(
    "extra",
    [("../outside", "bad"), ("word/huge.xml", "A" * 3_000_000), ("word/vbaProject.bin", "macro")],
)
def test_docx_rejects_traversal_expansion_bomb_and_macro(tmp_path, extra):
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.extraction import extract

    path = tmp_path / "bad.docx"
    path.write_bytes(docx_bytes("<document/>", extra))
    with pytest.raises(KnowledgeError):
        extract(path, "docx", "auto")


def test_malformed_pdf_is_rejected_without_echoing_content(tmp_path):
    from jarvis.knowledge.config import KnowledgeError
    from jarvis.knowledge.extraction import extract

    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.7\nPRIVATE-CONTENT-NOT-FOR-LOGS")
    with pytest.raises(KnowledgeError) as error:
        extract(path, "pdf", "auto")
    assert "PRIVATE" not in str(error.value)


def test_real_image_ocr_and_scanned_pdf(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw, ImageFont

    from jarvis.knowledge.extraction import extract

    if not shutil.which("tesseract") or not shutil.which("pdftoppm"):
        if os.environ.get("JARVIS_REQUIRE_INTEGRATION") == "1":
            pytest.fail("Poppler/Tesseract required by the Docker gate")
        pytest.skip("Poppler/Tesseract required; provided in Docker test image")
    monkeypatch.setenv("JARVIS_OCR_LANGUAGES", "eng")
    im = Image.new("RGB", (1400, 400), "white")
    font = ImageFont.truetype("DejaVuSans.ttf", 60)
    ImageDraw.Draw(im).text((40, 100), "DOCUMENT CODE RAMBUTAN 731", font=font, fill="black")
    png, pdf = tmp_path / "scan.png", tmp_path / "scan.pdf"
    im.save(png)
    im.save(pdf, "PDF", resolution=150)
    assert "RAMBUTAN 731" in extract(png, "png", "auto")[0].text
    rows = extract(pdf, "pdf", "auto")
    assert rows[0].locator == "halaman 1 (OCR)"
    assert "RAMBUTAN 731" in rows[0].text
