"""Document-level metadata: title, date, issuer, role, people named, and amendment statements.

Dates and supersession statements matter: the conflict engine only resolves a disagreement
between documents when one of them *says* it replaces or amends the other.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.ingest.extract import Extracted
from app.ingest.text_utils import split_sentences

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON + r"[,.]?\s+(\d{4})\b", re.I),       # 1 April 2026
    re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I),                     # April 1, 2026
    re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b"),                                             # 01/04/2026 (D/M/Y)
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),                                                          # 2026-04-01
]

TITLE_WORDS = re.compile(r"\b(guidelines?|rules?|circular|notice|notification|policy|application|form|certificate|"
                         r"statement|requirements?|faq|frequently|agreement|contract|report|order|memorandum|"
                         r"scheme|regulations?|handbook|manual|invoice|letter)\b", re.I)
AUTHORITY = re.compile(r"\b(ministry|department|government|directorate|office|cell|board|council|authority|"
                       r"commission|university|tehsildar|collector|bureau|agency)\b", re.I)
SUPERSEDE = re.compile(r"\b(supersede[sd]?|replaces?|replaced|in\s+supersession\s+of|stands?\s+withdrawn|is\s+hereby\s+withdrawn|"
                       r"no\s+longer\s+(?:valid|applicable|in\s+force))\b", re.I)
AMEND = re.compile(r"\b(in\s+(?:partial\s+)?modification\s+of|hereby\s+(?:amended|extended|revised|modified|substituted)|"
                   r"stands?\s+(?:amended|extended|revised|modified)|is\s+(?:extended|revised|amended)\s+to|"
                   r"has\s+been\s+(?:extended|revised|amended)|amendment\s+to)\b", re.I)
REF_ID = re.compile(r"\b(?:ref(?:erence)?\.?\s*no\.?|circular\s+no\.?|order\s+no\.?|notification\s+no\.?|letter\s+no\.?|"
                    r"certificate\s+no\.?|application\s+no\.?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-.]{3,})", re.I)
KV_LINE = re.compile(r"^([A-Z][A-Za-z ()/.&'-]{1,48}?)(?:\s*:|\s+[-–]\s)\s*(\S.{0,200})$")
NAME_KEYS = re.compile(r"^(?:full\s+)?name(?:\s+of\s+(?:the\s+)?(?:applicant|student|candidate|employee|beneficiary|claimant))?$|"
                       r"^(?:applicant|student|candidate|employee|beneficiary|claimant)(?:'s)?\s+name$|^applicant$", re.I)
RELATION_NAME = re.compile(r"\b(?:son|daughter|ward|father|mother|wife|husband|guardian)\s+of\s+(?:shri|smt\.?|mr\.?|ms\.?|mrs\.?|kumari|kum\.?)?\s*"
                           r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
CERTIFY_NAME = re.compile(r"\bcertif(?:y|ied)\s+that\s+(?:shri|smt\.?|mr\.?|ms\.?|mrs\.?|kumari|kum\.?)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
RECORD_HINT = re.compile(r"\b(this\s+is\s+to\s+certify|i\s+hereby\s+declare|statement\s+of\s+purpose|my\s+name\s+is|"
                         r"application\s+form|applicant\s+details|certificate\s+no)\b", re.I)
MODAL = re.compile(r"\b(shall|must|eligible|ineligible|required|mandatory|not\s+exceed|minimum|maximum|at\s+least|"
                   r"should|entitled|applicable|prohibited)\b", re.I)


@dataclass
class DocMeta:
    title: str
    doc_date: str | None = None          # ISO date
    authority: str | None = None
    role: str = "reference"              # policy | record | reference
    references: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)     # everyone named
    subjects: list[str] = field(default_factory=list)   # who the record is about ("Applicant Name: ...")
    amendments: list[dict] = field(default_factory=list)  # {kind, sentence}
    years: list[int] = field(default_factory=list)


def parse_date(text: str) -> date | None:
    found = find_dates(text)
    return found[0][0] if found else None


def find_dates(text: str) -> list[tuple[date, int, int]]:
    """All dates in text as (date, start, end), in order of appearance."""
    out = []
    for i, pat in enumerate(DATE_PATTERNS):
        for m in pat.finditer(text):
            try:
                if i == 0:
                    d = date(int(m.group(3)), MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
                elif i == 1:
                    d = date(int(m.group(3)), MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
                elif i == 2:
                    d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                else:
                    d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except (ValueError, KeyError):
                continue
            if 1900 <= d.year <= 2100:
                out.append((d, m.start(), m.end()))
    out.sort(key=lambda x: x[1])
    # drop overlaps (a D/M/Y inside a longer match)
    dedup, last_end = [], -1
    for d, s, e in out:
        if s >= last_end:
            dedup.append((d, s, e))
            last_end = e
    return dedup


def extract_meta(doc: Extracted, filename: str) -> DocMeta:
    blocks = [b for b in doc.blocks if b.kind != "hidden"]
    full = "\n".join(b.text for b in blocks)
    head = "\n".join(b.text for b in blocks[:25])[:2500]

    title = _title(blocks, filename)
    meta = DocMeta(title=title)

    # Date: prefer one introduced by an effective/issued keyword near the top.
    keyed = re.search(r"(effective(?:\s+from)?|w\.?e\.?f\.?|dated|date\s+of\s+issue|issued\s+on|submitted\s+on|date(?!\s+of\s+birth))\s*[:\-]?\s*(.{0,40})", head, re.I)
    d = parse_date(keyed.group(2)) if keyed else None
    if d is None:
        d = parse_date(head)
    meta.doc_date = d.isoformat() if d else None
    meta.years = sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", f"{filename} {title}")})

    for b in blocks[:6]:
        if AUTHORITY.search(b.text) and len(b.text) < 120 and not b.text.startswith("•") and ":" not in b.text[:30]:
            meta.authority = b.text
            break

    meta.references = sorted({m.group(1).rstrip(".") for m in REF_ID.finditer(head)})

    kv_lines = 0
    people: list[str] = []
    for b in blocks:
        for part in re.split(r"\s*\|\s*|\n", b.text):
            m = KV_LINE.match(part.strip())
            if m:
                kv_lines += 1
                if NAME_KEYS.match(m.group(1).strip()):
                    people.append(_clean_name(m.group(2)))
                    meta.subjects.append(_clean_name(m.group(2)))
    for rx in (RELATION_NAME, CERTIFY_NAME):
        people.extend(_clean_name(m.group(1)) for m in rx.finditer(full))
    meta.people = [p for p in dict.fromkeys(people) if p and len(p.split()) <= 4]
    meta.subjects = [p for p in dict.fromkeys(meta.subjects) if p and len(p.split()) <= 4]
    if not meta.subjects:
        # "father of Priya Sharma" / "certify that X": the person the certificate is about
        rel = [_clean_name(m.group(1)) for m in RELATION_NAME.finditer(full)]
        meta.subjects = list(dict.fromkeys(r for r in rel if r))[:2]

    modal = len(MODAL.findall(full))
    has_amendment = bool(SUPERSEDE.search(full) or AMEND.search(full))
    if RECORD_HINT.search(full) or (meta.people and kv_lines >= 3):
        meta.role = "record"
    elif modal >= 3 or has_amendment:
        meta.role = "policy"
    else:
        meta.role = "reference"

    sentences = [s for b in blocks if b.kind != "heading" for s in split_sentences(b.text)]
    for s in sentences:
        if SUPERSEDE.search(s):
            meta.amendments.append({"kind": "supersede", "sentence": s})
        elif AMEND.search(s):
            meta.amendments.append({"kind": "amend", "sentence": s})
    return meta


def _clean_name(raw: str) -> str:
    raw = re.split(r"[,;(|]|\s{2,}", raw.strip())[0]
    raw = re.sub(r"^(shri|smt\.?|mr\.?|ms\.?|mrs\.?|kumari|kum\.?)\s+", "", raw, flags=re.I)
    words = [w for w in raw.split() if w[:1].isupper()]
    return " ".join(words[:4])


def _title(blocks, filename: str) -> str:
    heads = [b for b in blocks[:20] if b.kind == "heading"]
    for b in heads:
        if TITLE_WORDS.search(b.text) and len(b.text) <= 110:
            return _tidy(b.text)
    if heads:
        return _tidy(heads[0].text)
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    return re.sub(r"[_\-]+", " ", stem).strip()


def _tidy(t: str) -> str:
    if t.isupper():
        t = t.title()
    return t.strip(" :-–")
