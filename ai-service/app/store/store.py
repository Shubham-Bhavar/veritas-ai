"""Evidence store: documents, located chunks, facts, security flags and their embeddings.

Two backends behind one class:
  * sqlite:///...      local, zero-dependency; vectors as float32 BLOBs, similarity in numpy
  * postgresql://...   production; vectors in pgvector columns with an HNSW index

Collections (one per investigation) are small, so the reasoning layer works on an in-memory
snapshot per collection that is rebuilt whenever the collection changes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from app.errors import ServiceUnavailable

log = logging.getLogger(__name__)

DIM = 384

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    title TEXT,
    doc_date TEXT,
    role TEXT,
    authority TEXT,
    pages INTEGER,
    quality REAL,
    ocr_used INTEGER,
    chars INTEGER,
    meta_json TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_documents_collection ON documents(collection_id);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    page INTEGER,
    page_end INTEGER,
    line_start INTEGER,
    line_end INTEGER,
    section TEXT,
    text TEXT NOT NULL,
    boxes_json TEXT,
    quality REAL,
    flags_json TEXT,
    embedding {VEC}
);
CREATE INDEX IF NOT EXISTS ix_chunks_collection ON chunks(collection_id);
CREATE INDEX IF NOT EXISTS ix_chunks_document ON chunks(document_id);
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL,
    type TEXT NOT NULL,
    value_num REAL,
    value_text TEXT,
    value_hi REAL,
    comparator TEXT,
    display TEXT,
    label TEXT,
    role TEXT,
    sentence TEXT,
    sent_start INTEGER,
    sent_end INTEGER,
    fact_key TEXT,
    embedding {VEC}
);
CREATE INDEX IF NOT EXISTS ix_facts_collection ON facts(collection_id);
CREATE TABLE IF NOT EXISTS security_flags (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL,
    chunk_id TEXT,
    page INTEGER,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    text TEXT NOT NULL,
    reasons_json TEXT,
    bbox_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_flags_collection ON security_flags(collection_id);
"""


def _to_blob(vec) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(b) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


