"""Evidence graph for one answer: Documents -> Evidence -> Claims -> Verdict, plus conflict links.

Every node maps to something the user can open (a document, a passage, a claim, a conflict),
so the graph is a navigation surface over the actual reasoning, not decoration.
"""
from __future__ import annotations


def build(result: dict, idx) -> dict:
    nodes, edges = [], []
    verdict = result["verdict"]
    nodes.append({"id": "verdict", "type": "verdict", "label": verdict["headline"], "status": verdict["status"],
                  "layer": 3})

    doc_ids = list(dict.fromkeys(e["document_id"] for e in result["evidence"]))
    for d in doc_ids:
        doc = idx.docs.get(d)
        if not doc:
            continue
        nodes.append({"id": f"doc:{d}", "type": "document", "label": doc["filename"], "role": doc["role"],
                      "doc_date": doc["doc_date"], "document_id": d, "layer": 0,
                      "superseded": d in _superseded(idx)})
    for e in result["evidence"]:
        nodes.append({"id": f"ev:{e['id']}", "type": "evidence", "label": e["id"], "quote": e["quote"][:160],
                      "stance": e["stance"], "page": e["page"], "section": e["section"], "evidence_id": e["id"],
                      "chunk_id": e["chunk_id"], "document_id": e["document_id"], "layer": 1})
        edges.append({"source": f"doc:{e['document_id']}", "target": f"ev:{e['id']}", "type": "contains"})
    for c in result["claims"]:
        nodes.append({"id": f"cl:{c['id']}", "type": "claim", "label": c["text"][:120], "status": c["status"],
                      "claim_id": c["id"], "layer": 2})
        for eid in c["evidence"]:
            ev = next((e for e in result["evidence"] if e["id"] == eid), None)
            stance = ev["stance"] if ev else "supports"
            edges.append({"source": f"ev:{eid}", "target": f"cl:{c['id']}",
                          "type": "contradicts" if stance == "contradicts" else "context" if stance == "context" else "supports"})
        edges.append({"source": f"cl:{c['id']}", "target": "verdict", "type": "informs", "status": c["status"]})

    by_chunk_sentence = {}
    for e in result["evidence"]:
        by_chunk_sentence.setdefault(e["chunk_id"], []).append(e)
    for conf in result["conflicts"]:
        cid = f"cf:{conf['id']}"
        nodes.append({"id": cid, "type": "conflict", "label": conf["summary"], "severity": conf["severity"],
                      "status": conf["status"], "conflict_id": conf["id"], "layer": 1.5})
        linked = []
        for s in conf["sources"]:
            for e in by_chunk_sentence.get(s["chunk_id"], []):
                if e["highlight"]["start"] == s["sent_start"] or len(by_chunk_sentence[s["chunk_id"]]) == 1:
                    linked.append(e["id"])
        for eid in dict.fromkeys(linked):
            edges.append({"source": f"ev:{eid}", "target": cid, "type": "conflict"})
        for c in result["claims"]:
            if conf["id"] in c["conflict_ids"]:
                edges.append({"source": cid, "target": f"cl:{c['id']}", "type": "undermines"})
    return {"nodes": nodes, "edges": edges}


def _superseded(idx) -> set[str]:
    from app.intel.conflicts import supersession_map

    return set(supersession_map(idx))
