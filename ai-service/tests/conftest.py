import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="veritas-test-"))
# TEST_EVIDENCE_DATABASE_URL=postgresql://... runs the whole suite against PostgreSQL + pgvector.
os.environ["EVIDENCE_DATABASE_URL"] = os.environ.get("TEST_EVIDENCE_DATABASE_URL") or (
    "sqlite:///" + str(_TMP / "evidence.db").replace("\\", "/"))
os.environ["EVIDENCE_STORAGE_DIR"] = str(_TMP / "files")
os.environ["AI_INTERNAL_TOKEN"] = "test-token-0123456789"
os.environ["LLM_ENABLED"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEMO = Path(__file__).resolve().parents[2] / "backend" / "src" / "main" / "resources" / "demo"


@pytest.fixture(scope="session")
def store():
    from app.config import settings
    from app.store.store import Store

    return Store(settings.database_url)


@pytest.fixture(scope="session")
def demo(store):
    """The full demo investigation, ingested once through the real pipeline."""
    from app.ingest.pipeline import ingest
    from app.intel.index import get_index

    cid = "test-demo-" + uuid.uuid4().hex[:8]
    ids = {}
    for f in sorted(DEMO.iterdir()):
        doc_id = str(uuid.uuid4())
        ingest(store, document_id=doc_id, collection_id=cid, filename=f.name, data=f.read_bytes())
        ids[f.name] = doc_id
    return {"cid": cid, "ids": ids, "idx": lambda: get_index(store, cid)}


def new_id() -> str:
    return str(uuid.uuid4())