class Store:
    def __init__(self, url: str):
        self.url = url
        self.dialect = "postgres" if url.startswith(("postgresql://", "postgres://")) else "sqlite"
        self._lock = threading.RLock()
        self._conn = None
        self._versions: dict[str, int] = {}
        self._connect()
        self._init_schema()

    # ------------------------------------------------------------ connection

    def _connect(self):
        try:
            if self.dialect == "sqlite":
                path = self.url.replace("sqlite:///", "", 1)
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(path, check_same_thread=False, timeout=15)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                self._conn = conn
            else:
                import psycopg
                from pgvector.psycopg import register_vector
                from psycopg.rows import dict_row

                conn = psycopg.connect(self.url, row_factory=dict_row, autocommit=False, connect_timeout=10)
                with conn.cursor() as cur:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                conn.commit()
                register_vector(conn)
                self._conn = conn
        except Exception as e:
            log.error("Evidence store connection failed: %s", e)
            raise ServiceUnavailable("evidence_store", "The evidence database is unavailable.") from e

    def _init_schema(self):
        vec = "BLOB" if self.dialect == "sqlite" else f"vector({DIM})"
        sql = _SCHEMA.replace("{VEC}", vec)
        with self.tx() as cur:
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                cur.execute(stmt)
            if self.dialect == "postgres":
                # See dense_candidates: a global HNSW index breaks per-investigation filtering.
                cur.execute("DROP INDEX IF EXISTS ix_chunks_embedding")

    @contextmanager
    def tx(self) -> Iterator[Any]:
        with self._lock:
            if self._conn is None:
                self._connect()
            try:
                cur = self._conn.cursor()
                yield _Cursor(cur, self.dialect)
                self._conn.commit()
            except ServiceUnavailable:
                raise
            except Exception as e:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                if self._is_connection_error(e):
                    self._conn = None
                    raise ServiceUnavailable("evidence_store", "The evidence database is unavailable.") from e
                raise

    def _is_connection_error(self, e: Exception) -> bool:
        if self.dialect == "postgres":
            import psycopg

            return isinstance(e, psycopg.OperationalError)
        return isinstance(e, sqlite3.OperationalError) and "locked" not in str(e)

    def ping(self) -> bool:
        try:
            with self.tx() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:
            return False

    def version(self, collection_id: str) -> int:
        return self._versions.get(collection_id, 0)

    def _bump(self, collection_id: str):
        self._versions[collection_id] = self._versions.get(collection_id, 0) + 1

    # ------------------------------------------------------------ writes

    def save_document(self, doc: dict, chunks: list[dict], facts: list[dict], flags: list[dict]) -> None:
        vec = self._vec
        with self.tx() as cur:
            cur.execute("DELETE FROM documents WHERE id = ?", (doc["id"],))
            cur.execute(
                "INSERT INTO documents (id, collection_id, filename, kind, mime, sha256, title, doc_date, role, authority,"
                " pages, quality, ocr_used, chars, meta_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc["id"], doc["collection_id"], doc["filename"], doc["kind"], doc["mime"], doc["sha256"], doc["title"],
                 doc["doc_date"], doc["role"], doc["authority"], doc["pages"], doc["quality"], int(doc["ocr_used"]),
                 doc["chars"], json.dumps(doc["meta"]), time.time()))
            for c in chunks:
                cur.execute(
                    "INSERT INTO chunks (id, document_id, collection_id, ordinal, page, page_end, line_start, line_end,"
                    " section, text, boxes_json, quality, flags_json, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c["id"], doc["id"], doc["collection_id"], c["ordinal"], c["page"], c["page_end"], c["line_start"],
                     c["line_end"], c["section"], c["text"], json.dumps(c["boxes"]), c["quality"], json.dumps(c["flags"]),
                     vec(c["embedding"])))
            for f in facts:
                cur.execute(
                    "INSERT INTO facts (id, chunk_id, document_id, collection_id, type, value_num, value_text, value_hi,"
                    " comparator, display, label, role, sentence, sent_start, sent_end, fact_key, embedding)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f["id"], f["chunk_id"], doc["id"], doc["collection_id"], f["type"],
                     f["value"] if isinstance(f["value"], (int, float)) else None,
                     f["value"] if isinstance(f["value"], str) else None, f.get("value_hi"), f["comparator"], f["display"],
                     f["label"], f["role"], f["sentence"], f["sent_start"], f["sent_end"], f.get("key"), vec(f["embedding"])))
            for fl in flags:
                cur.execute(
                    "INSERT INTO security_flags (id, document_id, collection_id, chunk_id, page, kind, severity, text,"
                    " reasons_json, bbox_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (fl["id"], doc["id"], doc["collection_id"], fl.get("chunk_id"), fl.get("page"), fl["kind"],
                     fl["severity"], fl["text"], json.dumps(fl["reasons"]), json.dumps(fl.get("bbox"))))
        self._bump(doc["collection_id"])

    def delete_document(self, document_id: str) -> str | None:
        with self.tx() as cur:
            cur.execute("SELECT collection_id FROM documents WHERE id = ?", (document_id,))
            row = cur.fetchone()
            if not row:
                return None
            # explicit deletes: SQLite foreign keys may be off on old databases
            for table in ("facts", "security_flags", "chunks", "documents"):
                col = "id" if table == "documents" else "document_id"
                cur.execute(f"DELETE FROM {table} WHERE {col} = ?", (document_id,))
        self._bump(row["collection_id"])
        return row["collection_id"]

    def delete_collection(self, collection_id: str) -> list[str]:
        with self.tx() as cur:
            cur.execute("SELECT id FROM documents WHERE collection_id = ?", (collection_id,))
            ids = [r["id"] for r in cur.fetchall()]
            for table in ("facts", "security_flags", "chunks", "documents"):
                cur.execute(f"DELETE FROM {table} WHERE collection_id = ?", (collection_id,))
        self._bump(collection_id)
        return ids

    def _vec(self, v):
        if v is None:
            return None
        if self.dialect == "sqlite":
            return _to_blob(v)
        return np.asarray(v, dtype=np.float32)

    def _unvec(self, v) -> np.ndarray | None:
        if v is None:
            return None
        if self.dialect == "sqlite":
            return _from_blob(v)
        if hasattr(v, "to_numpy"):  # pgvector >= 0.3 returns a Vector object
            return np.asarray(v.to_numpy(), dtype=np.float32)
        return np.asarray(v, dtype=np.float32)

    # ------------------------------------------------------------ reads

    def documents(self, collection_id: str) -> list[dict]:
        with self.tx() as cur:
            cur.execute("SELECT * FROM documents WHERE collection_id = ? ORDER BY created_at", (collection_id,))
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["meta"] = json.loads(r.pop("meta_json") or "{}")
            r["ocr_used"] = bool(r["ocr_used"])
        return rows

    def document(self, document_id: str) -> dict | None:
        with self.tx() as cur:
            cur.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
            r = cur.fetchone()
        if not r:
            return None
        r = dict(r)
        r["meta"] = json.loads(r.pop("meta_json") or "{}")
        r["ocr_used"] = bool(r["ocr_used"])
        return r

    def find_by_hash(self, collection_id: str, sha256: str) -> dict | None:
        with self.tx() as cur:
            cur.execute("SELECT id, filename FROM documents WHERE collection_id = ? AND sha256 = ?", (collection_id, sha256))
            r = cur.fetchone()
        return dict(r) if r else None

    def chunks(self, collection_id: str) -> list[dict]:
        with self.tx() as cur:
            cur.execute("SELECT * FROM chunks WHERE collection_id = ? ORDER BY document_id, ordinal", (collection_id,))
            rows = [dict(r) for r in cur.fetchall()]
        return [self._chunk_row(r) for r in rows]

    def document_chunks(self, document_id: str) -> list[dict]:
        with self.tx() as cur:
            cur.execute("SELECT * FROM chunks WHERE document_id = ? ORDER BY ordinal", (document_id,))
            rows = [dict(r) for r in cur.fetchall()]
        return [self._chunk_row(r, with_embedding=False) for r in rows]

    def chunk(self, chunk_id: str) -> dict | None:
        with self.tx() as cur:
            cur.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,))
            r = cur.fetchone()
        return self._chunk_row(dict(r), with_embedding=False) if r else None

    def _chunk_row(self, r: dict, with_embedding: bool = True) -> dict:
        r["boxes"] = json.loads(r.pop("boxes_json") or "[]")
        r["flags"] = json.loads(r.pop("flags_json") or "[]")
        emb = r.pop("embedding", None)
        if with_embedding:
            r["embedding"] = self._unvec(emb)
        return r

    def facts(self, collection_id: str) -> list[dict]:
        with self.tx() as cur:
            cur.execute("SELECT * FROM facts WHERE collection_id = ?", (collection_id,))
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["value"] = r["value_num"] if r["value_num"] is not None else r["value_text"]
            r["key"] = r.pop("fact_key")
            r["embedding"] = self._unvec(r.pop("embedding"))
        return rows

    def flags(self, collection_id: str) -> list[dict]:
        with self.tx() as cur:
            cur.execute("SELECT * FROM security_flags WHERE collection_id = ?", (collection_id,))
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["reasons"] = json.loads(r.pop("reasons_json") or "[]")
            r["bbox"] = json.loads(r.pop("bbox_json") or "null")
        return rows

    def dense_candidates(self, collection_id: str, qvec: np.ndarray, k: int) -> list[tuple[str, float]] | None:
        """Cosine search in pgvector, restricted to one investigation. None on SQLite.

        The collection filter runs first (MATERIALIZED), then an exact `<=>` ranking. A global
        HNSW index is deliberately not used: with many investigations in one table, HNSW returns
        its ef_search nearest rows across *all* of them and the collection filter then discards
        them, which returned zero rows in testing. Investigations are small, so exact is fast.
        """
        if self.dialect != "postgres":
            return None
        q = np.asarray(qvec, dtype=np.float32)
        with self.tx() as cur:
            cur.execute(
                "WITH c AS MATERIALIZED (SELECT id, embedding FROM chunks WHERE collection_id = ?)"
                " SELECT id, 1 - (embedding <=> ?) AS score FROM c ORDER BY embedding <=> ? LIMIT ?",
                (collection_id, q, q, k))
            return [(r["id"], float(r["score"])) for r in cur.fetchall()]


class _Cursor:
    """Uniform '?' placeholders across sqlite3 and psycopg."""

    def __init__(self, cur, dialect: str):
        self._cur = cur
        self._pg = dialect == "postgres"

    def execute(self, sql: str, params: tuple = ()):
        if self._pg:
            sql = sql.replace("?", "%s").replace(" BLOB", " BYTEA")
        return self._cur.execute(sql, params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()
