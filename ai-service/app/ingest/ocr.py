"""OCR through RapidOCR (ONNX, no system Tesseract needed). Loaded lazily, once."""
from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass

from app.config import settings

log = logging.getLogger(__name__)

_engine = None
_failed = False
_lock = threading.Lock()


@dataclass
class OcrLine:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float


def _get():
    global _engine, _failed
    if _engine is not None or _failed:
        return _engine
    with _lock:
        if _engine is None and not _failed:
            if not settings.enable_ocr:
                _failed = True
                return None
            try:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
            except Exception:  # missing wheel, broken model files...
                log.exception("OCR engine failed to load; scanned documents will be rejected")
                _failed = True
    return _engine


def available() -> bool:
    return _get() is not None


def read_image(img) -> list[OcrLine]:
    import numpy as np

    engine = _get()
    if engine is None:
        return []
    img = img.convert("RGB")
    scale = 1.0
    longest = max(img.size)
    if longest > 2600:  # big scans are slow and gain nothing
        scale = 2600 / longest
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    result, _ = engine(np.array(img))
    lines = []
    for box, text, conf in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        if not str(text).strip():
            continue
        lines.append(OcrLine(str(text).strip(), float(conf),
                             min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale))
    lines.sort(key=lambda l: (round(l.y0 / 8), l.x0))
    return _merge_same_row(lines)


def read_image_bytes(data: bytes) -> list[OcrLine]:
    from PIL import Image

    return read_image(Image.open(io.BytesIO(data)))


def _merge_same_row(lines: list[OcrLine]) -> list[OcrLine]:
    """OCR often splits one printed line into several boxes; rejoin boxes on the same row."""
    merged: list[OcrLine] = []
    for l in lines:
        if merged:
            m = merged[-1]
            h = max(m.y1 - m.y0, 1)
            same_row = abs((l.y0 + l.y1) / 2 - (m.y0 + m.y1) / 2) < h * 0.5 and l.x0 > m.x0
            if same_row:
                merged[-1] = OcrLine(f"{m.text} {l.text}", (m.conf + l.conf) / 2,
                                     min(m.x0, l.x0), min(m.y0, l.y0), max(m.x1, l.x1), max(m.y1, l.y1))
                continue
        merged.append(l)
    return merged
