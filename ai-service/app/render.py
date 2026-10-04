"""Render a source page as PNG with the cited passage highlighted."""
from __future__ import annotations

import io

from app.errors import IngestError
from app.ingest.pipeline import file_path

HIGHLIGHT = (1.0, 0.78, 0.25)      # amber: the cited passage
SENTENCE = (1.0, 0.62, 0.0)        # stronger: the exact sentence
HIDDEN = (0.86, 0.18, 0.2)         # red: hidden text found by the security layer


def render_page(doc: dict, page: int, chunk: dict | None, sentence: str | None, hidden_boxes: list[list[float]],
                width: int = 1100) -> bytes:
    path = file_path(doc["collection_id"], doc["id"], doc["kind"])
    if not path.exists():
        raise IngestError("FILE_MISSING", "The original file is no longer stored.")
    if doc["kind"] == "pdf":
        return _pdf(path, page, chunk, sentence, hidden_boxes, width)
    if doc["kind"] == "image":
        return _image(path, chunk, width)
    raise IngestError("NOT_RENDERABLE", "This document type has no page images; use the text view.")


def _pdf(path, page_no: int, chunk, sentence, hidden_boxes, width) -> bytes:
    import pymupdf

    doc = pymupdf.open(str(path))
    if page_no < 1 or page_no > doc.page_count:
        raise IngestError("BAD_PAGE", "That page does not exist.")
    page = doc[page_no - 1]
    marked_sentence = False
    if sentence:
        for probe in (sentence[:120], sentence[:60]):
            quads = page.search_for(probe, quads=True)
            if quads:
                annot = page.add_highlight_annot(quads)
                annot.set_colors(stroke=SENTENCE)
                annot.update(opacity=0.45)
                marked_sentence = True
                break
    if chunk:
        for box in chunk.get("boxes", []):
            if int(box[0]) != page_no:
                continue
            rect = pymupdf.Rect(*box[1:5]) + (-3, -2, 3, 2)
            if marked_sentence:
                page.draw_rect(rect, color=HIGHLIGHT, width=1.2)
            else:
                annot = page.add_rect_annot(rect)
                annot.set_colors(stroke=HIGHLIGHT, fill=HIGHLIGHT)
                annot.update(opacity=0.28)
    for box in hidden_boxes:
        rect = pymupdf.Rect(*box) + (-4, -3, 4, 3)
        page.draw_rect(rect, color=HIDDEN, width=1.6, dashes="[4 3] 0")
    zoom = width / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
    return pix.tobytes("png")


def _image(path, chunk, width) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.open(path).convert("RGB")
    if chunk:
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for box in chunk.get("boxes", []):
            x0, y0, x1, y1 = box[1:5]
            draw.rectangle((x0 - 6, y0 - 4, x1 + 6, y1 + 4), fill=(255, 190, 60, 80), outline=(255, 160, 0, 255), width=3)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
