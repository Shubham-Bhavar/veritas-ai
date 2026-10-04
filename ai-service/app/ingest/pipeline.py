"""Ingestion: bytes in, an indexed and fact-annotated document out."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path

from app.config import settings
from app.errors import IngestError
from app.ingest import chunker, injection
from app.ingest.extract import extract
from app.ingest.metadata import extract_meta
from app.ingest.validate import detect
from app.intel.embeddings import embedder
from app.intel.facts import extract_facts
from app.store.store import Store

log = logging.getLogger(__name__)

SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def section_leaf(section: str) -> str:
    leaf = section.split(" › ")[-1]
    return re.sub(r"^(?:rule|section|para|chapter)?\s*\d+(?:\.\d+)*[.)]?\s*", "", leaf, flags=re.I).strip()


def ingest(store: Store, *, document_id: str, collection_id: str, filename: str, data: bytes) -> dict:
    if not SAFE_ID.match(document_id) or not SAFE_ID.match(collection_id):
        raise IngestError("BAD_REQUEST", "Invalid document or collection id.")
    timings: dict[str, int] = {}
    t0 = time.perf_counter()

    detected = detect(filename, data, settings.max_file_mb * 1024 * 1024)
    sha = hashlib.sha256(data).hexdigest()
    dup = store.find_by_hash(collection_id, sha)
    if dup and dup["id"] != document_id:
        raise IngestError("DUPLICATE", f"This file is identical to '{dup['filename']}', which is already in the investigation.")

    t = time.perf_counter()
    extracted = extract(detected.kind, data, settings.max_pages)
    timings["extract_ms"] = _ms(t)

    meta = extract_meta(extracted, filename)
    chunks = chunker.chunk(extracted, meta.title)

    # Security: hidden text and instruction-like passages.
    flags: list[dict] = []
    for b in extracted.blocks:
        if b.kind == "hidden":
            found = injection.scan_text(b.text, hidden=True)
            if found:
                reasons = list(dict.fromkeys(r for f in found for r in f.reasons))
                severity = "HIGH" if any(f.severity == "HIGH" for f in found) else "MEDIUM"
                flags.append({"kind": "hidden_text", "severity": severity, "text": b.text, "reasons": reasons,
                              "page": b.page, "bbox": list(b.bbox) if b.bbox else None, "chunk_id": None,
                              "sentences": [f.text for f in found]})
    chunk_rows = []
    for c in chunks:
        cid = f"{document_id}#c{c.ordinal}"
        findings = injection.scan_text(c.text)
        for f in findings:
            flags.append({"kind": "instruction", "severity": f.severity, "text": f.text, "reasons": f.reasons,
                          "page": c.page, "bbox": None, "chunk_id": cid})
        chunk_rows.append({"id": cid, "ordinal": c.ordinal, "page": c.page, "page_end": c.page_end,
                           "line_start": c.line_start, "line_end": c.line_end, "section": c.section, "text": c.text,
                           "boxes": c.boxes, "quality": c.quality, "flags": [f.text for f in findings]})
    for i, fl in enumerate(flags):
        fl["id"] = f"{document_id}#s{i}"

    # Facts (never from flagged text).
    fact_rows = []
    for row in chunk_rows:
        for fact in extract_facts(row["text"], meta.role, row["flags"]):
            d = fact.as_dict()
            d["chunk_id"] = row["id"]
            d["section_leaf"] = section_leaf(row["section"])
            fact_rows.append(d)
    for i, f in enumerate(fact_rows):
        f["id"] = f"{document_id}#f{i}"

    t = time.perf_counter()
    chunk_vecs = embedder.embed([f"{meta.title} — {r['section']}\n{r['text']}" for r in chunk_rows])
    fact_vecs = embedder.embed([f"{f['section_leaf']}: {f['attr_text']}" for f in fact_rows])
    timings["embed_ms"] = _ms(t)
    for r, v in zip(chunk_rows, chunk_vecs):
        r["embedding"] = v
    for f, v in zip(fact_rows, fact_vecs):
        f["embedding"] = v

    pages = len(extracted.pages) if extracted.pages else None
    doc_row = {
        "id": document_id, "collection_id": collection_id, "filename": filename, "kind": detected.kind,
        "mime": detected.mime, "sha256": sha, "title": meta.title, "doc_date": meta.doc_date, "role": meta.role,
        "authority": meta.authority, "pages": pages, "quality": extracted.quality, "ocr_used": extracted.ocr_used,
        "chars": extracted.text_chars,
        "meta": {"people": meta.people, "subjects": meta.subjects, "references": meta.references, "amendments": meta.amendments,
                 "years": meta.years, "warnings": extracted.warnings,
                 "page_sizes": [[p.number, p.width, p.height, p.ocr, p.quality] for p in extracted.pages]},
    }
    _save_file(collection_id, document_id, detected.kind, data)
    store.save_document(doc_row, chunk_rows, fact_rows, flags)
    timings["total_ms"] = _ms(t0)
    log.info("Indexed %s: %d chunks, %d facts, %d flags in %d ms", filename, len(chunk_rows), len(fact_rows), len(flags),
             timings["total_ms"])
    return {
        "document_id": document_id, "title": meta.title, "kind": detected.kind, "mime": detected.mime,
        "pages": pages, "chunks": len(chunk_rows), "facts": len(fact_rows), "ocr_used": extracted.ocr_used,
        "quality": extracted.quality, "role": meta.role, "doc_date": meta.doc_date, "authority": meta.authority,
        "people": meta.people, "subjects": meta.subjects, "security_flags": len(flags), "warnings": extracted.warnings, "timings": timings,
        "sha256": sha, "embedding_mode": embedder.mode,
    }


def file_path(collection_id: str, document_id: str, kind: str) -> Path:
    return settings.storage_dir / collection_id / f"{document_id}.{kind}"


def _save_file(collection_id: str, document_id: str, kind: str, data: bytes) -> None:
    path = file_path(collection_id, document_id, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _ms(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)
