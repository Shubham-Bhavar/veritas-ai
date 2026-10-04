"""Explainable confidence: a weighted score over named evidence signals, never a model's self-report."""
from __future__ import annotations

WEIGHTS = {"relevance": 0.25, "corroboration": 0.25, "agreement": 0.20, "completeness": 0.20, "extraction": 0.10}
CAPS = {"INSUFFICIENT_EVIDENCE": 0.25, "UNCERTAIN": 0.55, "PARTIALLY_SUPPORTED": 0.85}


def compute(status: str, claims: list[dict], evidence: list[dict], conflicts: list[dict]) -> dict:
    ev_by_id = {e["id"]: e for e in evidence}
    used = [e for e in evidence if e["stance"] in ("supports", "contradicts")] or evidence

    relevance = sum(e["relevance"] for e in used) / len(used) if used else 0.0

    decided = [c for c in claims if c["status"] in ("SUPPORTED", "CONTRADICTED", "PARTIALLY_SUPPORTED")]
    corr_scores, corroborated = [], 0
    for c in decided:
        docs = {ev_by_id[e]["document_id"] for e in c["evidence"] if e in ev_by_id}
        n = len(docs)
        corr_scores.append(0.55 if n <= 1 else 0.8 if n == 2 else 1.0)
        if n >= 2:
            corroborated += 1
    corroboration = sum(corr_scores) / len(corr_scores) if corr_scores else 0.3

    material = [c for c in claims if c.get("conflict_ids") and c["status"] == "UNCERTAIN"]
    unresolved = [c for c in conflicts if c["status"] == "UNRESOLVED"]
    resolved = [c for c in conflicts if c["status"] == "RESOLVED"]
    if material:
        agreement = 0.3
    elif unresolved:
        agreement = 0.75
    elif resolved:
        agreement = 0.92
    else:
        agreement = 1.0

    with_evidence = [c for c in claims if c["status"] != "INSUFFICIENT_EVIDENCE" and c["evidence"]]
    completeness = len(with_evidence) / len(claims) if claims else 0.0

    qualities = [e["quality"] for e in used if e.get("quality") is not None]
    extraction = sum(qualities) / len(qualities) if qualities else 1.0

    signals = {"relevance": relevance, "corroboration": corroboration, "agreement": agreement,
               "completeness": completeness, "extraction": extraction}
    score = sum(WEIGHTS[k] * v for k, v in signals.items())
    capped_by = None
    if status in CAPS and score > CAPS[status]:
        score, capped_by = CAPS[status], status
    score = round(max(0.0, min(1.0, score)), 3)
    level = "HIGH" if score >= 0.8 else "MODERATE" if score >= 0.55 else "LOW"

    reasons = []
    n_docs = len({e["document_id"] for e in used})
    n_pass = len(used)
    if level == "HIGH":
        reasons.append(f"High confidence: {n_pass} passages from {n_docs} independent documents support the conclusion"
                       + (" and no unresolved conflict affects it." if not material else "."))
    elif status == "INSUFFICIENT_EVIDENCE":
        reasons.append("Low confidence: the documents do not contain enough evidence to answer.")
    elif material:
        reasons.append(f"Confidence is limited because {len(material)} conclusion(s) depend on documents that disagree.")
    elif level == "LOW":
        reasons.append(f"Low confidence: only {n_pass} weakly relevant passage(s) support the answer.")
    else:
        reasons.append(f"Moderate confidence: supported by {n_pass} passages from {n_docs} documents, with gaps noted below.")

    details = [
        _detail("relevance", relevance, f"Average relevance of cited evidence is {relevance:.2f}."),
        _detail("corroboration", corroboration,
                f"{corroborated} of {len(decided)} decided claim(s) are corroborated by two or more documents."
                if decided else "No claim could be decided from the evidence."),
        _detail("agreement", agreement,
                f"{len(material)} conclusion(s) depend on an unresolved conflict." if material else
                f"{len(unresolved)} unresolved conflict(s) in the cited sources do not change the outcome." if unresolved else
                f"{len(resolved)} conflict(s) were resolved by explicit supersession or amendment." if resolved else
                "The cited sources agree."),
        _detail("completeness", completeness,
                f"{len(with_evidence)} of {len(claims)} claim(s) have supporting evidence." if claims else "No claims."),
        _detail("extraction", extraction,
                "Includes OCR-extracted text; extraction quality {:.2f}.".format(extraction) if extraction < 0.98
                else "All evidence comes from native digital text."),
    ]
    if capped_by:
        reasons.append(f"Capped at {int(CAPS[capped_by] * 100)}% because the verdict is {capped_by.replace('_', ' ').lower()}.")
    return {"score": score, "level": level, "signals": details, "explanation": reasons, "weights": WEIGHTS}


def _detail(name: str, value: float, text: str) -> dict:
    return {"name": name, "value": round(value, 3), "weight": WEIGHTS[name], "text": text}
