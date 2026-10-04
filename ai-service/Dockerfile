# VERITAS evidence service: extraction, OCR, embeddings, retrieval, conflicts, reasoning.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_CACHE_DIR=/models \
    EVIDENCE_STORAGE_DIR=/data/files

# OpenCV (used by RapidOCR) needs these shared libraries.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding and re-ranking models into the image so the service starts offline.
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models'); TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2', cache_dir='/models')"

COPY app ./app

RUN useradd --system --uid 10001 veritas && mkdir -p /data/files && chown -R veritas /data /models
USER veritas

EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=5 CMD curl -fs http://localhost:8001/health || exit 1
# One worker: the per-collection index cache lives in process memory.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
