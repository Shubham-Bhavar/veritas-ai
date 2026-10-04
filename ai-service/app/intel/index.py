"""In-memory snapshot of one collection plus hybrid retrieval over it."""
from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from app.ingest.text_utils import GENERIC_QUERY_WORDS, content_terms
from app.intel.embeddings import embedder
from app.store.store import DIM, Store


@dataclass
class Hit:
    chunk: dict
    dense: float
    lexical: float
    rerank: float | None
    score: float

    @property
    def relevance(self) -> float:
        """0..1 relevance used for gating and confidence."""
        if self.rerank is not None:
            return round(0.75 * self.rerank + 0.25 * max(0.0, min(1.0, (self.dense - 0.45) / 0.4)), 3)
        return round(max(0.0, min(1.0, (self.dense - 0.45) / 0.4)) * 0.7 + 0.3 * self.lexical, 3)


@dataclass
class CollectionIndex:
    collection_id: str
    version: int
    docs: dict[str, dict]
    chunks: list[dict]
    chunk_by_id: dict[str, dict]
    emb: np.ndarray
    facts: list[dict]
    fact_emb: np.ndarray
    flags: list[dict]
    df: Counter = field(default_factory=Counter)
    tf: list[Counter] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    vocab: set[str] = field(default_factory=set)
    cache: dict = field(default_factory=dict)  # derived results (conflicts...) for this version
    # On PostgreSQL the dense ranking comes from pgvector; on SQLite from the in-memory matrix.
    dense_search: Callable[[np.ndarray, int], list[tuple[str, float]]] | None = None

    @property
    def avgdl(self) -> float:
        return (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0

    def bm25(self, terms: list[str], k1: float = 1.4, b: float = 0.75) -> np.ndarray:
        n = len(self.chunks)
        scores = np.zeros(n, dtype=np.float32)
        if not n:
            return scores
        avg = self.avgdl
        for t in set(terms):
            df = self.df.get(t, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if f:
                    scores[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.lengths[i] / avg))
        return scores


_cache: dict[str, CollectionIndex] = {}
_lock = threading.Lock()


def get_index(store: Store, collection_id: str) -> CollectionIndex:
    v = store.version(collection_id)
    idx = _cache.get(collection_id)
    if idx is not None and idx.version == v:
        return idx
    with _lock:
        idx = _cache.get(collection_id)
        if idx is not None and idx.version == v:
            return idx
        idx = _build(store, collection_id, v)
        _cache[collection_id] = idx
        return idx


def _build(store: Store, collection_id: str, version: int) -> CollectionIndex:
    docs = {d["id"]: d for d in store.documents(collection_id)}
    chunks = [c for c in store.chunks(collection_id) if c["document_id"] in docs]
    facts = [f for f in store.facts(collection_id) if f["document_id"] in docs]
    flags = store.flags(collection_id)
    emb = np.stack([c.pop("embedding") for c in chunks]) if chunks else np.zeros((0, DIM), np.float32)
    fact_emb = np.stack([f.pop("embedding") for f in facts]) if facts else np.zeros((0, DIM), np.float32)
    idx = CollectionIndex(collection_id, version, docs, chunks, {c["id"]: c for c in chunks}, emb, facts, fact_emb, flags)
    for c in chunks:
        doc = docs[c["document_id"]]
        terms = content_terms(f"{doc['title']} {c['section']} {c['text']}")
        tf = Counter(terms)
        idx.tf.append(tf)
        idx.lengths.append(len(terms))
        idx.df.update(tf.keys())
        idx.vocab.update(tf.keys())
    for f in facts:
        f["chunk"] = idx.chunk_by_id.get(f["chunk_id"])
    if store.dialect == "postgres":
        idx.dense_search = lambda q, k: store.dense_candidates(collection_id, q, k) or []
    return idx


GENERIC_STEMS = {t for w in GENERIC_QUERY_WORDS for t in content_terms(w)}


def question_terms(question: str) -> list[str]:
    return [t for t in content_terms(question) if t not in GENERIC_STEMS]


def missing_terms(idx: CollectionIndex, question: str) -> list[str]:
    """Specific question words that appear nowhere in the collection."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", question)
    missing = []
    for w in words:
        terms = content_terms(w)
        if not terms or w.lower() in GENERIC_QUERY_WORDS:
            continue
        if not any(t in idx.vocab for t in terms):
            missing.append(w.lower())
    return list(dict.fromkeys(missing))


def retrieve(idx: CollectionIndex, query: str, k: int = 8, per_doc: int = 3,
             doc_ids: set[str] | None = None, pool: int = 30) -> list[Hit]:
    if not idx.chunks:
        return []
    qv = embedder.embed_query(query)
    dense = idx.emb @ qv
    lex = idx.bm25(question_terms(query) or content_terms(query))
    allowed = np.array([doc_ids is None or c["document_id"] in doc_ids for c in idx.chunks])

    # Reciprocal-rank fusion of the dense and lexical rankings.
    rrf = np.zeros(len(idx.chunks))
    if idx.dense_search is not None:
        position = {c["id"]: i for i, c in enumerate(idx.chunks)}
        dense_order = [position[cid] for cid, _ in idx.dense_search(qv, max(pool, 50)) if cid in position]
    else:
        dense_order = [int(i) for i in np.argsort(-dense) if dense[i] > 0]
    lex_order = [int(i) for i in np.argsort(-lex) if lex[i] > 0]
    for order in (dense_order, lex_order):
        for rank, i in enumerate(order):
            rrf[i] += 1.0 / (60 + rank)
    rrf[~allowed] = -1
    cand = [int(i) for i in np.argsort(-rrf)[:pool] if rrf[i] > 0]
    if not cand:
        return []
    lex_max = float(lex.max()) or 1.0
    texts = [f"{idx.chunks[i]['section']}: {idx.chunks[i]['text']}" for i in cand]
    rr = embedder.rerank(query, texts)
    hits = []
    for j, i in enumerate(cand):
        d, l = float(dense[i]), float(lex[i]) / lex_max
        r = rr[j] if rr is not None else None
        score = (0.6 * r + 0.25 * d + 0.15 * l) if r is not None else (0.65 * d + 0.35 * l)
        hits.append(Hit(idx.chunks[i], d, l, r, score))
    hits.sort(key=lambda h: -h.score)
    out, per = [], Counter()
    for h in hits:
        if per[h.chunk["document_id"]] >= per_doc:
            continue
        per[h.chunk["document_id"]] += 1
        out.append(h)
        if len(out) >= k:
            break
    return out
