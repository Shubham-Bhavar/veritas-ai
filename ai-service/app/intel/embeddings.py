"""Local embeddings (fastembed / ONNX) and a cross-encoder reranker.

If the embedding model cannot be loaded (offline first run, missing cache) the service
falls back to a deterministic hashed bag-of-words embedding. Retrieval then degrades to
mostly-lexical matching; /health reports which mode is active so nobody is misled.
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading

import numpy as np

from app.config import settings
from app.ingest.text_utils import content_terms
from app.store.store import DIM

log = logging.getLogger(__name__)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    def __init__(self):
        self._model = None
        self._reranker = None
        self._lock = threading.Lock()
        self.mode = "uninitialised"
        self.reranker_mode = "disabled"

    def load(self):
        with self._lock:
            if self._model is not None or self.mode == "hashed-fallback":
                return
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(settings.embedding_model, cache_dir=settings.model_cache_dir)
                list(self._model.embed(["warm-up"]))
                self.mode = settings.embedding_model
            except Exception as e:
                log.warning("Embedding model unavailable (%s); using hashed lexical fallback", e)
                self.mode = "hashed-fallback"
            if settings.enable_reranker:
                try:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    self._reranker = TextCrossEncoder(settings.reranker_model, cache_dir=settings.model_cache_dir)
                    list(self._reranker.rerank("warm", ["up"]))
                    self.reranker_mode = settings.reranker_model
                except Exception as e:
                    log.warning("Reranker unavailable (%s); ranking without it", e)
                    self.reranker_mode = "unavailable"

    @property
    def semantic(self) -> bool:
        return self._model is not None

    def embed(self, texts: list[str]) -> np.ndarray:
        self.load()
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        if self._model is not None:
            vecs = np.array(list(self._model.embed(texts, batch_size=32)), dtype=np.float32)
        else:
            vecs = np.stack([_hashed(t) for t in texts])
        return _normalize(vecs)

    def embed_query(self, text: str) -> np.ndarray:
        if self._model is not None or self.mode == "uninitialised":
            self.load()
        prefix = QUERY_PREFIX if self._model is not None and "bge" in settings.embedding_model.lower() else ""
        return self.embed([prefix + text])[0]

    def rerank(self, query: str, docs: list[str]) -> list[float] | None:
        """Relevance in 0..1 per doc, or None when no reranker is loaded."""
        self.load()
        if self._reranker is None or not docs:
            return None
        logits = list(self._reranker.rerank(query, docs, batch_size=16))
        return [1 / (1 + math.exp(-float(x))) for x in logits]


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return (m / norms).astype(np.float32)


def _hashed(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    terms = content_terms(text)
    for t in terms + [f"{a}_{b}" for a, b in zip(terms, terms[1:])]:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
    return v


embedder = Embedder()
