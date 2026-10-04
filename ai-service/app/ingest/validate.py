"""File validation by content, never by the client-supplied name or MIME type alone."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from app.errors import IngestError

KIND_PDF = "pdf"
KIND_DOCX = "docx"
KIND_TEXT = "text"
KIND_IMAGE = "image"

_EXT_KIND = {
    ".pdf": KIND_PDF,
    ".docx": KIND_DOCX,
    ".txt": KIND_TEXT, ".md": KIND_TEXT, ".csv": KIND_TEXT,
    ".png": KIND_IMAGE, ".jpg": KIND_IMAGE, ".jpeg": KIND_IMAGE, ".webp": KIND_IMAGE,
    ".tif": KIND_IMAGE, ".tiff": KIND_IMAGE, ".bmp": KIND_IMAGE,
}

SUPPORTED_EXTENSIONS = sorted(_EXT_KIND)


@dataclass(frozen=True)
class Detected:
    kind: str
    mime: str


def _ext(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot >= 0 else ""


def detect(filename: str, data: bytes, max_bytes: int) -> Detected:
    """Return the real file kind, or raise IngestError with a user-facing reason."""
    if not data:
        raise IngestError("EMPTY_FILE", "The file is empty.")
    if len(data) > max_bytes:
        raise IngestError("FILE_TOO_LARGE", f"The file is larger than {max_bytes // (1024 * 1024)} MB.")

    ext = _ext(filename)
    if ext not in _EXT_KIND:
        raise IngestError("UNSUPPORTED_TYPE",
                          f"'{ext or 'no extension'}' files are not supported. Use PDF, DOCX, TXT/MD or an image.")
    claimed = _EXT_KIND[ext]
    head = data[:16]

    if head.startswith(b"%PDF"):
        actual = Detected(KIND_PDF, "application/pdf")
    elif head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile as e:
            raise IngestError("CORRUPTED_FILE", "The DOCX file is damaged and cannot be opened.") from e
        if "word/document.xml" not in names:
            raise IngestError("UNSUPPORTED_TYPE", "This archive is not a Word (.docx) document.")
        actual = Detected(KIND_DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    elif head.startswith(b"\x89PNG"):
        actual = Detected(KIND_IMAGE, "image/png")
    elif head.startswith(b"\xff\xd8\xff"):
        actual = Detected(KIND_IMAGE, "image/jpeg")
    elif head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        actual = Detected(KIND_IMAGE, "image/webp")
    elif head[:4] in (b"II*\x00", b"MM\x00*"):
        actual = Detected(KIND_IMAGE, "image/tiff")
    elif head[:2] == b"BM":
        actual = Detected(KIND_IMAGE, "image/bmp")
    else:
        actual = None

    if claimed == KIND_TEXT:
        if actual is not None:
            raise IngestError("TYPE_MISMATCH", "The file content does not match its .txt/.md extension.")
        if b"\x00" in data[:4096]:
            raise IngestError("CORRUPTED_FILE", "The text file contains binary data.")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                data.decode("cp1252")
            except UnicodeDecodeError as e:
                raise IngestError("CORRUPTED_FILE", "The text file is not valid UTF-8 text.") from e
        return Detected(KIND_TEXT, "text/plain")

    if actual is None:
        if claimed == KIND_PDF:
            raise IngestError("CORRUPTED_FILE", "The PDF is damaged: it has no PDF header.")
        raise IngestError("TYPE_MISMATCH", "The file content does not match its extension.")
    if actual.kind != claimed:
        raise IngestError("TYPE_MISMATCH",
                          f"The file is named {ext} but its content is {actual.mime}.")
    return actual
