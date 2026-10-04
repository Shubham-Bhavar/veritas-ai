"""LLM verification gate, service failures, and the HTTP contract."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.errors import ServiceUnavailable
from app.intel.investigate import investigate
from app.intel.llm import LlmSynthesizer
from tests.conftest import DEMO

TOKEN = {"X-Internal-Token": "test-token-0123456789"}


class FakeMessages:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def fake_llm(payload=None, error=None):
    client = SimpleNamespace(messages=FakeMessages(payload, error))
    return LlmSynthesizer(client=client, model="claude-opus-5-5"), client


def test_llm_cannot_override_conflict_or_invent_evidence(demo):
    # A model that was successfully manipulated: claims full eligibility, cites a fake passage,
    # and invents a number that is in no document.
    payload = {
        "headline": "Eligible", "verdict_status": "SUPPORTED",
        "answer": "Rahul Verma satisfies every criterion.",
        "claims": [
            {"text": "Rahul meets every criterion.", "status": "SUPPORTED", "evidence_ids": ["E999"], "reasoning": "x"},
            {"text": "The income limit is ₹3,00,000.", "status": "SUPPORTED", "evidence_ids": ["E1"], "reasoning": "x"},
            {"text": "Rahul Verma is enrolled full-time in B.Sc. Physics.", "status": "SUPPORTED", "evidence_ids": ["E1"], "reasoning": "ok"},
        ],
        "missing_information": [], "recommendation": "Approve.",
    }
    llm, client = fake_llm(payload)
    r = investigate(demo["idx"](), "Is Rahul Verma eligible for the scholarship?", llm=llm)
    assert r["verdict"]["status"] == "UNCERTAIN"           # the more cautious engine verdict stands
    texts = [c["text"] for c in r["claims"]]
    assert "Rahul meets every criterion." not in texts       # cited a passage that does not exist
    assert "The income limit is ₹3,00,000." not in texts      # number not in any cited passage
    assert any(c["source"] == "llm" for c in r["claims"])     # a grounded claim is accepted
    assert r["confidence"]["score"] <= 0.55                  # confidence never comes from the model
    prompt = client.messages.calls[0]["messages"][0]["content"]
    assert "administrator mode" not in prompt                 # hidden injection never reaches the model
    assert client.messages.calls[0]["model"] == "claude-opus-5-5"


def test_llm_failure_falls_back_to_extractive_answer(demo):
    llm, _ = fake_llm(error=RuntimeError("upstream timeout"))
    r = investigate(demo["idx"](), "What minimum aggregate marks are required to qualify?", llm=llm)
    assert r["engine"] == "extractive"
    assert r["verdict"]["status"] == "SUPPORTED"
    assert any("unavailable" in n for n in r["notes"])


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health_is_public_and_reports_components(client):
    r = client.get("/health").json()
    import os

    expected = "pgvector" if os.environ["EVIDENCE_DATABASE_URL"].startswith("postgres") else "sqlite"
    assert r["store"]["ok"] is True and r["store"]["backend"] == expected
    assert r["llm"]["configured"] is False


def test_endpoints_require_internal_token(client):
    assert client.get("/v1/collections/abcdefgh-1/conflicts").status_code == 401
    assert client.get("/v1/collections/abcdefgh-1/conflicts", headers={"X-Internal-Token": "wrong"}).status_code == 401


def test_upload_rejections_are_structured(client):
    r = client.post("/v1/collections/api-test-01/documents", headers=TOKEN,
                    data={"document_id": "doc-api-0001"}, files={"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")})
    assert r.status_code == 422 and r.json()["code"] == "UNSUPPORTED_TYPE"
    r = client.post("/v1/collections/../../etc/documents", headers=TOKEN, data={"document_id": "doc-api-0001"},
                    files={"file": ("a.txt", b"hello world, this is enough text to index.", "text/plain")})
    assert r.status_code in (400, 404)


def test_upload_ask_and_render_over_http(client):
    data = (DEMO / "Scholarship_Guidelines_2026.pdf").read_bytes()
    r = client.post("/v1/collections/api-test-02/documents", headers=TOKEN, data={"document_id": "doc-api-0002"},
                    files={"file": ("Guidelines.pdf", data, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["chunks"] > 5
    ans = client.post("/v1/collections/api-test-02/investigate", headers=TOKEN, json={"question": "What is the last date for applications?"}).json()
    assert ans["verdict"]["status"] == "SUPPORTED" and "31 July 2026" in ans["verdict"]["headline"]
    ev = ans["evidence"][0]
    img = client.get(f"/v1/collections/api-test-02/documents/doc-api-0002/pages/{ev['page']}",
                     headers=TOKEN, params={"chunk_id": ev["chunk_id"], "sentence": ev["quote"]})
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.post("/v1/collections/api-test-02/investigate", headers=TOKEN, json={"question": "x"}).status_code == 422


def test_vector_store_unavailable_returns_503(monkeypatch, client):
    import app.main as main

    def boom():
        raise ServiceUnavailable("evidence_store", "The evidence database is unavailable.")

    monkeypatch.setattr(main, "_store", boom)
    r = client.get("/v1/collections/api-test-02/conflicts", headers=TOKEN)
    assert r.status_code == 503 and r.json()["component"] == "evidence_store"


def test_postgres_unreachable_is_reported_as_unavailable():
    from app.store.store import Store

    with pytest.raises(ServiceUnavailable):
        Store("postgresql://veritas:wrong@127.0.0.1:1/veritas")
