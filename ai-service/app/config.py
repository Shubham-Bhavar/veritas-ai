"""Runtime settings, read once from the environment. No secrets have defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


@dataclass(frozen=True)
class Settings:
    # Shared secret the Spring backend sends in X-Internal-Token. Empty = reject everything
    # except /health (never run the service open by accident).
    internal_token: str = field(default_factory=lambda: os.getenv("AI_INTERNAL_TOKEN", ""))

    # sqlite:///path/to/file.db (local, zero-dependency) or postgresql://... (pgvector).
    database_url: str = field(default_factory=lambda: os.getenv(
        "EVIDENCE_DATABASE_URL", "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data" / "evidence.db")))
    storage_dir: Path = field(default_factory=lambda: Path(os.getenv(
        "EVIDENCE_STORAGE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "files"))))

    max_file_mb: int = field(default_factory=lambda: _int("MAX_FILE_MB", 25))
    max_pages: int = field(default_factory=lambda: _int("MAX_PAGES", 300))

    # Embeddings: a local ONNX model through fastembed. If it cannot load (offline, no
    # model cache) the service falls back to a hashed lexical embedding and says so in /health.
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"))
    reranker_model: str = field(default_factory=lambda: os.getenv("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2"))
    enable_reranker: bool = field(default_factory=lambda: _bool("ENABLE_RERANKER", True))
    enable_ocr: bool = field(default_factory=lambda: _bool("ENABLE_OCR", True))
    model_cache_dir: str = field(default_factory=lambda: os.getenv(
        "MODEL_CACHE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "models")))

    # LLM synthesis is optional. Without a key the extractive engine answers on its own.
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-opus-5-5"))
    llm_effort: str = field(default_factory=lambda: os.getenv("LLM_EFFORT", "medium"))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "90")))
    llm_enabled: bool = field(default_factory=lambda: _bool("LLM_ENABLED", True))

    @property
    def llm_configured(self) -> bool:
        return self.llm_enabled and bool(self.anthropic_api_key)


settings = Settings()
