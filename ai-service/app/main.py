"""VERITAS evidence service (internal API, called only by the Spring backend)."""
from __future__ import annotations

import contextvars
import hmac
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.errors import IngestError, ServiceUnavailable
from app.ingest import ocr
from app.ingest.pipeline import SAFE_ID, ingest
from app.intel import compare as compare_mod
from app.intel import conflicts as cf
from app.intel.embeddings import embedder
from app.intel.index import get_index
from app.intel.investigate import investigate
from app.intel.llm import LlmSynthesizer
from app.render import render_page
from app.store.store import Store

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
for _h in logging.getLogger().handlers:
    _h.addFilter(_RequestIdFilter())
log = logging.getLogger("veritas")

state: dict = {"store": None, "store_error": None, "models": "loading", "llm": None}


def _store() -> Store:
    if state["store"] is None:
        try:
            state["store"] = Store(settings.database_url)
            state["store_error"] = None
        except ServiceUnavailable as e:
            state["store_error"] = e.message
            raise
    return state["store"]


def _warm():
    try:
        embedder.load()
        ocr.available()
        state["models"] = "ready"
    except Exception:  # pragma: no cover - reported via /health
        log.exception("Model warm-up failed")
        state["models"] = "failed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _store()
    except ServiceUnavailable:
        log.error("Evidence store unavailable at startup; will retry on demand")
    state["llm"] = LlmSynthesizer() if settings.llm_configured else None
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title="VERITAS evidence service", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = (request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12])[:64]
    token = _request_id.set(rid)
    t = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        _request_id.reset(token)
    response.headers["X-Request-Id"] = rid
    if request.url.path != "/health":
        log.info("[%s] %s %s -> %s in %d ms", rid, request.method, request.url.path, response.status_code,
                 (time.perf_counter() - t) * 1000)
    return response


def require_token(x_internal_token: str = Header(default="")):
    if not settings.internal_token:
        raise HTTPException(503, detail={"code": "NOT_CONFIGURED", "message": "AI_INTERNAL_TOKEN is not set on the evidence service."})
    if not hmac.compare_digest(x_internal_token, settings.internal_token):
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "Invalid internal token."})


def _check_id(value: str) -> str:
    if not SAFE_ID.match(value):
        raise HTTPException(400, detail={"code": "BAD_ID", "message": "Invalid identifier."})
    return value


@app.exception_handler(IngestError)
async def ingest_error(_: Request, e: IngestError):
    status = 409 if e.code == "DUPLICATE" else 404 if e.code in ("FILE_MISSING",) else 422
    return JSONResponse(status_code=status, content={"code": e.code, "message": e.message})


@app.exception_handler(ServiceUnavailable)
async def unavailable(_: Request, e: ServiceUnavailable):
    return JSONResponse(status_code=503, content={"code": "UNAVAILABLE", "component": e.component, "message": e.message})


@app.exception_handler(HTTPException)
async def http_error(_: Request, e: HTTPException):
    detail = e.detail if isinstance(e.detail, dict) else {"code": "ERROR", "message": str(e.detail)}
    return JSONResponse(status_code=e.status_code, content=detail)


@app.exception_handler(Exception)
async def unexpected(_: Request, e: Exception):
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"code": "INTERNAL", "message": "The evidence service hit an unexpected error."})


# ------------------------------------------------------------------ health

@app.get("/health")
def health():
    store_ok = False
    try:
        store_ok = _store().ping()
    except ServiceUnavailable:
        pass
    return {
        "status": "ok" if store_ok and state["models"] != "failed" else "degraded",
        "store": {"ok": store_ok, "backend": "pgvector" if settings.database_url.startswith("postgres") else "sqlite",
                  "error": state["store_error"]},
        "models": state["models"],
        "embeddings": embedder.mode,
        "semantic_embeddings": embedder.semantic,
        "reranker": embedder.reranker_mode,
        "ocr": ocr.available() if state["models"] == "ready" else None,
        "llm": {"configured": state["llm"] is not None, "model": settings.llm_model if state["llm"] else None},
        "limits": {"max_file_mb": settings.max_file_mb, "max_pages": settings.max_pages},
    }


# ------------------------------------------------------------------ documents

@app.post("/v1/collections/{collection_id}/documents", dependencies=[Depends(require_token)])
def upload(collection_id: str, document_id: str = Form(...), file: UploadFile = File(...)):
    _check_id(collection_id)
    _check_id(document_id)
    limit = settings.max_file_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise IngestError("FILE_TOO_LARGE", f"The file is larger than {settings.max_file_mb} MB.")
    filename = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1][:200]
    return ingest(_store(), document_id=document_id, collection_id=collection_id, filename=filename, data=data)


@app.delete("/v1/collections/{collection_id}/documents/{document_id}", dependencies=[Depends(require_token)])
def delete_document(collection_id: str, document_id: str):
    _check_id(collection_id)
    _check_id(document_id)
    found = _store().delete_document(document_id)
    from app.ingest.pipeline import file_path

    for kind in ("pdf", "docx", "text", "image"):
        p = file_path(collection_id, document_id, kind)
        if p.exists():
            p.unlink()
    return {"deleted": bool(found)}


