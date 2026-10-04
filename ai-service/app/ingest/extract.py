"""Turn a validated file into ordered, located text blocks.

Every block remembers where it came from (page, bounding box or line), because every
citation VERITAS shows must lead back to an exact place in the original document.
"""
from __future__ import annotations

import io
import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from app.errors import IngestError
from app.ingest import ocr
from app.ingest.validate import KIND_DOCX, KIND_IMAGE, KIND_PDF, KIND_TEXT

log = logging.getLogger(__name__)

_SOFT_HYPHEN = re.compile(r"(?<=\w)­(?=\w)")
_TRANSLATE = str.maketrans({" ": " ", " ": " ", " ": " ", "ꞏ": "·", "‐": "-", "‑": "-",
                            "‒": "-", "​": None, "‌": None, "‍": None, "﻿": None})


def clean(text: str) -> str:
    """Undo common text-layer quirks: NBSP spaces, soft hyphens used as hyphens, odd middots."""
    text = _SOFT_HYPHEN.sub("-", text).replace("­", "")
    return text.translate(_TRANSLATE)


NUMBERED_HEADING = re.compile(r"^(?:(?:section|rule|para|chapter|part)\s+)?(\d{1,2}(?:\.\d{1,2}){0,3})[.)]?\s+[A-Z(]", re.I)
WHITE = 0xFFFFFF


@dataclass
class Block:
    text: str
    kind: str = "para"            # heading | para | table | hidden
    level: int = 0                # heading depth (1 = top)
    page: int | None = None       # 1-based page, None when the format has no pages
    bbox: tuple[float, float, float, float] | None = None
    line: int | None = None       # line (txt) or paragraph index (docx)
    ocr_conf: float | None = None


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    ocr: bool = False
    quality: float = 1.0


