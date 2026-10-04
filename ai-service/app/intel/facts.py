"""Fact extraction: typed, comparable values with the attribute they describe.

"The annual family income ... must not exceed ₹2,50,000" becomes
    Fact(type=money, value=250000, comparator=lte, label="annual family income", role=requirement)
and "Annual Family Income: Rs. 1,85,000/-" in an application form becomes
    Fact(type=money, value=185000, comparator=eq, label="Annual Family Income", role=subject).

Facts are what make conflict detection and criteria checks *computable* instead of guessed.
The attribute is matched across documents by embedding a value-masked version of the clause,
so the engine is not tied to one domain's vocabulary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.ingest.metadata import KV_LINE, find_dates
from app.ingest.text_utils import STOPWORDS, content_terms, split_sentences

T_MONEY, T_PERCENT, T_SCORE, T_AGE, T_DATE, T_ASSERTION = "money", "percent", "score", "age", "date", "assertion"

MONEY = re.compile(r"(?:₹|\brs\.?|\binr\b|\brupees\b)\s*([\d,]+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?|k\b)?(?:\s*/-)?"
                   r"|\b(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)\b", re.I)
PERCENT = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s?cent\b|percent\b)", re.I)
SCORE = re.compile(r"\b(\d{1,2}(?:\.\d{1,2})?)\s*(?:cgpa|gpa|sgpa)\b|\b(?:cgpa|gpa|sgpa)\s*(?:of\s*)?[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)\b", re.I)
AGE_RANGE = re.compile(r"\bbetween\s+(\d{1,2})\s+and\s+(\d{1,2})\s+years\b|\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s+years\b", re.I)
AGE_SINGLE = re.compile(r"\b(\d{1,2})\s+years\b", re.I)

LTE = re.compile(r"(not\s+exceed\w*|does\s+not\s+exceed|not\s+more\s+than|no\s+more\s+than|up\s*to|upto|maximum(\s+of)?|max\.?|"
                 r"below|less\s+than|under|within|ceiling(\s+of)?|at\s+most|capped\s+at|limit(ed)?\s+(of|to)|"
                 r"on\s+or\s+before|before|not\s+later\s+than|last\s+date|deadline|by)\s*$", re.I)
GTE = re.compile(r"(at\s+least|minimum(\s+of)?|min\.?|not\s+less\s+than|no\s+less\s+than|more\s+than|above|over|"
                 r"on\s+or\s+after|after|not\s+earlier\s+than|from)\s*$", re.I)
GTE_AFTER = re.compile(r"^\s*(or\s+(above|more|higher)|and\s+above)", re.I)
LTE_AFTER = re.compile(r"^\s*(or\s+(below|less|lower)|and\s+below)", re.I)

REQUIREMENT_WORDS = re.compile(r"\b(must|shall|should|required|requirement|eligible|eligibility|ineligible|mandatory|"
                               r"not\s+exceed|minimum|maximum|at\s+least|qualify|limit|ceiling|deadline|last\s+date|"
                               r"entitled|permitted|allowed|only)\b", re.I)
DISQUALIFY = re.compile(r"\b(not\s+(be\s+)?eligible|ineligible|disqualified|shall\s+not\s+be\s+considered|will\s+be\s+rejected)\b", re.I)
# Assertions = eligibility-type statements whose polarity can contradict another document's.
NEGATION = re.compile(r"\b(not\s+(be\s+)?(eligible|allowed|permitted|accepted|covered|entitled|considered|admissible)|"
                      r"ineligible|prohibited|excluded|disallowed|cannot\s+(apply|claim|be)|does\s+not\s+cover|"
                      r"will\s+not\s+be|shall\s+not\s+be|no\s+longer)\b", re.I)
ASSERTION_TRIGGER = re.compile(r"\b(eligible|ineligible|allowed|permitted|prohibited|accepted|excluded|covered|cover|"
                               r"entitled|admissible|may\s+apply|can\s+apply|cannot\s+apply)\b", re.I)
METADATA_KEYS = re.compile(r"\b(dated?|date\s+of\s+issue|issued(\s+on)?|effective(\s+from)?|w\.?e\.?f|ref|reference|"
                           r"no\.|number|signed|place|printed|generated)\b", re.I)
VERB_SPLIT = re.compile(r"\b(must|shall|should|will|may|can|is|are|was|were|be|has|have|had|stands?|remains?|"
                        r"includes?|covers?|provides?|consists?)\b", re.I)
PREP = re.compile(r"\b(of|from|for|in|on|at|by|to|with|under|as|per|during|towards)\b", re.I)
ACTOR = {"applicant", "applicants", "student", "students", "candidate", "candidates", "beneficiary", "person", "he", "she",
         "they", "employee", "claimant"}
TYPE_LABEL = {T_AGE: "age", T_SCORE: "academic score (CGPA)"}


@dataclass
class Fact:
    type: str
    value: float | str
    comparator: str            # lte | gte | eq | range
    display: str
    label: str
    role: str                  # requirement | subject | statement | metadata
    sentence: str
    attr_text: str             # value-masked text used to match attributes
    value_hi: float | None = None
    sent_start: int = 0
    sent_end: int = 0
    key: str | None = None
    embedding: list[float] | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "embedding"}
        return d


# ------------------------------------------------------------------ values

def _money_value(m: re.Match) -> float | None:
    num, mult = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    mult = (mult or "").lower()
    if mult.startswith("lakh") or mult.startswith("lac"):
        v *= 100_000
    elif mult.startswith("crore"):
        v *= 10_000_000
    elif mult == "k":
        v *= 1_000
    return v


def format_inr(v: float) -> str:
    n = int(round(v))
    s = str(n)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups) + "," + tail


def format_value(type_: str, value, value_hi=None) -> str:
    if type_ == T_MONEY:
        return format_inr(value)
    if type_ == T_PERCENT:
        return f"{value:g}%"
    if type_ == T_SCORE:
        return f"{value:g} CGPA"
    if type_ == T_AGE:
        return f"{value:g}–{value_hi:g} years" if value_hi is not None else f"{value:g} years"
    if type_ == T_DATE:
        try:
            return _date_display(date.fromisoformat(value))
        except ValueError:
            return str(value)
    return str(value)


def _date_display(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def _values(text: str) -> list[tuple[str, float | str, float | None, int, int]]:
    """(type, value, value_hi, start, end) for every value in text, without overlaps."""
    out = []
    taken: list[tuple[int, int]] = []

    def free(s, e):
        return all(e <= a or s >= b for a, b in taken)

    for d, s, e in find_dates(text):
        out.append((T_DATE, d.isoformat(), None, s, e))
        taken.append((s, e))
    for m in MONEY.finditer(text):
        if free(m.start(), m.end()):
            v = _money_value(m)
            if v is not None and v >= 1:
                out.append((T_MONEY, v, None, m.start(), m.end()))
                taken.append((m.start(), m.end()))
    for m in PERCENT.finditer(text):
        if free(m.start(), m.end()):
            v = float(m.group(1))
            if 0 <= v <= 100:
                out.append((T_PERCENT, v, None, m.start(), m.end()))
                taken.append((m.start(), m.end()))
    for m in SCORE.finditer(text):
        if free(m.start(), m.end()):
            v = float(m.group(1) or m.group(2))
            if 0 < v <= 10:
                out.append((T_SCORE, v, None, m.start(), m.end()))
                taken.append((m.start(), m.end()))
    has_age_word = re.search(r"\b(age|aged|old|years\s+of\s+age)\b", text, re.I)
    for m in AGE_RANGE.finditer(text):
        if free(m.start(), m.end()) and has_age_word:
            lo, hi = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            lo, hi = float(lo), float(hi)
            if 0 < lo < hi < 120:
                out.append((T_AGE, lo, hi, m.start(), m.end()))
                taken.append((m.start(), m.end()))
    if has_age_word:
        for m in AGE_SINGLE.finditer(text):
            if free(m.start(), m.end()):
                v = float(m.group(1))
                if 0 < v < 120:
                    out.append((T_AGE, v, None, m.start(), m.end()))
                    taken.append((m.start(), m.end()))
    out.sort(key=lambda x: x[3])
    return out


def _mask(text: str, values) -> str:
    masked, last = [], 0
    for t, _, _, s, e in values:
        masked.append(text[last:s])
        masked.append(f"[{t.upper()}]")
        last = e
    masked.append(text[last:])
    return re.sub(r"\s+", " ", "".join(masked)).strip()


STRONG_LTE = re.compile(r"\b(not\s+exceed\w*|does\s+not\s+exceed|not\s+more\s+than|no\s+more\s+than|up\s*to|upto|"
                        r"maximum|ceiling|at\s+most|capped\s+at|not\s+later\s+than|on\s+or\s+before)\b", re.I)
STRONG_GTE = re.compile(r"\b(at\s+least|minimum|not\s+less\s+than|no\s+less\s+than|on\s+or\s+after|not\s+earlier\s+than)\b", re.I)
CLAUSE_BREAK = re.compile(r",\s+|;\s*|\s+and\s+|\s+or\s+|:\s+|\?\s+|\.\s+")
SKIP_WORDS = {"provided", "secures", "secure", "secured", "obtains", "obtain", "obtained", "maintains", "maintain",
              "need", "needs", "has", "have", "had", "get", "gets", "scored", "scores", "score", "achieve", "achieves",
              "achieved", "earn", "earns", "earned", "receive", "receives", "hold", "holds", "if", "where", "whose",
              "hereby", "extended", "revised", "amended", "paid", "payable", "fixed", "set", "you", "your", "i", "we"}
NP_STOP = {"has", "have", "had", "is", "are", "was", "were", "be", "that", "which", "who", "with", "and", "or", "but",
           "must", "shall", "should", "will", "may", "can", "secures", "secured", "obtained", "maintains", "certify",
           "hereby", "extended", "revised", "to", "by", "on", "at", "in", "from"}


def _clause_before(sentence: str, start: int) -> str:
    before = sentence[:start]
    breaks = list(CLAUSE_BREAK.finditer(before))
    # do not cut inside the number we are labelling, and keep at least a few words
    for m in reversed(breaks):
        tail = before[m.end():]
        if len(tail.split()) >= 2:
            return tail
    return before


def _comparator(text: str, start: int, end: int, type_: str, value_hi) -> str:
    if value_hi is not None:
        return "range"
    clause = _clause_before(text, start)
    before = clause[-45:]
    after = text[end:end + 25]
    if GTE_AFTER.search(after):
        return "gte"
    if LTE_AFTER.search(after):
        return "lte"
    b = before.rstrip(" :,₹(")
    m_lte, m_gte = LTE.search(b), GTE.search(b)
    if not m_lte and not m_gte:
        m_lte, m_gte = STRONG_LTE.search(clause), STRONG_GTE.search(clause)
    if m_lte and (not m_gte or m_lte.start() > m_gte.start()):
        word = m_lte.group(1).lower()
        if type_ != T_DATE and word in {"before", "by", "last date", "deadline", "not later than", "on or before"}:
            return "eq"
        return "lte"
    if m_gte:
        word = m_gte.group(1).lower()
        if type_ != T_DATE and word in {"after", "on or after", "not earlier than"}:
            return "eq"
        if type_ == T_DATE and word in {"from", "over", "above", "more than"}:
            return "eq"
        return "gte"
    # "the last date ... is 31 July 2026" - a deadline stated as equality
    if type_ == T_DATE and re.search(r"\b(last\s+date|deadline|due\s+date|closing\s+date)\b", text, re.I):
        return "lte"
    return "eq"


def _label(sentence: str, start: int, end: int, type_: str) -> str:
    if type_ in TYPE_LABEL:
        return TYPE_LABEL[type_]
    clause = _clause_before(sentence, start)
    stripped = clause.rstrip(" :,₹(")
    while True:  # peel trailing comparator words ("must not exceed", "of up to")
        m = LTE.search(stripped) or GTE.search(stripped)
        if not m or m.start() == 0 and not stripped[: m.start()]:
            stripped = stripped[: m.start()].rstrip() if m else stripped
            break
        stripped = stripped[: m.start()].rstrip()

    # Strategy 1: "<noun phrase> of|is|: VALUE" -> the noun phrase right before the value.
    m = re.search(r"(?:\bof|\bis|\bare|\bat|\bas|:|=)\s*$", stripped, re.I)
    if m:
        np = _noun_phrase_backwards(stripped[: m.start()])
        if np:
            return np
    # Strategy 2: the grammatical subject of the clause ("The annual family income ... must not exceed").
    verbs = list(VERB_SPLIT.finditer(clause))
    subject = clause[: verbs[0].start()] if verbs else clause
    label = _phrase(subject)
    if label:
        return label
    # Strategy 3: the words after the value ("at least 60% aggregate marks in ...").
    after = sentence[end:]
    after = re.split(r"[.;,()]|\b(in|of|for|from|during|per|as)\b", after, maxsplit=1, flags=re.I)[0]
    label = _phrase(after)
    return label or type_


def _noun_phrase_backwards(text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*|[,;:()]", text)
    out: list[str] = []
    for w in reversed(words):
        lw = w.lower()
        if w in ",;:()" or lw in NP_STOP or lw in ACTOR or len(out) >= 7:
            break
        out.insert(0, w)
    while out and (out[0].lower() in STOPWORDS or out[0].lower() in SKIP_WORDS or PREP.fullmatch(out[0].lower())):
        out.pop(0)
    while out and (out[-1].lower() in STOPWORDS or PREP.fullmatch(out[-1].lower())):
        out.pop()
    if not [w for w in out if w.lower() not in STOPWORDS]:
        return ""
    return " ".join(out).lower()


def _phrase(text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    # drop leading articles/actor words; cut at the first preposition once we have content
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if PREP.fullmatch(lw):
            if any(x.lower() not in STOPWORDS and x.lower() not in ACTOR for x in out):
                break
            out = []
            continue
        if lw in {"the", "a", "an", "this", "that", "such", "any", "all", "total", "said", "these", "those"}:
            continue
        if lw in ACTOR or lw in SKIP_WORDS:
            continue
        if LTE.fullmatch(lw) or GTE.fullmatch(lw) or lw in {"not", "exceed", "minimum", "maximum", "least", "up"}:
            continue
        out.append(w)
    content = [w for w in out if w.lower() not in STOPWORDS]
    if not content:
        return ""
    return " ".join(out[:6]).strip().lower()


# ------------------------------------------------------------------ extraction

def extract_facts(chunk_text: str, doc_role: str, flagged_sentences: list[str]) -> list[Fact]:
    facts: list[Fact] = []
    flagged = set(flagged_sentences)
    cursor = 0
    for raw_line in chunk_text.split("\n"):
        line_start = chunk_text.find(raw_line, cursor)
        cursor = line_start + len(raw_line)
        parts = [p for p in re.split(r"\s+\|\s+", raw_line) if p.strip()]
        kv_handled = False
        for part in parts:
            m = KV_LINE.match(part.strip())
            if m and len(m.group(1).split()) <= 7 and not re.search(r"\b(must|shall)\b", m.group(1), re.I):
                kv_handled = True
                key, val = m.group(1).strip(), m.group(2).strip()
                vals = _values(val)
                if not vals:
                    continue
                p_start = chunk_text.find(part, line_start)
                role = "metadata" if METADATA_KEYS.search(key) and not re.search(r"birth|deadline|last\s+date", key, re.I) \
                    else ("subject" if doc_role == "record" else "statement")
                for t, v, hi, s, e in vals:
                    facts.append(Fact(
                        type=t, value=v, value_hi=hi, comparator=_comparator(val, s, e, t, hi) if role != "subject" else "eq",
                        display=_display(t, v, hi), label=key.lower(), key=key, role=role, sentence=part.strip(),
                        attr_text=f"{key}. {key}: [{t.upper()}]", sent_start=max(p_start, 0), sent_end=max(p_start, 0) + len(part),
                    ))
        if kv_handled and len(parts) > 1:
            continue
        if kv_handled:
            continue
        for sentence in split_sentences(raw_line):
            if sentence in flagged or any(f and f in sentence for f in flagged):
                continue  # instruction-like text never becomes a fact
            s_start = chunk_text.find(sentence, line_start)
            vals = _values(sentence)
            for t, v, hi, s, e in vals:
                if t == T_DATE and re.search(r"\bas\s+(on|of|at)\s*$", sentence[:s], re.I):
                    continue  # "25 years of age as on 1 July 2026": a reference date, not a fact of its own
                comp = _comparator(sentence, s, e, t, hi)
                is_req = bool(REQUIREMENT_WORDS.search(sentence)) or comp != "eq"
                if doc_role == "record":
                    role = "subject"
                elif re.search(r"\b(dated|date\s+of\s+issue|issued\s+on|effective\s+from|w\.?e\.?f)\b", sentence[:max(0, s)][-40:], re.I):
                    role = "metadata"
                else:
                    role = "requirement" if is_req else "statement"
                if role == "requirement" and DISQUALIFY.search(sentence) and comp in {"gte", "lte"}:
                    comp = "lte" if comp == "gte" else "gte"   # "income above X is not eligible" == limit X
                label = _label(sentence, s, e, t)
                facts.append(Fact(
                    type=t, value=v, value_hi=hi, comparator=comp, display=_display(t, v, hi), label=label,
                    role=role, sentence=sentence, attr_text=f"{label}. {_mask(sentence, vals)}",
                    sent_start=max(s_start, 0), sent_end=max(s_start, 0) + len(sentence),
                ))
            if not vals and doc_role != "record" and ASSERTION_TRIGGER.search(sentence) and 30 <= len(sentence) <= 400:
                polarity = -1.0 if NEGATION.search(sentence) else 1.0
                facts.append(Fact(
                    type=T_ASSERTION, value=polarity, comparator="eq", display="negative" if polarity < 0 else "positive",
                    label=" ".join(content_terms(sentence)[:6]), role="assertion", sentence=sentence,
                    attr_text=_neutralize(sentence), sent_start=max(s_start, 0), sent_end=max(s_start, 0) + len(sentence),
                ))
    return facts


def _display(t, v, hi) -> str:
    if t == T_DATE:
        return _date_display(date.fromisoformat(v))
    return format_value(t, v, hi)


def _neutralize(sentence: str) -> str:
    """Remove negation so 'X are eligible' and 'X are not eligible' embed close together."""
    s = re.sub(r"\b(not|no|never|cannot|can't)\b", " ", sentence, flags=re.I)
    s = re.sub(r"\bineligible\b", "eligible", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def satisfies(subject_value, comparator: str, req_value, req_hi=None) -> bool | None:
    """Does a subject value meet a requirement? None when not comparable."""
    try:
        if comparator == "lte":
            return subject_value <= req_value
        if comparator == "gte":
            return subject_value >= req_value
        if comparator == "range":
            return req_value <= subject_value <= req_hi
        if comparator == "eq":
            return subject_value == req_value
    except TypeError:
        return None
    return None
