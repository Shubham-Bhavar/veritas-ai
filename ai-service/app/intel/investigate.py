"""The investigation engine: question -> claims -> evidence -> conflicts -> verdict -> confidence.

Every claim cites evidence items, every evidence item points at an exact chunk (and sentence)
in a document, and the verdict is derived from the claims by explicit rules. When an LLM is
configured it may rephrase and add claims, but only through the verification gate in llm.py.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.ingest.metadata import find_dates
from app.ingest.text_utils import content_terms, split_sentences
from app.intel import conflicts as cf
from app.intel import confidence, graph
from app.intel.embeddings import embedder
from app.intel.facts import format_value, satisfies
from app.intel.index import CollectionIndex, Hit, missing_terms, question_terms, retrieve

log = logging.getLogger(__name__)

SUPPORTED, PARTIAL, CONTRADICTED, INSUFFICIENT, UNCERTAIN = (
    "SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE", "UNCERTAIN")
CAUTION = {SUPPORTED: 0, PARTIAL: 1, CONTRADICTED: 2, UNCERTAIN: 2, INSUFFICIENT: 3}

ELIGIBILITY_Q = re.compile(r"\b(eligib\w*|qualif(y|ies|ied|ication)|meet(s)?\s+the\s+(criteria|requirements|conditions)|entitled)\b", re.I)
THIS_PERSON = re.compile(r"\b(this|the)\s+(student|applicant|candidate|person|beneficiary|claimant|employee)\b", re.I)
TYPE_HINTS = [
    ("money", re.compile(r"\b(income|salary|fee|fees|amount|cost|price|rupees?|₹|allowance|reimbursement|stipend|ceiling|pay)\b", re.I)),
    ("percent", re.compile(r"\b(marks?|percentage|percent|%|attendance|aggregate)\b", re.I)),
    ("score", re.compile(r"\b(cgpa|gpa|grade\s+point)\b", re.I)),
    ("age", re.compile(r"\b(age|old|years\s+old)\b", re.I)),
    ("date", re.compile(r"\b(date|deadline|when|due|last\s+day|extended|until)\b", re.I)),
]
VALUE_Q = re.compile(r"\b(what\s+is|what's|what\s+are|how\s+much|how\s+many|when|which\s+date|limit|minimum|maximum|deadline|last\s+date)\b", re.I)
YESNO_Q = re.compile(r"^\s*(is|are|does|do|can|could|will|should|has|have|was|were|may)\b", re.I)
ELIG_CONTEXT = re.compile(r"\b(eligib\w*|criteri\w*|qualif\w*|conditions?|requirements?|limits?|ceiling|income|age|merit|academic|rules?)\b", re.I)
NOT_ELIG_CONTEXT = re.compile(r"\b(benefits?|reimburse\w*|allowance|renew\w*|disburse\w*|stipend|payment|exclusions?|verification)\b", re.I)
SUBMISSION = re.compile(r"\b(submit\w*|submission|applied|application\s+date|received\s+on|filed)\b", re.I)
DOC_LIST_SECTION = re.compile(r"(required|requirement|mandatory).{0,25}documents?|documents?.{0,25}(required|checklist|to\s+be\s+(uploaded|submitted)|enclosed)", re.I)


# ------------------------------------------------------------------ result builder

@dataclass
class Builder:
    idx: CollectionIndex
    evidence: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    conflicts: dict[str, dict] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    _keys: dict = field(default_factory=dict)

    def add_evidence(self, chunk: dict, *, start: int | None = None, end: int | None = None, relevance: float,
                     stance: str, why: str) -> str:
        key = (chunk["id"], start)
        if key in self._keys:
            eid = self._keys[key]
            item = next(e for e in self.evidence if e["id"] == eid)
            if stance == "contradicts" or item["stance"] == "context":
                item["stance"] = stance
            item["relevance"] = max(item["relevance"], round(relevance, 3))
            return eid
        doc = self.idx.docs[chunk["document_id"]]
        text = chunk["text"]
        if start is None or end is None:
            start, end = 0, len(text)
        quote = text[start:end].strip()
        eid = f"E{len(self.evidence) + 1}"
        self._keys[key] = eid
        self.evidence.append({
            "id": eid, "chunk_id": chunk["id"], "document_id": doc["id"], "filename": doc["filename"],
            "title": doc["title"], "doc_role": doc["role"], "doc_date": doc["doc_date"], "kind": doc["kind"],
            "page": chunk["page"], "line": chunk["line_start"], "section": chunk["section"], "quote": quote,
            "highlight": {"start": start, "end": end}, "relevance": round(relevance, 3), "stance": stance, "why": why,
            "quality": chunk["quality"], "ocr": bool(doc["ocr_used"]), "flagged": bool(chunk["flags"]),
        })
        return eid

    def fact_evidence(self, fact: dict, relevance: float, stance: str, why: str) -> str:
        return self.add_evidence(fact["chunk"], start=fact["sent_start"], end=fact["sent_end"], relevance=relevance,
                                 stance=stance, why=why)

    def claim(self, text: str, status: str, evidence: list[str], reasoning: str, kind: str = "finding",
              conflict_ids: list[str] | None = None, criterion: str | None = None) -> dict:
        c = {"id": f"C{len(self.claims) + 1}", "text": text, "status": status, "evidence": list(dict.fromkeys(evidence)),
             "reasoning": reasoning, "kind": kind, "conflict_ids": conflict_ids or [], "criterion": criterion,
             "source": "engine"}
        self.claims.append(c)
        return c

    def add_conflict(self, c: dict) -> str:
        self.conflicts[c["id"]] = c
        return c["id"]


# ------------------------------------------------------------------ question analysis

def applicants(idx: CollectionIndex) -> dict[str, dict]:
    """Primary subjects of record documents: casefolded name -> {name, document_ids}."""
    out: dict[str, dict] = {}
    for d in idx.docs.values():
        if d["role"] != "record":
            continue
        for name in d["meta"].get("subjects", []):
            key = name.casefold()
            entry = out.setdefault(key, {"name": name if not name.isupper() else name.title(), "document_ids": set()})
            entry["document_ids"].add(d["id"])
    # every record that mentions the name belongs to that subject's file
    for key, entry in out.items():
        for c in idx.chunks:
            doc = idx.docs[c["document_id"]]
            if doc["role"] == "record" and key in c["text"].casefold():
                entry["document_ids"].add(doc["id"])
    return out


def analyze(idx: CollectionIndex, question: str) -> dict:
    q = question.strip()
    people = applicants(idx)
    qf = q.casefold()
    mentioned = []
    for key, entry in people.items():
        parts = key.split()
        if key in qf:
            mentioned.append(key)
            continue
        for p in parts:
            if len(p) > 2 and re.search(rf"\b{re.escape(p)}\b", qf):
                if sum(1 for k in people if p in k.split()) == 1:
                    mentioned.append(key)
                    break
    mentioned = list(dict.fromkeys(mentioned))
    hints = [t for t, rx in TYPE_HINTS if rx.search(q)]
    if ELIGIBILITY_Q.search(q) and (mentioned or THIS_PERSON.search(q)):
        intent = "eligibility"
    elif hints and (VALUE_Q.search(q) or YESNO_Q.search(q)):
        intent = "value"
    elif YESNO_Q.search(q):
        intent = "yes_no"
    else:
        intent = "open"
    return {"intent": intent, "type_hints": hints, "mentioned": mentioned, "people": people,
            "refers_to_unnamed": bool(THIS_PERSON.search(q))}


# ------------------------------------------------------------------ eligibility

def _is_criterion(f: dict, idx: CollectionIndex) -> bool:
    if f["role"] != "requirement" or f["type"] not in ("money", "percent", "score", "age"):
        return False
    if f["comparator"] not in ("lte", "gte", "range"):
        return False
    if idx.docs[f["document_id"]]["role"] == "record":
        return False
    section = (f.get("chunk") or {}).get("section", "")
    if NOT_ELIG_CONTEXT.search(section) or NOT_ELIG_CONTEXT.search(f["sentence"]):
        return False
    return bool(ELIG_CONTEXT.search(section) or re.search(r"\b(must|shall|eligible|not\s+exceed|at\s+least|minimum)\b", f["sentence"], re.I))


def _deadline(f: dict, idx: CollectionIndex) -> bool:
    return (f["type"] == "date" and f["role"] == "requirement" and f["comparator"] == "lte"
            and idx.docs[f["document_id"]]["role"] != "record"
            and bool(re.search(r"\b(last\s+date|deadline|submission|submit)\b", f["sentence"], re.I)))


def _groups(idx: CollectionIndex, predicate) -> list[list[int]]:
    selected = {i for i, f in enumerate(idx.facts) if predicate(f, idx)}
    groups, seen = [], set()
    for members in cf.clusters(idx):
        g = [i for i in members if i in selected]
        if g:
            groups.append(members)
            seen.update(members)
    for i in sorted(selected - seen):
        groups.append([i])
    return groups


def _age_at(dob: date, ref: date) -> int:
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


def _ref_date(sentence: str) -> date | None:
    m = re.search(r"\bas\s+(?:on|of|at)\s+(.{0,30})", sentence, re.I)
    if m:
        found = find_dates(m.group(1))
        if found:
            return found[0][0]
    return None


def _phrase(comparator: str, display: str, typ: str) -> str:
    if typ == "date":
        return f"on or before {display}" if comparator == "lte" else display
    return {"lte": f"at most {display}", "gte": f"at least {display}", "range": f"between {display}"}.get(comparator, display)


def _match_subject(idx: CollectionIndex, group: list[int], subject_facts: list[int], typ: str) -> list[tuple[int, float]]:
    """Subject facts describing the same attribute as a criterion group, best first."""
    out = []
    for si in subject_facts:
        s = idx.facts[si]
        if typ == "age":
            if s["type"] == "age" or (s["type"] == "date" and re.search(r"birth|dob", s["label"] or "", re.I)):
                out.append((si, 0.95))
            continue
        if typ == "date":
            if s["type"] == "date" and SUBMISSION.search(f"{s['label']} {s['sentence']}"):
                out.append((si, 0.8))
            continue
        if s["type"] != typ:
            continue
        sim = max(float(idx.fact_emb[si] @ idx.fact_emb[g]) for g in group)
        lab = len(set(content_terms(s["label"] or "")) & {t for g in group for t in content_terms(idx.facts[g]["label"] or "")})
        score = sim + 0.08 * min(lab, 2)
        if score >= 0.62:
            out.append((si, round(min(score, 1.0), 3)))
    out.sort(key=lambda x: -x[1])
    return out


def eligibility(b: Builder, subject: dict) -> None:
    idx = b.idx
    name = subject["name"]
    subject_docs = subject["document_ids"]
    subject_facts = [i for i, f in enumerate(idx.facts) if f["document_id"] in subject_docs and f["role"] == "subject"]

    for group in _groups(idx, _is_criterion) + _groups(idx, _deadline):
        res = cf.resolve_cluster(idx, group)
        active = res["active"]
        if not active:
            continue
        typ = active[0]["type"]
        label = cf._cluster_label(res["facts"])
        matches = _match_subject(idx, group, subject_facts, typ)
        conflict = next((c for c in cf.detect(idx) if set(c["fact_ids"]) & {f["id"] for f in res["facts"]}), None)
        if conflict:
            b.add_conflict(conflict)
        req_desc = " / ".join(dict.fromkeys(_phrase(f["comparator"], f["display"], typ) for f in active))

        if not matches:
            if typ == "date":
                continue  # a deadline is only checked when the record states a submission date
            eids = [b.fact_evidence(f, 0.9, "context", f"States the {label} requirement ({_phrase(f['comparator'], f['display'], typ)}).")
                    for f in active]
            what = "date of birth or age" if typ == "age" else label
            b.missing.append(f"{name}'s {what}")
            b.claim(f"{label.capitalize()} requirement ({req_desc}) could not be verified: no {what} found in {name}'s documents.",
                    INSUFFICIENT, eids, f"None of {name}'s {len(subject_docs)} document(s) state a {what}.",
                    kind="criterion", criterion=label)
            continue

        # Subject values (corroborating or inconsistent across the subject's documents)
        best_i = matches[0][0]
        best = idx.facts[best_i]
        same_attr = [(i, s) for i, s in matches if idx.facts[i]["type"] == best["type"]]
        values = {}
        for i, s in same_attr:
            values.setdefault(idx.facts[i]["value"], []).append((i, s))
        subject_value = best["value"]
        subject_display = best["display"]
        evaluated_value = subject_value
        if typ == "age" and best["type"] == "date":
            ref = _ref_date(active[0]["sentence"]) or date.today()
            age = _age_at(date.fromisoformat(best["value"]), ref)
            evaluated_value = age
            subject_display = f"{age} years (born {best['display']}, as on {ref.day} {ref.strftime('%B %Y')})"
        elif typ == "age":
            evaluated_value = best["value"]

        subj_eids = []
        for i, s in values.get(subject_value, []):
            f = idx.facts[i]
            subj_eids.append(b.fact_evidence(f, s, "supports",
                                             f"Records {name}'s {f['label']} ({f['display']})"
                                             + (" — OCR-extracted from a scanned document." if idx.docs[f['document_id']]['ocr_used'] else ".")))
        if len(values) > 1:
            others = [idx.facts[i] for v, lst in values.items() if v != subject_value for i, _ in lst]
            o_eids = [b.fact_evidence(f, 0.8, "contradicts", f"States a different {label} for {name} ({f['display']}).") for f in others]
            b.claim(f"{name}'s records disagree on {label}: " + " vs ".join(dict.fromkeys([best['display']] + [f['display'] for f in others])) + ".",
                    UNCERTAIN, subj_eids + o_eids, "The subject's own documents are inconsistent, so the criterion cannot be evaluated reliably.",
                    kind="criterion", criterion=label)
            continue

        outcomes = []
        for f in active:
            ok = satisfies(evaluated_value if typ != "date" else best["value"], f["comparator"], f["value"], f.get("value_hi"))
            outcomes.append((f, ok))
        sat = [f for f, ok in outcomes if ok]
        unsat = [f for f, ok in outcomes if ok is False]
        req_eids = []
        for f, ok in outcomes:
            stance = "supports" if ok else "contradicts"
            req_eids.append(b.fact_evidence(f, 0.92, stance,
                                            f"Sets the {label} rule: {_phrase(f['comparator'], f['display'], typ)}"
                                            f" — {name}'s {subject_display} {'meets' if ok else 'fails'} it."))
        for f in res["facts"]:
            if f["id"] in res["status"]:
                b.fact_evidence(f, 0.5, "context", f"Earlier value ({f['display']}), not applied: {res['status'][f['id']][1]}")
        dates_note = ""
        if any(f["id"] in res["status"] for f in res["facts"]):
            dates_note = " Superseded or amended values were excluded, citing the document that replaces them."

        conflict_ids = [conflict["id"]] if conflict and conflict["status"] == "UNRESOLVED" else []
        subj_label = "Application date" if typ == "date" else label.capitalize()
        if sat and not unsat:
            if len(active) > 1:
                text = f"{subj_label} {subject_display} satisfies every stated rule ({req_desc})."
                reasoning = (f"The documents disagree on the {label} rule, but {name}'s value satisfies all of them, "
                             "so the conflict does not change the outcome." + dates_note)
                conflict_ids = []  # not material
            else:
                text = f"{subj_label} {subject_display} meets the requirement ({req_desc})."
                reasoning = f"Compared {name}'s {label} against the rule in {idx.docs[active[0]['document_id']]['filename']}." + dates_note
            status = SUPPORTED
        elif unsat and not sat:
            text = f"{subj_label} {subject_display} does not meet the requirement ({req_desc})."
            reasoning = f"{name}'s {label} fails the rule stated in " + ", ".join(idx.docs[f['document_id']]['filename'] for f in unsat) + "." + dates_note
            status = CONTRADICTED
        else:
            text = (f"{subj_label} {subject_display} satisfies "
                    + ", ".join(f"{_phrase(f['comparator'], f['display'], typ)} ({idx.docs[f['document_id']]['filename']})" for f in sat)
                    + " but not " + ", ".join(f"{_phrase(f['comparator'], f['display'], typ)} ({idx.docs[f['document_id']]['filename']})" for f in unsat) + ".")
            reasoning = ("The outcome depends on which document's rule applies, and no document resolves that. "
                         "VERITAS does not pick one.")
            status = UNCERTAIN
        b.claim(text, status, req_eids + subj_eids, reasoning, kind="criterion", conflict_ids=conflict_ids, criterion=label)

    _documents_checklist(b, subject)
    _review_conditions(b, subject)


def _documents_checklist(b: Builder, subject: dict) -> None:
    idx = b.idx
    name = subject["name"]
    lists = [c for c in idx.chunks if idx.docs[c["document_id"]]["role"] != "record"
             and DOC_LIST_SECTION.search(c["section"]) and "•" in c["text"]]
    if not lists:
        return
    chunk = lists[0]
    items = [ln.lstrip("• ").strip() for ln in chunk["text"].split("\n") if ln.strip().startswith("•")]
    subj_chunks = [c for c in idx.chunks if c["document_id"] in subject["document_ids"]]
    found, missing, where = [], [], {}
    for item in items:
        key = re.split(r"\b(issued|from|of\s+an?|of\s+the|by|in|for)\b", item, maxsplit=1)[0].strip(" ,;")
        terms = set(content_terms(key))
        hit = None
        for c in subj_chunks:
            if terms and terms <= set(content_terms(c["text"])):
                hit = c
                break
        if hit is None:  # a document of that kind in the collection, about this subject
            for d_id in subject["document_ids"]:
                d = idx.docs[d_id]
                if terms and terms <= set(content_terms(f"{d['title']} {d['filename']}")):
                    hit = next(c for c in idx.chunks if c["document_id"] == d_id)
                    break
        (found if hit else missing).append(key)
        if hit:
            where[hit["id"]] = hit
    req_eid = b.add_evidence(chunk, relevance=0.9, stance="supports" if not missing else "contradicts",
                             why=f"Lists the {len(items)} documents every application must include.")
    subj_eids = [b.add_evidence(c, relevance=0.85, stance="supports",
                                why=f"Shows which required documents {name} submitted.") for c in where.values()]
    if not missing:
        b.claim(f"All {len(items)} required documents are present in {name}'s file.", SUPPORTED, [req_eid] + subj_eids,
                "Matched each item of the required-documents list against the documents enclosed by the applicant.",
                kind="criterion", criterion="required documents")
    else:
        b.missing.extend(f"{name}'s {m.lower()}" for m in missing)
        status = PARTIAL if found else INSUFFICIENT
        b.claim(f"{len(found)} of {len(items)} required documents found; missing: {', '.join(missing)}.", status,
                [req_eid] + subj_eids,
                "The requirements state that incomplete applications will be rejected, so missing items matter."
                if re.search(r"incomplete", " ".join(c["text"] for c in idx.chunks if c["document_id"] == chunk["document_id"]), re.I)
                else "Each required item was searched for in the applicant's documents.",
                kind="criterion", criterion="required documents")


def _review_conditions(b: Builder, subject: dict) -> None:
    """Non-numeric eligibility conditions: shown with the closest record, never auto-decided."""
    idx = b.idx
    sup = cf.supersession_map(idx)
    lines = [(c, ln.strip()) for c in idx.chunks if c["document_id"] in subject["document_ids"]
             for ln in c["text"].split("\n") if len(ln.strip()) > 8]
    line_vecs = embedder.embed([ln for _, ln in lines]) if lines else None
    seen = set()
    for i, f in enumerate(idx.facts):
        if f["type"] != "assertion" or f["document_id"] in sup or idx.docs[f["document_id"]]["role"] == "record":
            continue
        if not re.search(r"\beligib", f["sentence"], re.I) or f["sentence"] in seen:
            continue
        seen.add(f["sentence"])
        related = None
        if lines:
            sims = line_vecs @ idx.fact_emb[i]
            cond_terms = set(content_terms(f["sentence"]))
            scores = [float(sims[k]) + 0.06 * len(cond_terms & set(content_terms(ln))) for k, (_, ln) in enumerate(lines)]
            k = int(np.argmax(scores))
            if scores[k] >= 0.6:
                c, ln = lines[k]
                related = {"chunk_id": c["id"], "document_id": c["document_id"], "filename": idx.docs[c["document_id"]]["filename"],
                           "quote": ln}
        conflict = next((c for c in cf.detect(idx) if f["id"] in c["fact_ids"] and c["status"] == "UNRESOLVED"), None)
        b.review.append({"condition": f["sentence"], "document_id": f["document_id"],
                         "filename": idx.docs[f["document_id"]]["filename"], "chunk_id": f["chunk_id"],
                         "page": (f.get("chunk") or {}).get("page"), "related_record": related,
                         "conflict_id": conflict["id"] if conflict else None})
        if conflict:
            b.add_conflict(conflict)


def _best_sentence(text: str, target: str) -> str:
    tt = set(content_terms(target))
    best, score = text[:240], -1
    for s in split_sentences(text.replace("\n", ". ")):
        sc = len(tt & set(content_terms(s)))
        if sc > score:
            best, score = s, sc
    return best


# ------------------------------------------------------------------ value questions

def value_answer(b: Builder, question: str, hints: list[str], hits: list[Hit]) -> bool:
    idx = b.idx
    if not idx.facts:
        return False
    qv = embedder.embed_query(question)
    hit_rel = {h.chunk["id"]: h.relevance for h in hits}
    types = set(hints) & {"money", "percent", "score", "age", "date"} or {"money", "percent", "score", "age", "date"}
    best, best_score = None, 0.0
    sims = idx.fact_emb @ qv
    for i, f in enumerate(idx.facts):
        if f["type"] not in types or f["role"] not in ("requirement", "statement"):
            continue
        rel = hit_rel.get(f["chunk_id"], 0.0)
        score = 0.55 * float(sims[i]) + 0.45 * rel
        if score > best_score:
            best, best_score = i, score
    if best is None or best_score < 0.42 or (hit_rel.get(idx.facts[best]["chunk_id"], 0) < 0.3 and float(sims[best]) < 0.7):
        return False
    group = cf.cluster_of(idx, best) or [best]
    res = cf.resolve_cluster(idx, group)
    active = res["active"] or res["facts"]
    label = cf._cluster_label(res["facts"])
    typ = active[0]["type"]
    values = list(dict.fromkeys(f["display"] for f in active))
    conflict = next((c for c in cf.detect(idx) if set(c["fact_ids"]) & {f["id"] for f in res["facts"]}), None)
    if conflict:
        b.add_conflict(conflict)

    for f in res["facts"]:
        if f["id"] in res["status"]:
            b.fact_evidence(f, 0.5, "context", f"Earlier value ({f['display']}), not applied: {res['status'][f['id']][1]}")
    if len(values) == 1:
        eids = [b.fact_evidence(f, max(0.75, hit_rel.get(f["chunk_id"], 0.75)), "supports",
                                f"States the {label}: {_phrase(f['comparator'], f['display'], typ)}.") for f in active]
        n_docs = len({f["document_id"] for f in active})
        b.claim(f"{label.capitalize()}: {_phrase(active[0]['comparator'], values[0], typ)}.", SUPPORTED, eids,
                f"Stated in {n_docs} document(s)" + (" that agree with each other." if n_docs > 1 else ".")
                + (" Older or amended values were excluded with the reason quoted." if res["status"] else ""),
                kind="value", criterion=label)
    else:
        for v in values:
            fs = [f for f in active if f["display"] == v]
            others = [f for f in active if f["display"] != v]
            eids = [b.fact_evidence(f, max(0.75, hit_rel.get(f["chunk_id"], 0.75)), "supports",
                                    f"States the {label} as {_phrase(f['comparator'], v, typ)}.") for f in fs]
            claim = b.claim(f"{', '.join(dict.fromkeys(idx.docs[f['document_id']]['filename'] for f in fs))}: {label} "
                    f"{_phrase(fs[0]['comparator'], v, typ)}.", UNCERTAIN, eids,
                    "Contradicted by " + ", ".join(f"{idx.docs[f['document_id']]['filename']} ({f['display']})" for f in others)
                    + "; no document states which one prevails.", kind="value",
                    conflict_ids=[conflict["id"]] if conflict else [], criterion=label)
            claim["value"] = v
    return True


# ------------------------------------------------------------------ passage questions

def assertion_answer(b: Builder, question: str, hits: list[Hit]) -> bool:
    """Yes/no questions answered by polarity-bearing statements (eligible / not eligible ...)."""
    idx = b.idx
    qv = embedder.embed_query(question)
    hit_rel = {h.chunk["id"]: h.relevance for h in hits}
    sup = cf.supersession_map(idx)
    q_terms = set(question_terms(question))
    cands = []
    for i, f in enumerate(idx.facts):
        if f["type"] != "assertion" or f["document_id"] in sup:
            continue
        rel = hit_rel.get(f["chunk_id"], 0.0)
        overlap = len(q_terms & set(content_terms(f["sentence"]))) / max(1, len(q_terms))
        score = 0.4 * float(idx.fact_emb[i] @ qv) + 0.35 * rel + 0.25 * overlap
        if rel >= 0.45 and overlap >= 0.5:
            cands.append((score, i))
    if not cands:
        return False
    cands.sort(reverse=True)
    top = cands[0][0]
    chosen = [idx.facts[i] for s, i in cands if s >= top - 0.08][:4]
    polarities = {f["value"] for f in chosen}
    conflict = next((c for c in cf.detect(idx) if set(c["fact_ids"]) & {f["id"] for f in chosen}), None)
    if conflict:
        b.add_conflict(conflict)
    if len(polarities) == 1:
        yes = chosen[0]["value"] > 0
        eids = [b.fact_evidence(f, hit_rel.get(f["chunk_id"], 0.6), "supports", "States the rule that answers the question.") for f in chosen]
        b.claim(("Yes — " if yes else "No — ") + chosen[0]["sentence"], SUPPORTED, eids,
                f"{len(chosen)} statement(s) with the same polarity were found; none contradicts them.", kind="statement")
    else:
        for f in chosen:
            eid = b.fact_evidence(f, hit_rel.get(f["chunk_id"], 0.6), "supports" if f["value"] > 0 else "contradicts",
                                  "Affirms the point." if f["value"] > 0 else "Denies the point.")
            b.claim(f"{idx.docs[f['document_id']]['filename']}: {f['sentence']}", UNCERTAIN, [eid],
                    "Another document states the opposite; neither says it overrides the other.", kind="statement",
                    conflict_ids=[conflict["id"]] if conflict else [])
    return True


def passage_answer(b: Builder, question: str, hits: list[Hit]) -> None:
    q_terms = set(question_terms(question))
    cands = []
    for h in hits[:5]:
        prev = ""
        for s in split_sentences(h.chunk["text"].replace("\n", " \n ")):
            s = s.strip()
            answer = re.sub(r"^\s*A\s*:\s*", "", s)
            if s.endswith("?"):
                prev = re.sub(r"^\s*Q\s*:\s*", "", s)  # FAQ: keep the question as context for its answer
                continue
            if len(answer) >= 25:
                cands.append((h, answer, f"{prev} {answer}".strip() if prev else answer))
            prev = ""
    # Sentence-level cross-encoder relevance; lexical overlap only as a fallback.
    rr = embedder.rerank(question, [ctx for _, _, ctx in cands]) if cands else None
    scored = []
    for k, (h, s, _) in enumerate(cands):
        ov = len(q_terms & set(content_terms(s))) / max(1, len(q_terms))
        sent = rr[k] if rr is not None else ov
        scored.append((0.65 * sent + 0.35 * h.relevance, h, s))
    scored.sort(key=lambda x: -x[0])
    eids, used = [], set()
    for score, h, s in scored[:3]:
        start = h.chunk["text"].find(s)
        if (h.chunk["id"], s) in used or start < 0:
            continue
        used.add((h.chunk["id"], s))
        eids.append(b.add_evidence(h.chunk, start=start, end=start + len(s), relevance=h.relevance, stance="supports",
                                   why=f"One of the most relevant passages for the question (relevance {h.relevance:.2f})."))
    if eids:
        best = next(e for e in b.evidence if e["id"] == eids[0])
        b.claim(best["quote"], PARTIAL, eids,
                "Extractive answer: the closest passages are quoted verbatim. The engine did not infer beyond them.",
                kind="passage")


def concept_covered(idx: CollectionIndex, missing: list[str], hits: list[Hit]) -> bool:
    """A question word absent from every document can still be covered by a synonym in the
    evidence ("pupil" ~ "student"). Without that, the question asks about something the
    documents never mention, and a confident answer would be a hallucination."""
    if not hits:
        return False
    vecs = embedder.embed([" ".join(missing)])
    texts = [s for h in hits[:5] for s in split_sentences(h.chunk["text"].replace("\n", ". "))]
    if not texts:
        return False
    sims = embedder.embed(texts) @ vecs[0]
    return float(np.max(sims)) >= 0.78


def insufficient(b: Builder, question: str, hits: list[Hit], missing: list[str]) -> None:
    for h in hits[:2]:
        b.add_evidence(h.chunk, relevance=h.relevance, stance="context",
                       why=f"Closest passage found (relevance {h.relevance:.2f}); it does not answer the question.")
    n = len(b.idx.docs)
    if missing:
        what = ", ".join(f"“{m}”" for m in missing)
        b.missing.append(f"any mention of {what}")
        text = f"None of the {n} documents mention {what}."
    else:
        text = f"No passage in the {n} documents answers this question with sufficient relevance."
    b.claim(text, INSUFFICIENT, [e["id"] for e in b.evidence], "VERITAS does not answer beyond the evidence.", kind="gap")


# ------------------------------------------------------------------ verdict

def verdict(intent: str, claims: list[dict], subject: str | None) -> dict:
    statuses = [c["status"] for c in claims]
    if not claims or all(s == INSUFFICIENT for s in statuses):
        return {"status": INSUFFICIENT, "headline": "Insufficient evidence"}
    if intent == "eligibility":
        crit = [c for c in claims if c["kind"] == "criterion"]
        st = [c["status"] for c in crit]
        n_ok = st.count(SUPPORTED)
        if CONTRADICTED in st:
            return {"status": CONTRADICTED, "headline": "Not eligible",
                    "summary": f"{st.count(CONTRADICTED)} criterion(s) are not met by {subject}'s documents."}
        if UNCERTAIN in st:
            return {"status": UNCERTAIN, "headline": "Undetermined — the rules conflict",
                    "summary": f"{n_ok} of {len(crit)} criteria are met, but at least one depends on conflicting documents."}
        if st and all(s == SUPPORTED for s in st):
            return {"status": SUPPORTED, "headline": "Eligible",
                    "summary": f"All {len(crit)} evaluated criteria are met, each backed by cited evidence."}
        if n_ok:
            return {"status": PARTIAL, "headline": "Likely eligible",
                    "summary": f"{n_ok} of {len(crit)} criteria are met; the rest could not be verified from the documents."}
        return {"status": INSUFFICIENT, "headline": "Insufficient evidence"}
    if UNCERTAIN in statuses:
        vals = [c["value"] for c in claims if c["status"] == UNCERTAIN and c.get("value")]
        return {"status": UNCERTAIN, "headline": "Conflicting evidence" + (f": {' vs '.join(vals)}" if vals else ""),
                "summary": "The documents disagree and none of them states which one prevails."}
    if CONTRADICTED in statuses and SUPPORTED not in statuses:
        return {"status": CONTRADICTED, "headline": "Contradicted by the evidence"}
    if all(s == SUPPORTED for s in statuses):
        return {"status": SUPPORTED, "headline": claims[0]["text"] if len(claims) == 1 else "Supported by the evidence"}
    if claims[0]["kind"] == "passage":
        return {"status": PARTIAL, "headline": "Relevant evidence found",
                "summary": "The closest passages are quoted verbatim; the extractive engine does not infer beyond them."}
    return {"status": PARTIAL, "headline": "Partially supported"}


def recommendation(status: str, b: Builder, subject: str | None) -> str:
    unresolved = [c for c in b.conflicts.values() if c["status"] == "UNRESOLVED"]
    material = [c for c in b.claims if c["conflict_ids"] and c["status"] == UNCERTAIN]
    if material:
        c = b.conflicts.get(material[0]["conflict_ids"][0]) or (unresolved[0] if unresolved else None)
        docs = " and ".join(dict.fromkeys(s["filename"] for s in c["sources"] if s["status"] == "active")) if c else "the sources"
        return f"Confirm which rule governs ({docs}) before making a final decision. VERITAS will not choose between them."
    if any("which applicant" in m for m in b.missing):
        return "Ask again naming the applicant, for example “Is Priya Sharma eligible?”."
    if status == INSUFFICIENT:
        return "Add documents that cover this question, or rephrase it using terms the documents use."
    if b.missing:
        return f"Obtain {', '.join(dict.fromkeys(b.missing))} before a final decision."
    if unresolved:
        return "The answer holds under every conflicting source, but review the open conflicts in Conflict Radar."
    if status == SUPPORTED:
        return "No further verification needed for the evaluated points; every claim cites its source."
    return "Review the cited passages; the extractive engine quotes evidence but does not infer beyond it."


# ------------------------------------------------------------------ entry point

def investigate(idx: CollectionIndex, question: str, llm=None) -> dict:
    t_all = time.perf_counter()
    steps: list[dict] = []

    def step(name: str, detail: str, t0: float):
        steps.append({"step": name, "detail": detail, "ms": int((time.perf_counter() - t0) * 1000)})

    b = Builder(idx)
    t = time.perf_counter()
    a = analyze(idx, question)
    subject = None
    people = a["people"]
    if a["intent"] == "eligibility":
        if len(a["mentioned"]) == 1:
            subject = people[a["mentioned"][0]]
        elif not a["mentioned"] and len(people) == 1:
            subject = next(iter(people.values()))
    step("analyze", f"Intent: {a['intent']}" + (f"; subject: {subject['name']}" if subject else "")
         + (f"; value types: {', '.join(a['type_hints'])}" if a["type_hints"] else ""), t)

    t = time.perf_counter()
    hits = retrieve(idx, question, k=8)
    step("retrieve", f"{len(hits)} passages from {len({h.chunk['document_id'] for h in hits})} documents "
                     f"(hybrid dense + BM25{', cross-encoder reranked' if hits and hits[0].rerank is not None else ''})", t)

    t = time.perf_counter()
    all_conflicts = cf.detect(idx)
    step("conflicts", f"{sum(1 for c in all_conflicts if c['status'] == 'UNRESOLVED')} unresolved and "
                      f"{sum(1 for c in all_conflicts if c['status'] == 'RESOLVED')} resolved conflicts in the collection", t)

    t = time.perf_counter()
    missing = missing_terms(idx, question)
    top_rel = hits[0].relevance if hits else 0.0
    note = None
    if not idx.docs:
        b.claim("The investigation has no indexed documents.", INSUFFICIENT, [], "Upload documents first.", kind="gap")
    elif a["intent"] == "eligibility" and subject is None:
        names = [p["name"] for p in people.values()]
        if names:
            note = f"Several people have records in this investigation ({', '.join(names)}). Name the person to evaluate."
            b.missing.append("which applicant the question refers to")
        else:
            note = "No applicant records (forms, certificates) were found to evaluate eligibility against."
            b.missing.append("an applicant record")
        b.claim(note, INSUFFICIENT, [], "Eligibility needs a specific subject with their own records.", kind="gap")
    elif a["intent"] == "eligibility":
        eligibility(b, subject)
        if not b.claims:
            insufficient(b, question, hits, [])
    elif missing and not concept_covered(idx, missing, hits):
        insufficient(b, question, hits, missing)
    elif not hits or top_rel < 0.3:
        insufficient(b, question, hits, [])
    else:
        handled = False
        if a["intent"] in ("value",) or a["type_hints"]:
            handled = value_answer(b, question, a["type_hints"], hits)
        if not handled and a["intent"] in ("yes_no", "open", "value"):
            handled = assertion_answer(b, question, hits)
        if not handled:
            passage_answer(b, question, hits)
    step("reason", f"{len(b.claims)} claims, {len(b.evidence)} evidence items, {len(b.conflicts)} relevant conflicts", t)

    v = verdict(a["intent"], b.claims, subject["name"] if subject else None)
    engine = "extractive"
    llm_note = None
    if llm is not None and llm.available() and v["status"] != INSUFFICIENT and b.evidence:
        t = time.perf_counter()
        try:
            merged = llm.synthesize(question, b, v, idx)
            if merged:
                v = merged["verdict"]
                engine = "llm-verified"
                llm_note = merged.get("note")
            else:
                llm_note = "The LLM returned no usable answer (declined or truncated), so the extractive engine answered."
            step("synthesize", f"LLM synthesis ({llm.model}); {merged.get('verified', 0) if merged else 0} LLM claims "
                               f"passed verification, {merged.get('rejected', 0) if merged else 0} rejected", t)
        except Exception as e:  # never fail the investigation because the LLM failed
            log.warning("LLM synthesis failed: %s", e)
            llm_note = "The LLM was unavailable, so the extractive engine answered on its own."
            step("synthesize", "LLM unavailable — extractive answer used", t)

    t = time.perf_counter()
    conflicts = list(b.conflicts.values())
    conf = confidence.compute(v["status"], b.claims, b.evidence, conflicts)
    step("confidence", f"{int(conf['score'] * 100)}% ({conf['level'].lower()})", t)

    flagged_docs = {e["document_id"] for e in b.evidence} | (subject["document_ids"] if subject else set())
    security = [{"document_id": f["document_id"], "filename": idx.docs[f["document_id"]]["filename"], "page": f["page"],
                 "kind": f["kind"], "severity": f["severity"], "text": f["text"], "reasons": f["reasons"],
                 "action": "Excluded from evidence and facts; redacted from any AI prompt."}
                for f in idx.flags if f["document_id"] in flagged_docs and f["document_id"] in idx.docs]

    answer_text = v.get("answer") or _answer_text(v, b, subject)
    result = {
        "question": question, "intent": a["intent"], "engine": engine,
        "subject": {"name": subject["name"], "document_ids": sorted(subject["document_ids"])} if subject else None,
        "verdict": {"status": v["status"], "headline": v["headline"], "summary": v.get("summary"), "answer": answer_text},
        "confidence": conf, "claims": b.claims, "evidence": b.evidence, "conflicts": conflicts,
        "missing": list(dict.fromkeys(b.missing)), "review": b.review,
        "recommendation": v.get("recommendation") or recommendation(v["status"], b, subject["name"] if subject else None),
        "security": security, "notes": [n for n in (note, llm_note) if n],
        "stats": {"documents": len(idx.docs), "chunks": len(idx.chunks), "facts": len(idx.facts),
                  "passages_retrieved": len(hits), "top_relevance": top_rel},
        "timeline": steps,
    }
    result["graph"] = graph.build(result, idx)
    result["timeline"].append({"step": "done", "detail": "Answer assembled", "ms": int((time.perf_counter() - t_all) * 1000)})
    return result


def _answer_text(v: dict, b: Builder, subject: dict | None) -> str:
    if v["status"] == INSUFFICIENT:
        gap = next((c["text"] for c in b.claims if c["status"] == INSUFFICIENT), "")
        return f"Insufficient evidence to determine this. {gap}".strip()
    parts = [v.get("summary") or ""]
    for c in b.claims[:6]:
        mark = {SUPPORTED: "✓", CONTRADICTED: "✗", UNCERTAIN: "⚠", PARTIAL: "◐", INSUFFICIENT: "?"}[c["status"]]
        parts.append(f"{mark} {c['text']}")
    return "\n".join(p for p in parts if p)
