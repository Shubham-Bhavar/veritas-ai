"""Compare two documents as a reviewer would: changed values, added and removed requirements."""
from __future__ import annotations

import re

import numpy as np

from app.ingest.text_utils import split_sentences
from app.intel import conflicts as cf
from app.intel.embeddings import embedder
from app.intel.index import CollectionIndex
from app.intel.investigate import NOT_ELIG_CONTEXT

RULE_SENTENCE = re.compile(r"\b(must|shall|required|mandatory|eligible|ineligible|not\s+accepted|will\s+not|only|may\s+be|"
                           r"minimum|maximum|at\s+least|not\s+exceed|last\s+date|deadline|supersede|credited|paid)\b", re.I)
MATCH = 0.80
SAME_SENTENCE = 0.90
REWORDED = 0.74


def _fact_items(idx: CollectionIndex, doc_id: str) -> list[int]:
    return [i for i, f in enumerate(idx.facts) if f["document_id"] == doc_id and f["role"] not in ("metadata",)
            and f["type"] != "assertion"]


def _side(idx: CollectionIndex, f: dict) -> dict:
    c = f.get("chunk") or {}
    return {"display": f["display"], "sentence": f["sentence"], "page": c.get("page"), "section": c.get("section"),
            "chunk_id": f["chunk_id"], "sent_start": f["sent_start"], "sent_end": f["sent_end"], "label": f["label"]}


def _significance(f: dict) -> str:
    section = (f.get("chunk") or {}).get("section", "")
    if (f["role"] == "requirement" and f["type"] in ("money", "percent", "score", "age") and f["comparator"] in ("lte", "gte", "range")
            and not NOT_ELIG_CONTEXT.search(section)):
        return "HIGH"
    if f["type"] == "date" or f["role"] == "requirement":
        return "MEDIUM"
    return "LOW"


