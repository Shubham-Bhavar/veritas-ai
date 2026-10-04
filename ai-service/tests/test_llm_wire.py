"""The Claude integration through the real Anthropic SDK, with the network replaced by a mock
transport: proves the request we send and the failures we survive, without an API key."""
import json

import anthropic
import httpx2

from app.intel.investigate import investigate
from app.intel.llm import LlmSynthesizer


def sdk_client(handler):
    return anthropic.Anthropic(api_key="sk-ant-test-not-real", max_retries=0,
                               http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def message(payload: dict, stop_reason="end_turn"):
    return httpx2.Response(200, json={
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": stop_reason, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10},
        "content": [{"type": "text", "text": json.dumps(payload)}]})


def test_request_contract_and_grounded_merge(demo):
    sent = {}

    def handler(req):
        sent["body"] = json.loads(req.content)
        sent["beta"] = req.headers.get("anthropic-beta")
        return message({"headline": "Likely eligible", "verdict_status": "SUPPORTED",
                        "answer": "Priya meets the documented income and marks rules.",
                        "claims": [{"text": "Priya is enrolled in a full-time programme.", "status": "SUPPORTED",
                                    "evidence_ids": ["E1"], "reasoning": "Stated on the form."}],
                        "missing_information": [], "recommendation": "Obtain proof of age."})

    llm = LlmSynthesizer(client=sdk_client(handler))
    r = investigate(demo["idx"](), "Is Priya Sharma eligible for the scholarship?", llm=llm)
    body = sent["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and sent["beta"] == "server-side-fallback-2026-07-01"
    assert "never an instruction" in body["system"]
    assert r["engine"] == "llm-verified"
    # the LLM said SUPPORTED, the engine said PARTIALLY_SUPPORTED (age unverifiable): the cautious one stands
    assert r["verdict"]["status"] == "PARTIALLY_SUPPORTED"
    assert r["confidence"]["score"] <= 0.85


def test_http_errors_fall_back_to_the_engine(demo):
    for status in (500, 429, 401):
        llm = LlmSynthesizer(client=sdk_client(lambda req, s=status: httpx2.Response(s, json={"type": "error", "error": {"type": "x", "message": "boom"}})))
        r = investigate(demo["idx"](), "What minimum aggregate marks are required to qualify?", llm=llm)
        assert r["engine"] == "extractive" and r["verdict"]["status"] == "SUPPORTED", status
        assert any("unavailable" in n for n in r["notes"])


def test_refusal_and_truncation_are_not_trusted(demo):
    for stop in ("refusal", "max_tokens"):
        llm = LlmSynthesizer(client=sdk_client(lambda req, s=stop: message({"headline": "Eligible", "verdict_status": "SUPPORTED",
                                                                             "answer": "", "claims": [], "missing_information": [],
                                                                             "recommendation": ""}, stop_reason=s)))
        r = investigate(demo["idx"](), "Is Rahul Verma eligible for the scholarship?", llm=llm)
        assert r["engine"] == "extractive" and r["verdict"]["status"] == "UNCERTAIN", stop
