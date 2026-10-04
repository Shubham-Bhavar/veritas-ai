"""End-to-end reasoning over the real demo investigation (real extraction, OCR, embeddings)."""
from app.intel import conflicts as cf
from app.intel.compare import compare
from app.intel.investigate import investigate


def ask(demo, q):
    return investigate(demo["idx"](), q)


def test_conflict_radar_finds_exactly_the_real_disagreements(demo):
    found = cf.detect(demo["idx"]())
    unresolved = [c for c in found if c["status"] == "UNRESOLVED"]
    assert {c["kind"] for c in unresolved} == {"value", "statement"}
    income = next(c for c in unresolved if c["kind"] == "value")
    assert income["severity"] == "HIGH" and set(income["values"]) == {"₹2,50,000", "₹2,00,000"}
    assert "does not establish" in income["reason"]  # newer date is reported, not used to decide
    statement = next(c for c in unresolved if c["kind"] == "statement")
    assert "distance" in statement["sources"][0]["sentence"]
    # renewal marks (55%) are a different attribute from eligibility marks (60%)
    assert not any("55%" in c["values"] for c in found)


def test_amendment_and_supersession_resolve_with_quoted_evidence(demo):
    found = cf.detect(demo["idx"]())
    deadline = next(c for c in found if c["type"] == "date")
    assert deadline["status"] == "RESOLVED"
    assert "15 August 2026" in deadline["resolution"] and "partial modification" in deadline["resolution"]
    statuses = {s["filename"]: s["status"] for s in deadline["sources"]}
    assert statuses["Scholarship_Guidelines_2026.pdf"] == "amended"
    assert statuses["Scholarship_Guidelines_2025.pdf"] == "superseded"


def test_strong_evidence_high_confidence(demo):
    r = ask(demo, "What minimum aggregate marks are required to qualify?")
    assert r["verdict"]["status"] == "SUPPORTED"
    assert "60%" in r["verdict"]["headline"]
    assert r["confidence"]["score"] >= 0.8
    assert len({e["document_id"] for e in r["evidence"] if e["stance"] == "supports"}) >= 2


def test_conflicting_documents_are_not_silently_resolved(demo):
    r = ask(demo, "What is the annual family income limit for eligibility?")
    assert r["verdict"]["status"] == "UNCERTAIN"
    assert r["conflicts"] and r["conflicts"][0]["status"] == "UNRESOLVED"
    assert r["confidence"]["score"] <= 0.55


def test_flagship_eligibility_question(demo):
    r = ask(demo, "Is Priya Sharma eligible for the scholarship, and what evidence supports the conclusion?")
    assert r["verdict"]["headline"] == "Likely eligible"
    by_criterion = {c["criterion"]: c for c in r["claims"]}
    assert by_criterion["annual family income"]["status"] == "SUPPORTED"
    assert by_criterion["age"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert by_criterion["required documents"]["status"] == "SUPPORTED"
    # income is corroborated by the application form AND the OCR-read income certificate
    income_docs = {e["filename"] for e in r["evidence"] if e["id"] in by_criterion["annual family income"]["evidence"]}
    assert {"Application_Form_Priya_Sharma.pdf", "Income_Certificate_Priya_Sharma.png"} <= income_docs
    # every evidence item points at an exact location
    assert all(e["chunk_id"] and e["quote"] for e in r["evidence"])


def test_material_conflict_makes_eligibility_undetermined(demo):
    r = ask(demo, "Is Rahul Verma eligible for the scholarship?")
    assert r["verdict"]["status"] == "UNCERTAIN"
    income = next(c for c in r["claims"] if c["criterion"] == "annual family income")
    assert income["status"] == "UNCERTAIN" and income["conflict_ids"]
    age = next(c for c in r["claims"] if c["criterion"] == "age")
    assert age["status"] == "SUPPORTED" and "22 years" in age["text"]


def test_prompt_injection_in_document_is_neutralised(demo):
    r = ask(demo, "Is Rahul Verma eligible for the scholarship?")
    assert r["security"] and r["security"][0]["kind"] == "hidden_text"
    assert r["verdict"]["status"] != "SUPPORTED"
    assert r["confidence"]["score"] < 1.0
    sop = demo["ids"]["Rahul_Verma_Statement_of_Purpose.pdf"]
    assert not any(f["document_id"] == sop for f in demo["idx"]().facts)
    assert not any("administrator mode" in e["quote"] for e in r["evidence"])


def test_missing_information_gives_insufficient_evidence(demo):
    r = ask(demo, "Does the scholarship cover hostel accommodation fees?")
    assert r["verdict"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "hostel" in r["claims"][0]["text"]
    assert all(e["stance"] == "context" for e in r["evidence"])


def test_irrelevant_question(demo):
    r = ask(demo, "What is the capital of France?")
    assert r["verdict"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert r["confidence"]["score"] <= 0.25


def test_ambiguous_subject_is_not_guessed(demo):
    r = ask(demo, "Is this student eligible?")
    assert r["verdict"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "Priya Sharma" in r["claims"][0]["text"] and "Rahul Verma" in r["claims"][0]["text"]


def test_contradictory_statements_answer_is_uncertain(demo):
    r = ask(demo, "Are students in distance-learning programmes eligible?")
    assert r["verdict"]["status"] == "UNCERTAIN"
    assert any(c["kind"] == "statement" for c in r["conflicts"])


def test_graph_links_real_reasoning(demo):
    r = ask(demo, "Is Priya Sharma eligible for the scholarship?")
    g = r["graph"]
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert {n["type"] for n in g["nodes"]} >= {"document", "evidence", "claim", "verdict", "conflict"}


def test_pgvector_search_is_scoped_and_matches_exact_ranking(demo, store):
    """Runs on PostgreSQL only (TEST_EVIDENCE_DATABASE_URL). Guards two real bugs: pgvector
    returning Vector objects, and a global HNSW index dropping every per-investigation row."""
    import numpy as np
    import pytest

    from app.intel.embeddings import embedder

    if store.dialect != "postgres":
        pytest.skip("pgvector only")
    idx = demo["idx"]()
    q = embedder.embed_query("annual family income limit")
    ann = store.dense_candidates(demo["cid"], q, 10)
    assert len(ann) == 10
    assert all(cid in idx.chunk_by_id for cid, _ in ann)          # never another investigation's rows
    exact = np.argsort(-(idx.emb @ q))[:10]
    assert [cid for cid, _ in ann][:5] == [idx.chunks[i]["id"] for i in exact[:5]]


def test_compare_detects_changed_requirements(demo):
    idx = demo["idx"]()
    r = compare(idx, demo["ids"]["Scholarship_Guidelines_2026.pdf"], demo["ids"]["Scholarship_Guidelines_2025.pdf"])
    assert r["before"]["filename"] == "Scholarship_Guidelines_2025.pdf"  # ordered by date
    assert r["relation"] and "supersedes" in r["relation"]
    changed = {(c["before"]["display"], c["after"]["display"]) for c in r["changes"] if c["kind"] == "changed" and c["category"] != "requirement"}
    assert ("₹2,00,000", "₹2,50,000") in changed
    assert ("31 August 2025", "31 July 2026") in changed
    added = " ".join(c["after"]["sentence"] for c in r["changes"] if c["kind"] == "added")
    assert "distance-learning" in added and "Physical applications" in added