def compare(idx: CollectionIndex, doc_a: str, doc_b: str) -> dict:
    a, b = idx.docs[doc_a], idx.docs[doc_b]
    # Order so that "before" is the older document when dates allow.
    swapped = bool(a["doc_date"] and b["doc_date"] and a["doc_date"] > b["doc_date"])
    if swapped:
        a, b = b, a
    fa, fb = _fact_items(idx, a["id"]), _fact_items(idx, b["id"])
    changes: list[dict] = []
    matched_a, matched_b = set(), set()
    pairs = []
    for i in fa:
        for j in fb:
            if not cf._comparable(idx.facts[i], idx.facts[j]):
                continue
            sim = float(idx.fact_emb[i] @ idx.fact_emb[j])
            lab = cf._label_overlap(idx.facts[i], idx.facts[j])
            if sim >= MATCH or (sim >= 0.72 and lab >= 0.5):
                pairs.append((sim + 0.1 * lab, i, j))
    for _, i, j in sorted(pairs, reverse=True):
        if i in matched_a or j in matched_b:
            continue
        matched_a.add(i)
        matched_b.add(j)
        x, y = idx.facts[i], idx.facts[j]
        if cf._value_key(x) != cf._value_key(y):
            changes.append({"kind": "changed", "category": "date" if x["type"] == "date" else "value", "label": y["label"] or x["label"],
                            "before": _side(idx, x), "after": _side(idx, y), "significance": _significance(y)})

    # Rule sentences that exist on one side only (added / removed requirements).
    sa = _rule_sentences(idx, a["id"])
    sb = _rule_sentences(idx, b["id"])
    fact_sentences = {idx.facts[i]["sentence"] for i in list(matched_a) + list(matched_b)}
    if sa and sb:
        va = embedder.embed([s for _, s, _ in sa])
        vb = embedder.embed([s for _, s, _ in sb])
        sims = va @ vb.T
        paired_a: set[int] = set()
        for k, (chunk, s, start) in enumerate(sb):
            if s in fact_sentences or float(np.max(sims[:, k])) >= SAME_SENTENCE:
                continue
            best = int(np.argmax(sims[:, k]))
            kept = float(np.max(sims[best, :])) >= SAME_SENTENCE  # that old sentence survives unchanged elsewhere
            if float(sims[best, k]) >= REWORDED and not kept and sa[best][1] not in fact_sentences and best not in paired_a:
                paired_a.add(best)
                changes.append({"kind": "changed", "category": "requirement", "label": _short(s),
                                "before": _sent_side(sa[best]), "after": _sent_side((chunk, s, start)), "significance": "MEDIUM"})
            else:
                changes.append({"kind": "added", "category": "requirement", "label": _short(s), "before": None,
                                "after": _sent_side((chunk, s, start)), "significance": "MEDIUM"})
        for k, (chunk, s, start) in enumerate(sa):
            if s in fact_sentences or k in paired_a or float(np.max(sims[k, :])) >= SAME_SENTENCE:
                continue
            changes.append({"kind": "removed", "category": "requirement", "label": _short(s), "before": _sent_side((chunk, s, start)),
                            "after": None, "significance": "MEDIUM"})
    for i in fa:
        if i not in matched_a and idx.facts[i]["sentence"] not in {c["before"]["sentence"] for c in changes if c["before"]}:
            f = idx.facts[i]
            if not any(c["before"] and c["before"]["sentence"] == f["sentence"] for c in changes):
                changes.append({"kind": "removed", "category": "value", "label": f["label"], "before": _side(idx, f), "after": None,
                                "significance": _significance(f)})
    for j in fb:
        if j not in matched_b:
            f = idx.facts[j]
            if not any(c["after"] and c["after"]["sentence"] == f["sentence"] for c in changes):
                changes.append({"kind": "added", "category": "value", "label": f["label"], "before": None, "after": _side(idx, f),
                                "significance": _significance(f)})

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    kind_order = {"changed": 0, "added": 1, "removed": 2}
    changes.sort(key=lambda c: (kind_order[c["kind"]], order[c["significance"]]))
    unchanged = len(matched_a) - sum(1 for c in changes if c["kind"] == "changed" and c["category"] != "requirement")
    sup = cf.supersession_map(idx)
    relation = None
    if sup.get(a["id"], {}).get("by") == b["id"]:
        relation = f"{b['filename']} explicitly supersedes {a['filename']}: “{sup[a['id']]['sentence']}”"
    elif sup.get(b["id"], {}).get("by") == a["id"]:
        relation = f"{a['filename']} explicitly supersedes {b['filename']}: “{sup[b['id']]['sentence']}”"
    return {
        "before": _doc(a), "after": _doc(b), "reordered": swapped, "relation": relation,
        "summary": {"changed": sum(1 for c in changes if c["kind"] == "changed"),
                    "added": sum(1 for c in changes if c["kind"] == "added"),
                    "removed": sum(1 for c in changes if c["kind"] == "removed"),
                    "unchanged_values": max(0, unchanged)},
        "changes": changes,
    }


def _doc(d: dict) -> dict:
    return {"document_id": d["id"], "filename": d["filename"], "title": d["title"], "doc_date": d["doc_date"], "role": d["role"]}


def _rule_sentences(idx: CollectionIndex, doc_id: str) -> list[tuple[dict, str, int]]:
    out = []
    for c in idx.chunks:
        if c["document_id"] != doc_id:
            continue
        for s in split_sentences(c["text"].replace("\n", " \n ")):
            s = s.strip()
            if 30 <= len(s) <= 400 and RULE_SENTENCE.search(s):
                out.append((c, s, max(0, c["text"].find(s))))
    return out


def _sent_side(item: tuple[dict, str, int]) -> dict:
    chunk, s, start = item
    return {"display": None, "sentence": s, "page": chunk["page"], "section": chunk["section"], "chunk_id": chunk["id"],
            "sent_start": start, "sent_end": start + len(s), "label": None}


def _short(s: str) -> str:
    return s if len(s) <= 90 else s[:87].rsplit(" ", 1)[0] + "…"
