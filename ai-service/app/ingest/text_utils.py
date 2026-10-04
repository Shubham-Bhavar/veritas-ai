"""Small text helpers shared by ingestion and reasoning."""
from __future__ import annotations

import re

_ABBREV = r"(?:Rs|No|Nos|Dr|Mr|Mrs|Ms|Smt|Shri|Sh|Prof|St|vs|viz|etc|e\.g|i\.e|approx|Govt|Dept|Sr|Jr|Ltd|Co|Inc|para|Para|Sec|Art|cl|Fig|p|pp|Vol)"
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9₹•])")

STOPWORDS = frozenset("""
a an the and or of to in on for from by with at as is are was were be been being this that these those it its
which who whom whose what when where why how all any each every both either neither no not nor only own same so
than too very can could shall should will would may might must do does did done has have had having i me my we
our you your he him his she her they them their there here into over under above below up down out off again
further then once also such per upon about between during before after other same s t just than whether if while
under within without across via
""".split())

GENERIC_QUERY_WORDS = frozenset("""
document documents evidence source sources say says said state states stated mention mentions mentioned according
tell explain describe what which who whom whose how why where when does do did is are was were can could would should
please show give list find information info detail details regarding about related support supports supported
conclusion answer question collection file files based provide provided
""".split())

_TOKEN = re.compile(r"[a-z0-9₹%]+(?:[.,][0-9]+)*")


def split_sentences(text: str) -> list[str]:
    """Sentence split that respects abbreviations such as 'Rs.' and 'No.'."""
    protected = re.sub(r"\b" + _ABBREV + r"\.", lambda m: m.group(0)[:-1] + "\u2024", text)
    protected = re.sub(r"(\d)\.(\d)", "\\1\u2024\\2", protected)
    parts = _SPLIT.split(protected)
    out = []
    for p in parts:
        p = p.replace("\u2024", ".").strip()
        if p:
            out.append(p)
    return out


def stem(word: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ers", "er", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            if suffix in ("ies", "ied"):
                return word[: -len(suffix)] + "y"
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def content_terms(text: str, extra_stop: frozenset[str] = frozenset()) -> list[str]:
    """Lower-cased, stemmed content words (no stopwords, no pure numbers)."""
    out = []
    for t in tokens(text):
        if t in STOPWORDS or t in extra_stop or len(t) < 2:
            continue
        if re.fullmatch(r"[\d.,%₹]+", t):
            continue
        out.append(stem(t))
    return out


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
