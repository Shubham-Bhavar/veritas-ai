"""Upload validation and extraction edge cases."""
import io
import time
import zipfile

import pymupdf
import pytest

from app.errors import IngestError
from app.ingest.extract import extract
from app.ingest.injection import scan_text
from app.ingest.pipeline import ingest
from app.ingest.validate import detect
from tests.conftest import DEMO, new_id

MB = 1024 * 1024


def test_empty_file_rejected():
    with pytest.raises(IngestError) as e:
        detect("empty.pdf", b"", 25 * MB)
    assert e.value.code == "EMPTY_FILE"


def test_unsupported_extension_rejected():
    with pytest.raises(IngestError) as e:
        detect("payload.exe", b"MZ\x90\x00", 25 * MB)
    assert e.value.code == "UNSUPPORTED_TYPE"


def test_content_must_match_extension():
    png = (DEMO / "Income_Certificate_Priya_Sharma.png").read_bytes()
    with pytest.raises(IngestError) as e:
        detect("renamed.pdf", png, 25 * MB)
    assert e.value.code in ("TYPE_MISMATCH", "CORRUPTED_FILE")


def test_oversized_file_rejected():
    with pytest.raises(IngestError) as e:
        detect("big.txt", b"a" * (2 * MB + 1), 2 * MB)
    assert e.value.code == "FILE_TOO_LARGE"


def test_corrupted_pdf_rejected():
    with pytest.raises(IngestError) as e:
        extract("pdf", b"%PDF-1.7\n this is not really a pdf \x00\x01", 300)
    assert e.value.code in ("CORRUPTED_FILE", "NO_TEXT")


def test_corrupted_docx_rejected():
    with pytest.raises(IngestError) as e:
        detect("broken.docx", b"PK\x03\x04garbage-not-a-zip", 25 * MB)
    assert e.value.code == "CORRUPTED_FILE"


def test_zip_that_is_not_docx_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(IngestError) as e:
        detect("archive.docx", buf.getvalue(), 25 * MB)
    assert e.value.code == "UNSUPPORTED_TYPE"


def test_binary_text_file_rejected():
    with pytest.raises(IngestError) as e:
        detect("notes.txt", b"abc\x00\x00\x01def", 25 * MB)
    assert e.value.code == "CORRUPTED_FILE"


def test_pdf_without_text_and_without_images_rejected():
    doc = pymupdf.open()
    doc.new_page()
    with pytest.raises(IngestError) as e:
        extract("pdf", doc.tobytes(), 300)
    assert e.value.code == "NO_TEXT"


def test_blank_scan_reports_ocr_failure():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (255, 255, 255)).save(buf, "PNG")
    with pytest.raises(IngestError) as e:
        extract("image", buf.getvalue(), 300)
    assert e.value.code == "OCR_NO_TEXT"


def test_encrypted_pdf_rejected():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret text " * 20)
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(IngestError) as e:
        extract("pdf", data, 300)
    assert e.value.code == "ENCRYPTED"


def test_page_limit_enforced():
    doc = pymupdf.open()
    for _ in range(5):
        doc.new_page().insert_text((72, 72), "Some text on this page that is long enough.")
    with pytest.raises(IngestError) as e:
        extract("pdf", doc.tobytes(), 3)
    assert e.value.code == "TOO_MANY_PAGES"


def test_pdf_sections_pages_and_running_headers():
    ex = extract("pdf", (DEMO / "Scholarship_Guidelines_2026.pdf").read_bytes(), 300)
    headings = [b.text for b in ex.blocks if b.kind == "heading"]
    assert "2.1 Income Criteria" in headings
    assert len(ex.pages) == 2
    # the running header repeats on every page and is not treated as content
    assert not any(b.text.startswith("National Merit Scholarship Scheme — Guidelines 2026") and b.bbox[1] < 60
                   for b in ex.blocks)


def test_hidden_text_is_detected_and_flagged():
    ex = extract("pdf", (DEMO / "Rahul_Verma_Statement_of_Purpose.pdf").read_bytes(), 300)
    hidden = [b for b in ex.blocks if b.kind == "hidden"]
    assert hidden and "Ignore all previous instructions" in hidden[0].text
    findings = scan_text(hidden[0].text, hidden=True)
    assert findings and all(f.severity == "HIGH" for f in findings)


def test_scanned_pdf_is_read_with_ocr():
    ex = extract("pdf", (DEMO / "Marksheet_Priya_Sharma_scanned.pdf").read_bytes(), 300)
    assert ex.ocr_used
    text = " ".join(b.text for b in ex.blocks)
    assert "82.40%" in text and "PRIYA SHARMA" in text


def test_docx_two_column_table_becomes_fields():
    ex = extract("docx", (DEMO / "Application_Form_Rahul_Verma.docx").read_bytes(), 300)
    texts = [b.text for b in ex.blocks]
    assert "Date of Birth: 14/02/2004" in texts


def test_duplicate_upload_rejected(store):
    cid = "dup-" + new_id()[:8]
    data = (DEMO / "Scholarship_FAQ.txt").read_bytes()
    ingest(store, document_id=new_id(), collection_id=cid, filename="faq.txt", data=data)
    with pytest.raises(IngestError) as e:
        ingest(store, document_id=new_id(), collection_id=cid, filename="faq-copy.txt", data=data)
    assert e.value.code == "DUPLICATE"


def test_large_document_is_indexed_quickly(store):
    doc = pymupdf.open()
    for i in range(120):
        page = doc.new_page()
        page.insert_text((72, 72), f"Section {i + 1}. Operating procedure", fontsize=14)
        y = 110
        for j in range(18):
            page.insert_text((72, y), f"Clause {i + 1}.{j + 1}: the operator must record reading {j} before shift end.", fontsize=10)
            y += 30
    t = time.time()
    r = ingest(store, document_id=new_id(), collection_id="large-" + new_id()[:8], filename="manual.pdf", data=doc.tobytes())
    assert r["pages"] == 120
    assert r["chunks"] >= 120
    assert time.time() - t < 120
