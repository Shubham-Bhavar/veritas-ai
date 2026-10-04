"""Section-aware chunking that keeps every chunk tied to its page, section and boxes."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.ingest.extract import Block, Extracted
from app.ingest.text_utils import split_sentences

TARGET_CHARS = 650
MAX_CHARS = 950


@dataclass
class Chunk:
    ordinal: int
    text: str
    section: str
    page: int | None
    page_end: int | None
    line_start: int | None
    line_end: int | None
    boxes: list[list[float]] = field(default_factory=list)  # [page, x0, y0, x1, y1]
    quality: float = 1.0
    heading: bool = False


def chunk(doc: Extracted, title: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    cur: list[Block] = []
    page_quality = {p.number: p.quality for p in doc.pages}

    def section_path() -> str:
        return " › ".join(t for _, t in stack) if stack else title

    def flush():
        if not cur:
            return
        text = "\n".join(b.text for b in cur)
        _emit(chunks, cur, text, section_path(), page_quality)
        cur.clear()

    for b in doc.blocks:
        if b.kind == "hidden":
            continue
        if b.kind == "heading":
            flush()
            level = max(b.level, 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, b.text))
            continue
        if cur and (b.page != cur[-1].page):
            flush()
        size = sum(len(x.text) + 1 for x in cur)
        if cur and size + len(b.text) > TARGET_CHARS:
            flush()
        if len(b.text) > MAX_CHARS:
            flush()
            for piece in _split_long(b.text):
                _emit(chunks, [b], piece, section_path(), page_quality)
            continue
        cur.append(b)
    flush()

    # A document of only headings (e.g. a slide title page) would otherwise vanish.
    if not chunks:
        heads = [b for b in doc.blocks if b.kind == "heading"]
        if heads:
            _emit(chunks, heads, "\n".join(h.text for h in heads), title, page_quality)
    return chunks


def _emit(chunks: list[Chunk], blocks: list[Block], text: str, section: str, page_quality: dict) -> None:
    pages = [b.page for b in blocks if b.page is not None]
    lines = [b.line for b in blocks if b.line is not None]
    boxes = [[b.page, *[round(v, 2) for v in b.bbox]] for b in blocks if b.bbox and b.page]
    confs = [b.ocr_conf for b in blocks if b.ocr_conf is not None]
    if confs:
        quality = sum(confs) / len(confs)
    elif pages:
        quality = min(page_quality.get(p, 1.0) for p in pages) or 1.0
    else:
        quality = 1.0
    chunks.append(Chunk(
        ordinal=len(chunks),
        text=text.strip(),
        section=section,
        page=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        line_start=min(lines) if lines else None,
        line_end=max(lines) if lines else None,
        boxes=boxes,
        quality=round(quality, 3),
    ))


def _split_long(text: str) -> list[str]:
    out, cur = [], ""
    for s in split_sentences(text):
        if cur and len(cur) + len(s) > TARGET_CHARS:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out