@app.delete("/v1/collections/{collection_id}", dependencies=[Depends(require_token)])
def delete_collection(collection_id: str):
    _check_id(collection_id)
    ids = _store().delete_collection(collection_id)
    import shutil

    shutil.rmtree(settings.storage_dir / collection_id, ignore_errors=True)
    return {"deleted_documents": len(ids)}


def _doc_or_404(collection_id: str, document_id: str) -> dict:
    doc = _store().document(document_id)
    if not doc or doc["collection_id"] != collection_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Document not found."})
    return doc


@app.get("/v1/collections/{collection_id}/documents/{document_id}", dependencies=[Depends(require_token)])
def document_detail(collection_id: str, document_id: str):
    doc = _doc_or_404(_check_id(collection_id), _check_id(document_id))
    chunks = _store().document_chunks(document_id)
    flags = [f for f in _store().flags(collection_id) if f["document_id"] == document_id]
    return {"document": doc, "chunks": chunks, "security_flags": flags}


@app.get("/v1/collections/{collection_id}/chunks/{chunk_id}", dependencies=[Depends(require_token)])
def chunk_detail(collection_id: str, chunk_id: str):
    _check_id(collection_id)
    chunk = _store().chunk(chunk_id)
    if not chunk or chunk["collection_id"] != collection_id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Passage not found."})
    doc = _store().document(chunk["document_id"])
    siblings = _store().document_chunks(chunk["document_id"])
    pos = next(i for i, c in enumerate(siblings) if c["id"] == chunk_id)
    return {"chunk": chunk, "document": doc,
            "previous": siblings[pos - 1] if pos > 0 else None,
            "next": siblings[pos + 1] if pos + 1 < len(siblings) else None}


@app.get("/v1/collections/{collection_id}/documents/{document_id}/pages/{page}", dependencies=[Depends(require_token)])
def page_image(collection_id: str, document_id: str, page: int, chunk_id: str | None = None, sentence: str | None = None,
               flags: bool = False):
    doc = _doc_or_404(_check_id(collection_id), _check_id(document_id))
    chunk = _store().chunk(chunk_id) if chunk_id else None
    if chunk and chunk["document_id"] != document_id:
        chunk = None
    hidden = []
    if flags:
        hidden = [f["bbox"] for f in _store().flags(collection_id)
                  if f["document_id"] == document_id and f["kind"] == "hidden_text" and f["page"] == page and f["bbox"]]
    png = render_page(doc, page, chunk, (sentence or "")[:300] or None, hidden)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


# ------------------------------------------------------------------ intelligence

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@app.post("/v1/collections/{collection_id}/investigate", dependencies=[Depends(require_token)])
def ask(collection_id: str, body: Question):
    idx = get_index(_store(), _check_id(collection_id))
    return investigate(idx, body.question.strip(), llm=state["llm"])


@app.get("/v1/collections/{collection_id}/conflicts", dependencies=[Depends(require_token)])
def conflicts(collection_id: str):
    idx = get_index(_store(), _check_id(collection_id))
    found = cf.detect(idx)
    return {"conflicts": found,
            "summary": {"unresolved": sum(1 for c in found if c["status"] == "UNRESOLVED"),
                        "resolved": sum(1 for c in found if c["status"] == "RESOLVED"),
                        "high": sum(1 for c in found if c["severity"] == "HIGH" and c["status"] == "UNRESOLVED")}}


@app.get("/v1/collections/{collection_id}/security", dependencies=[Depends(require_token)])
def security(collection_id: str):
    idx = get_index(_store(), _check_id(collection_id))
    return {"flags": [{**f, "filename": idx.docs[f["document_id"]]["filename"]} for f in idx.flags if f["document_id"] in idx.docs]}


@app.get("/v1/collections/{collection_id}/overview", dependencies=[Depends(require_token)])
def overview(collection_id: str):
    idx = get_index(_store(), _check_id(collection_id))
    found = cf.detect(idx)
    return {"documents": len(idx.docs), "chunks": len(idx.chunks), "facts": len(idx.facts),
            "conflicts_unresolved": sum(1 for c in found if c["status"] == "UNRESOLVED"),
            "conflicts_resolved": sum(1 for c in found if c["status"] == "RESOLVED"),
            "security_flags": len(idx.flags),
            "superseded_documents": list(cf.supersession_map(idx))}


class CompareBody(BaseModel):
    document_a: str
    document_b: str


@app.post("/v1/collections/{collection_id}/compare", dependencies=[Depends(require_token)])
def compare(collection_id: str, body: CompareBody):
    idx = get_index(_store(), _check_id(collection_id))
    for d in (body.document_a, body.document_b):
        if d not in idx.docs:
            raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Document not found in this investigation."})
    if body.document_a == body.document_b:
        raise HTTPException(400, detail={"code": "SAME_DOCUMENT", "message": "Choose two different documents."})
    return compare_mod.compare(idx, body.document_a, body.document_b)
