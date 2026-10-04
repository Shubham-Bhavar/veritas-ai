"""Conflict Radar: find where documents disagree, and resolve only what the evidence resolves.

1. Facts of the same type are clustered by *attribute* (value-masked clause embeddings,
   label overlap, compatible comparators) across different documents.
2. Supersession and amendment are read from the documents themselves: a cluster value from
   a document that another document explicitly supersedes, or that an amendment sentence
   explicitly changes, is marked inactive and the reason is quoted.
3. Whatever still disagrees is UNRESOLVED. A later date is reported, never used to pick a winner.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import date

import numpy as np

from app.ingest.metadata import AMEND, SUPERSEDE
from app.ingest.text_utils import content_terms, jaccard
from app.intel.index import CollectionIndex

VALUE_TYPES = {"money", "percent", "score", "age", "date"}
SAME_ATTR = 0.86          # embedding similarity that alone means "same attribute"
SAME_ATTR_WITH_LABEL = 0.74
ASSERTION_SAME = 0.84
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


# ------------------------------------------------------------------ supersession

def _title_terms(doc: dict) -> set[str]:
    return {t for t in content_terms(doc["title"] or doc["filename"]) if not t.isdigit()}


def references(sentence: str, target: dict) -> bool:
    """Does an amendment/supersession sentence point at this document?"""
    s = sentence.lower()
    for ref in target["meta"].get("references", []):
        if ref.lower() in s:
            return True
    years = set(target["meta"].get("years", []))
    sent_years = {int(y) for y in re.findall(r"\b(20\d{2})\b", sentence)}
    title = _title_terms(target)
    overlap = len(title & set(content_terms(sentence))) / max(1, len(title))
    if years and not (years & sent_years):
        return False
    return overlap >= 0.6


def supersession_map(idx: CollectionIndex) -> dict[str, dict]:
    """document_id -> {by: document_id, sentence: ...} for documents explicitly superseded."""
    if "supersession" in idx.cache:
        return idx.cache["supersession"]
    out: dict[str, dict] = {}
    for b in idx.docs.values():
        for a in b["meta"].get("amendments", []):
            if a["kind"] != "supersede":
                continue
            for target in idx.docs.values():
                if target["id"] == b["id"] or target["role"] == "record":
                    continue
                if references(a["sentence"], target):
                    out[target["id"]] = {"by": b["id"], "sentence": a["sentence"]}
    idx.cache["supersession"] = out
    return out


# ------------------------------------------------------------------ clustering

def _comparable(a: dict, b: dict) -> bool:
    if a["type"] != b["type"]:
        return False
    ca, cb = a["comparator"], b["comparator"]
    if ca == cb:
        return True
    return {ca, cb} <= {"eq", "lte"} and a["type"] == "date"


def _label_overlap(a: dict, b: dict) -> float:
    return jaccard(set(content_terms(a["label"] or "")), set(content_terms(b["label"] or "")))


def same_attribute(idx: CollectionIndex, i: int, j: int, sim: float | None = None) -> bool:
    a, b = idx.facts[i], idx.facts[j]
    if not _comparable(a, b):
        return False
    if sim is None:
        sim = float(idx.fact_emb[i] @ idx.fact_emb[j])
    lab = _label_overlap(a, b)
    if sim >= SAME_ATTR and lab >= 0.2:
        return True
    return sim >= SAME_ATTR_WITH_LABEL and lab >= 0.5


def clusters(idx: CollectionIndex) -> list[list[int]]:
    """Attribute clusters over policy-side value facts (cached per collection version)."""
    if "clusters" in idx.cache:
        return idx.cache["clusters"]
    cand = [i for i, f in enumerate(idx.facts)
            if f["type"] in VALUE_TYPES and f["role"] in ("requirement", "statement")]
    pos = {i: p for p, i in enumerate(cand)}
    sims = idx.fact_emb[cand] @ idx.fact_emb[cand].T if cand else np.zeros((0, 0))
    member_of = {i: i for i in cand}
    groups: dict[int, list[int]] = {i: [i] for i in cand}

    def compatible(g1: list[int], g2: list[int]) -> bool:
        for i in g1:
            for j in g2:
                fi, fj = idx.facts[i], idx.facts[j]
                if fi["document_id"] == fj["document_id"]:
                    # cannot-link: a document never states one attribute twice with different values
                    if _value_key(fi) != _value_key(fj):
                        return False
                    continue
                # complete linkage: every cross-document pair must describe the same attribute
                if not same_attribute(idx, i, j, float(sims[pos[i], pos[j]])):
                    return False
        return True

    pairs = []
    for a in range(len(cand)):
        for b in range(a + 1, len(cand)):
            i, j = cand[a], cand[b]
            if idx.facts[i]["document_id"] != idx.facts[j]["document_id"] and same_attribute(idx, i, j, float(sims[a, b])):
                pairs.append((float(sims[a, b]), i, j))
    for _, i, j in sorted(pairs, reverse=True):  # most similar first (agglomerative)
        gi, gj = member_of[i], member_of[j]
        if gi == gj or not compatible(groups[gi], groups[gj]):
            continue
        groups[gi].extend(groups.pop(gj))
        for m in groups[gi]:
            member_of[m] = gi
    result = [g for g in groups.values() if len({idx.facts[i]["document_id"] for i in g}) >= 2]
    idx.cache["clusters"] = result
    return result


def _value_key(f: dict):
    if f["type"] == "age":
        return (f["value"], f.get("value_hi"))
    return f["value"]


def _cluster_label(facts: list[dict]) -> str:
    labels = Counter(f["label"] for f in facts if f["label"])
    if not labels:
        return facts[0]["type"]
    best = max(labels.items(), key=lambda kv: (kv[1], len(kv[0].split()) >= 2, -len(kv[0])))
    return best[0]


def _source(idx: CollectionIndex, f: dict, status: str = "active", note: str | None = None) -> dict:
    doc = idx.docs[f["document_id"]]
    chunk = f.get("chunk") or {}
    return {
        "fact_id": f["id"], "document_id": doc["id"], "filename": doc["filename"], "title": doc["title"],
        "doc_date": doc["doc_date"], "chunk_id": f["chunk_id"], "page": chunk.get("page"), "section": chunk.get("section"),
        "sentence": f["sentence"], "value": f["display"], "comparator": f["comparator"], "status": status, "note": note,
        "sent_start": f["sent_start"], "sent_end": f["sent_end"],
    }


def resolve_cluster(idx: CollectionIndex, members: list[int]) -> dict:
    """Mark each member active / superseded / amended, using only statements in the documents."""
    sup = supersession_map(idx)
    facts = [idx.facts[i] for i in members]
    status: dict[str, tuple[str, str | None]] = {}
    for f in facts:
        s = sup.get(f["document_id"])
        if s:
            by = idx.docs[s["by"]]
            status[f["id"]] = ("superseded", f"Superseded by {by['filename']}: “{s['sentence']}”")
    # Amendments: a fact whose own sentence amends another document overrides that document's value.
    for f in facts:
        if not AMEND.search(f["sentence"]) and not SUPERSEDE.search(f["sentence"]):
            continue
        for g in facts:
            if g["document_id"] == f["document_id"] or g["id"] in status:
                continue
            if references(f["sentence"], idx.docs[g["document_id"]]):
                status[g["id"]] = ("amended", f"Amended by {idx.docs[f['document_id']]['filename']}: “{f['sentence']}”")
    active = [f for f in facts if f["id"] not in status]
    return {"facts": facts, "status": status, "active": active}


def _severity(facts: list[dict], resolved: bool) -> str:
    if resolved:
        return "LOW"
    types = {f["type"] for f in facts}
    comps = {f["comparator"] for f in facts}
    roles = {f["role"] for f in facts}
    if "requirement" in roles and types & {"money", "percent", "score", "age"} and comps & {"lte", "gte", "range"}:
        return "HIGH"
    if "date" in types or "requirement" in roles:
        return "MEDIUM"
    return "LOW"


def _newer(idx: CollectionIndex, facts: list[dict]) -> dict | None:
    dated = [(idx.docs[f["document_id"]]["doc_date"], f["document_id"]) for f in facts if idx.docs[f["document_id"]]["doc_date"]]
    if len({d for d, _ in dated}) < 2:
        return None
    d, doc_id = max(dated)
    return {"document_id": doc_id, "filename": idx.docs[doc_id]["filename"], "doc_date": d}


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "undated"
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def value_conflicts(idx: CollectionIndex) -> list[dict]:
    out = []
    for members in clusters(idx):
        res = resolve_cluster(idx, members)
        facts, status, active = res["facts"], res["status"], res["active"]
        all_values = {_value_key(f) for f in facts}
        if len(all_values) < 2:
            continue  # the documents agree
        active_values = {_value_key(f) for f in active}
        resolved = len(active_values) <= 1
        label = _cluster_label(facts)
        sources = [_source(idx, f, *(status.get(f["id"], ("active", None)))) for f in facts]
        sources.sort(key=lambda s: (s["status"] != "active", s["doc_date"] or ""), reverse=False)
        newer = _newer(idx, active if not resolved else facts)
        displays = list(dict.fromkeys(f["display"] for f in (active if not resolved else facts)))
        if resolved:
            kept = active[0] if active else facts[0]
            reasons = sorted({v[1] for v in status.values() if v[1]})
            resolution = (f"Resolved by evidence: {kept['display']} from {idx.docs[kept['document_id']]['filename']} applies. "
                          + " ".join(reasons))
            reason = "The documents state different values, but one of them is explicitly superseded or amended by another."
            recommendation = "No action needed; the superseding document is cited."
        else:
            docs_desc = " vs ".join(f"{idx.docs[f['document_id']]['filename']} ({f['display']})" for f in active)
            resolution = "Not automatically resolved."
            reason = (f"{len({f['document_id'] for f in active})} documents state different values for "
                      f"“{label}” ({docs_desc}) and none of them says it supersedes or amends the other.")
            if newer:
                reason += (f" {newer['filename']} is the most recently dated ({_fmt_date(newer['doc_date'])}), "
                           "but a later date alone does not establish which rule applies.")
            recommendation = "Confirm with the issuing authority which document governs before relying on this value."
        out.append({
            "kind": "value", "attribute": label, "type": facts[0]["type"],
            "severity": _severity(facts, resolved), "status": "RESOLVED" if resolved else "UNRESOLVED",
            "values": displays, "sources": sources, "resolution": resolution, "reason": reason,
            "recommendation": recommendation, "newer": newer, "fact_ids": [f["id"] for f in facts],
            "active_fact_ids": [f["id"] for f in active],
        })
    return out


def statement_conflicts(idx: CollectionIndex) -> list[dict]:
    sup = supersession_map(idx)
    items = [i for i, f in enumerate(idx.facts) if f["type"] == "assertion"]
    out, seen = [], set()
    if len(items) < 2:
        return out
    sims = idx.fact_emb[items] @ idx.fact_emb[items].T
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            fa, fb = idx.facts[items[a]], idx.facts[items[b]]
            if fa["document_id"] == fb["document_id"] or fa["value"] == fb["value"]:
                continue
            sim = float(sims[a, b])
            overlap = jaccard(set(content_terms(fa["sentence"])), set(content_terms(fb["sentence"])))
            if sim < ASSERTION_SAME or overlap < 0.3:
                continue
            key = tuple(sorted((fa["id"], fb["id"])))
            if key in seen:
                continue
            seen.add(key)
            superseded = [f for f in (fa, fb) if f["document_id"] in sup]
            resolved = bool(superseded)
            pos, neg = (fa, fb) if fa["value"] > 0 else (fb, fa)
            sources = []
            for f in (pos, neg):
                st = ("superseded", f"Superseded by {idx.docs[sup[f['document_id']]['by']]['filename']}") \
                    if f in superseded else ("active", None)
                sources.append(_source(idx, f, *st))
            topic = " ".join(w for w in re.findall(r"[a-z\-]+", neg["sentence"].lower())
                             if w in set(re.findall(r"[a-z\-]+", pos["sentence"].lower())) and len(w) > 3)[:80]
            out.append({
                "kind": "statement", "attribute": topic or "conflicting statements", "type": "assertion",
                "severity": "LOW" if resolved else ("HIGH" if re.search(r"eligib", pos["sentence"] + neg["sentence"], re.I) else "MEDIUM"),
                "status": "RESOLVED" if resolved else "UNRESOLVED",
                "values": ["affirms", "denies"], "sources": sources,
                "resolution": ("Resolved by evidence: the statement from a superseded document no longer applies."
                               if resolved else "Not automatically resolved."),
                "reason": (f"{pos['document_id'] and idx.docs[pos['document_id']]['filename']} affirms what "
                           f"{idx.docs[neg['document_id']]['filename']} denies, about the same subject "
                           f"(statement similarity {sim:.2f})."),
                "recommendation": "Check which authority's rule applies to this case before deciding.",
                "newer": _newer(idx, [pos, neg]), "fact_ids": [pos["id"], neg["id"]],
                "active_fact_ids": [f["id"] for f in (pos, neg) if f not in superseded],
            })
    return out


def detect(idx: CollectionIndex) -> list[dict]:
    """All conflicts in the collection, numbered, most severe first (cached per version)."""
    if "conflicts" in idx.cache:
        return idx.cache["conflicts"]
    found = value_conflicts(idx) + statement_conflicts(idx)
    found.sort(key=lambda c: (c["status"] != "UNRESOLVED", SEVERITY_ORDER[c["severity"]], c["attribute"]))
    for n, c in enumerate(found, 1):
        c["number"] = n
        c["id"] = "CF-" + hashlib.sha1("|".join(sorted(c["fact_ids"])).encode()).hexdigest()[:8]
        if c["kind"] == "value":
            c["summary"] = f"{c['attribute'].capitalize()}: " + " vs ".join(c["values"])
        else:
            # "Students enrolled in distance-learning programmes are eligible…" -> its subject
            first = c["sources"][0]["sentence"]
            subject = re.split(r"\b(are|is|shall|must|may|will|can|cannot)\b", first, maxsplit=1)[0].strip(" ,")
            c["attribute"] = subject or c["attribute"]
            c["summary"] = f"{c['attribute']}: affirmed vs denied"
    idx.cache["conflicts"] = found
    return found


def conflicts_touching(idx: CollectionIndex, fact_ids: set[str] | None = None, chunk_ids: set[str] | None = None) -> list[dict]:
    out = []
    for c in detect(idx):
        if fact_ids and fact_ids & set(c["fact_ids"]):
            out.append(c)
        elif chunk_ids and chunk_ids & {s["chunk_id"] for s in c["sources"]}:
            out.append(c)
    return out


def cluster_of(idx: CollectionIndex, fact_index: int) -> list[int] | None:
    for members in clusters(idx):
        if fact_index in members:
            return members
    return None


def similar_facts(idx: CollectionIndex, vec: np.ndarray, types: set[str], roles: set[str], min_sim: float) -> list[tuple[int, float]]:
    if not idx.facts:
        return []
    sims = idx.fact_emb @ vec
    out = [(i, float(sims[i])) for i, f in enumerate(idx.facts)
           if f["type"] in types and f["role"] in roles and sims[i] >= min_sim]
    out.sort(key=lambda x: -x[1])
    return out