@dataclass
class Extracted:
    kind: str
    blocks: list[Block]
    pages: list[PageInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_used(self) -> bool:
        return any(p.ocr for p in self.pages)

    @property
    def quality(self) -> float:
        if not self.pages:
            return 1.0
        return round(sum(p.quality for p in self.pages) / len(self.pages), 3)

    @property
    def text_chars(self) -> int:
        return sum(len(b.text) for b in self.blocks if b.kind != "hidden")


def extract(kind: str, data: bytes, max_pages: int) -> Extracted:
    if kind == KIND_PDF:
        result = _pdf(data, max_pages)
    elif kind == KIND_DOCX:
        result = _docx(data)
    elif kind == KIND_TEXT:
        result = _text(data)
    elif kind == KIND_IMAGE:
        result = _image(data)
    else:  # pragma: no cover - validate() guarantees the kind
        raise IngestError("UNSUPPORTED_TYPE", f"Unsupported kind {kind}")

    if result.text_chars < 20:
        if result.ocr_used or kind == KIND_IMAGE:
            raise IngestError("OCR_NO_TEXT", "No readable text was found, even with OCR.")
        raise IngestError("NO_TEXT", "The document contains no extractable text.")
    return result


# ---------------------------------------------------------------- PDF

def _pdf(data: bytes, max_pages: int) -> Extracted:
    import pymupdf as fitz

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # PyMuPDF raises several types for broken files
        raise IngestError("CORRUPTED_FILE", "The PDF is damaged and cannot be opened.") from e
    if doc.needs_pass:
        raise IngestError("ENCRYPTED", "The PDF is password-protected. Upload an unlocked copy.")
    if doc.page_count == 0:
        raise IngestError("CORRUPTED_FILE", "The PDF has no pages.")
    if doc.page_count > max_pages:
        raise IngestError("TOO_MANY_PAGES", f"The PDF has {doc.page_count} pages; the limit is {max_pages}.")

    raw: list[tuple[int, list[dict]]] = []
    pages: list[PageInfo] = []
    warnings: list[str] = []
    size_chars: Counter = Counter()

    for page in doc:
        number = page.number + 1
        info = PageInfo(number, page.rect.width, page.rect.height)
        pages.append(info)
        try:
            d = page.get_text("dict")
        except Exception:  # a single broken page should not sink the document
            warnings.append(f"Page {number} could not be read and was skipped.")
            raw.append((number, []))
            continue
        page_blocks = []
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            visible_lines, hidden_spans = [], []
            sizes, bold_chars, chars = [], 0, 0
            for line in b.get("lines", []):
                parts = []
                for s in line.get("spans", []):
                    t = clean(s.get("text", ""))
                    s["text"] = t
                    if not t.strip():
                        parts.append(t)
                        continue
                    if _is_hidden(s, page.rect):
                        hidden_spans.append(s)
                        continue
                    parts.append(t)
                    n = len(t.strip())
                    sizes.append((s["size"], n))
                    size_chars[round(s["size"] * 2) / 2] += n
                    chars += n
                    if s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower():
                        bold_chars += n
                txt = "".join(parts).strip()
                if txt:
                    visible_lines.append(txt)
            if visible_lines:
                page_blocks.append({
                    "lines": visible_lines,
                    "bbox": tuple(b["bbox"]),
                    "size": max(s for s, _ in sizes) if sizes else 0,
                    "bold": chars > 0 and bold_chars / chars > 0.8,
                })
            if hidden_spans:
                text = " ".join(s["text"].strip() for s in hidden_spans if s["text"].strip())
                x0 = min(s["bbox"][0] for s in hidden_spans)
                y0 = min(s["bbox"][1] for s in hidden_spans)
                x1 = max(s["bbox"][2] for s in hidden_spans)
                y1 = max(s["bbox"][3] for s in hidden_spans)
                page_blocks.append({"hidden": True, "text": text, "bbox": (x0, y0, x1, y1)})

        page_blocks = _merge_same_baseline(page_blocks)
        visible_chars = sum(len(" ".join(b["lines"])) for b in page_blocks if not b.get("hidden"))
        if visible_chars < 25 and page.get_images():
            ocr_blocks = _ocr_pdf_page(page, info, warnings)
            raw.append((number, ocr_blocks))
        else:
            raw.append((number, page_blocks))

    body = _body_size(size_chars)
    repeated = _repeated_lines(raw, pages)
    blocks: list[Block] = []
    for number, page_blocks in raw:
        height = pages[number - 1].height
        for b in page_blocks:
            if b.get("hidden"):
                blocks.append(Block(b["text"], "hidden", page=number, bbox=b["bbox"]))
                continue
            if b.get("ocr"):
                blocks.append(b["block"])
                continue
            text = _join_lines(b["lines"])
            y0, y1 = b["bbox"][1], b["bbox"][3]
            in_margin = y1 < height * 0.09 or y0 > height * 0.92
            if in_margin and (_norm_line(text) in repeated or re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", text, re.I)):
                continue  # running header/footer or page number
            is_heading, level = _heading(text, b["size"], b["bold"], body)
            blocks.append(Block(text, "heading" if is_heading else "para", level, number, b["bbox"]))
    _assign_heading_levels(blocks)
    return Extracted(KIND_PDF, blocks, pages, warnings)


def _merge_same_baseline(page_blocks: list[dict]) -> list[dict]:
    """Form layouts put 'Label:' and its value in separate blocks on one baseline; rejoin them."""
    out: list[dict] = []
    for b in page_blocks:
        prev = out[-1] if out else None
        if (prev and not prev.get("hidden") and not b.get("hidden") and len(prev["lines"]) == 1 and len(b["lines"]) == 1
                and abs(prev["bbox"][1] - b["bbox"][1]) < 2.5 and b["bbox"][0] >= prev["bbox"][2] - 1):
            prev["lines"] = [f"{prev['lines'][0]} {b['lines'][0]}"]
            prev["bbox"] = (prev["bbox"][0], min(prev["bbox"][1], b["bbox"][1]), b["bbox"][2], max(prev["bbox"][3], b["bbox"][3]))
            prev["size"] = max(prev["size"], b["size"])
            prev["bold"] = prev["bold"] and b["bold"]
            continue
        out.append(b)
    return out


def _is_hidden(span: dict, rect) -> bool:
    if span.get("size", 10) < 2.5:
        return True
    if span.get("color") == WHITE:
        return True
    x0, y0, x1, y1 = span["bbox"]
    return x1 < rect.x0 or x0 > rect.x1 or y1 < rect.y0 or y0 > rect.y1


def _ocr_pdf_page(page, info: PageInfo, warnings: list[str]) -> list[dict]:
    import pymupdf as fitz

    if not ocr.available():
        warnings.append(f"Page {info.number} looks scanned but OCR is unavailable; its text was not indexed.")
        info.quality = 0.0
        return []
    zoom = 2.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    lines = ocr.read_image_bytes(pix.tobytes("png"))
    info.ocr = True
    if not lines:
        warnings.append(f"OCR found no text on scanned page {info.number}.")
        info.quality = 0.0
        return []
    info.quality = round(sum(l.conf for l in lines) / len(lines), 3)
    return [{"ocr": True, "block": blk} for blk in _ocr_blocks(lines, info.number, 1 / zoom)]


def _body_size(size_chars: Counter) -> float:
    if not size_chars:
        return 10.0
    return size_chars.most_common(1)[0][0]


def _norm_line(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def _repeated_lines(raw, pages) -> set[str]:
    if len(pages) < 2:
        return set()
    counts: Counter = Counter()
    for _, page_blocks in raw:
        seen = set()
        for b in page_blocks:
            if b.get("hidden") or b.get("ocr"):
                continue
            seen.add(_norm_line(_join_lines(b["lines"])))
        counts.update(seen)
    need = len(pages) if len(pages) < 4 else max(2, len(pages) // 2)
    return {t for t, c in counts.items() if c >= need}


def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out = f"{out} {ln}" if out else ln
    return re.sub(r"\s+", " ", out).strip()


def _heading(text: str, size: float, bold: bool, body: float) -> tuple[bool, int]:
    if len(text) > 110 or text.endswith((".", ",", ";")) and not NUMBERED_HEADING.match(text):
        return False, 0
    words = len(text.split())
    if words > 14:
        return False, 0
    if re.match(r"^[^:]{2,50}:\s+\S", text) and not NUMBERED_HEADING.match(text):
        return False, 0  # "Label: value" form fields are content, not headings
    m = NUMBERED_HEADING.match(text)
    if m and (bold or size >= body + 0.5) and words <= 12:
        return True, m.group(1).count(".") + 1
    if size >= body + 1.5:
        return True, 0  # level assigned from relative size later
    if bold and words <= 10 and not text.endswith(":"):
        return True, 0
    return False, 0


def _assign_heading_levels(blocks: list[Block]) -> None:
    """Headings without a numbering scheme get a level from their position in the outline."""
    for b in blocks:
        if b.kind == "heading" and b.level == 0:
            b.level = 1


# ---------------------------------------------------------------- DOCX

def _docx(data: bytes) -> Extracted:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise IngestError("CORRUPTED_FILE", "The DOCX file is damaged and cannot be opened.") from e

    blocks: list[Block] = []
    index = 0
    for el in document.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, document)
            text = re.sub(r"\s+", " ", clean(p.text)).strip()
            if not text:
                continue
            index += 1
            style = (p.style.name if p.style is not None else "") or ""
            runs = [r for r in p.runs if r.text.strip()]
            all_bold = bool(runs) and all(r.bold for r in runs)
            if style.startswith("Heading") or style == "Title":
                digits = re.findall(r"\d", style)
                level = int(digits[0]) if digits else 1
                blocks.append(Block(text, "heading", level, line=index))
            elif all_bold and len(text) < 90 and not text.endswith("."):
                m = NUMBERED_HEADING.match(text)
                blocks.append(Block(text, "heading", m.group(1).count(".") + 1 if m else 2, line=index))
            else:
                if "List" in style:
                    text = f"• {text}"
                blocks.append(Block(text, "para", line=index))
        elif tag == "tbl":
            table = Table(el, document)
            rows = [[re.sub(r"\s+", " ", clean(c.text)).strip() for c in r.cells] for r in table.rows]
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            if ncols == 2 and all(r[0] and len(r[0]) < 60 for r in rows):
                # Two-column table = a form of "Label | Value" rows.
                for r in rows:
                    index += 1
                    blocks.append(Block(f"{r[0].rstrip(':')}: {r[1]}" if r[1] else r[0], "table", line=index))
                continue
            header = rows[0]
            has_header = len(rows) > 1 and all(h and len(h) < 40 for h in header)
            for r in rows[1:] if has_header else rows:
                index += 1
                if has_header:
                    cells = [f"{h}: {v}" for h, v in zip(header, r) if v]
                else:
                    cells = [v for v in r if v]
                blocks.append(Block(" | ".join(cells), "table", line=index))
    return Extracted(KIND_DOCX, blocks, [])


# ---------------------------------------------------------------- TXT / MD

def _text(data: bytes) -> Extracted:
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = data.decode("cp1252")
    content = clean(content)
    blocks: list[Block] = []
    para: list[str] = []
    para_line = 0

    def flush():
        nonlocal para
        if para:
            blocks.append(Block(re.sub(r"\s+", " ", " ".join(para)).strip(), "para", line=para_line))
            para = []

    for i, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        md = re.match(r"^(#{1,4})\s+(.*)$", line)
        upper = line.isupper() and 3 <= len(line) <= 80 and any(c.isalpha() for c in line)
        numbered = NUMBERED_HEADING.match(line) and len(line) <= 80 and not line.endswith(".")
        if md or upper or numbered:
            flush()
            text = md.group(2) if md else line
            level = len(md.group(1)) if md else (numbered.group(1).count(".") + 1 if numbered else 1)
            blocks.append(Block(text, "heading", level, line=i))
            continue
        if not para:
            para_line = i
        para.append(line)
    flush()
    return Extracted(KIND_TEXT, blocks, [])


# ---------------------------------------------------------------- Images

def _image(data: bytes) -> Extracted:
    if not ocr.available():
        raise IngestError("OCR_UNAVAILABLE", "OCR is not available on this server, so images cannot be read.")
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise IngestError("CORRUPTED_FILE", "The image is damaged and cannot be opened.") from e
    width, height = img.size
    lines = ocr.read_image(img)
    info = PageInfo(1, width, height, ocr=True)
    if not lines:
        raise IngestError("OCR_NO_TEXT", "No readable text was found in the image.")
    info.quality = round(sum(l.conf for l in lines) / len(lines), 3)
    return Extracted(KIND_IMAGE, _ocr_blocks(lines, 1, 1.0), [info])


KV_LIKE = re.compile(r"^[A-Z][A-Za-z ()/.'&-]{1,40}:\s*\S")


def _fix_ocr_spacing(t: str) -> str:
    """OCR drops spaces at case and punctuation boundaries ("Candidate'sName:PRIYA")."""
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    t = re.sub(r":(?=\S)", ": ", t)
    t = re.sub(r"(?<=[A-Za-z]{3})(?=(19|20)\d{2}\b)", " ", t)
    return re.sub(r"\s+", " ", clean(t)).strip()


def _ocr_blocks(lines: list["ocr.OcrLine"], page: int, scale: float) -> list[Block]:
    """Group OCR text lines into paragraphs by vertical gaps."""
    if not lines:
        return []
    heights = [l.y1 - l.y0 for l in lines]
    typical = statistics.median(heights) or 1
    out: list[Block] = []
    cur: list = []

    def flush():
        if not cur:
            return
        text = ""
        for l in cur:
            t = _fix_ocr_spacing(l.text)
            if not text:
                text = t
            elif KV_LIKE.match(t) or KV_LIKE.match(text.rsplit("\n", 1)[-1]):
                text += "\n" + t
            else:
                text += " " + t
        bbox = (min(l.x0 for l in cur) * scale, min(l.y0 for l in cur) * scale,
                max(l.x1 for l in cur) * scale, max(l.y1 for l in cur) * scale)
        conf = sum(l.conf for l in cur) / len(cur)
        short_caps = len(cur) == 1 and text.isupper() and len(text) <= 60 and ":" not in text
        out.append(Block(text, "heading" if short_caps else "para", 1 if short_caps else 0, page, bbox, ocr_conf=round(conf, 3)))
        cur.clear()

    for line in lines:
        if cur:
            prev = cur[-1]
            gap = line.y0 - prev.y1
            if gap > typical * 0.9 or line.text.isupper() != prev.text.isupper():
                flush()
        cur.append(line)
    flush()
    return out
