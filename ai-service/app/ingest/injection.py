"""Prompt-injection scanner.

Document text is evidence, never instructions. This layer finds passages that *read like
instructions to an AI system* so they can be (1) shown to the user, (2) excluded from fact
extraction, and (3) redacted before any text reaches an LLM. Text that is invisible in the
rendered document (white or microscopic) is always treated as high risk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingest.text_utils import split_sentences

# (pattern, weight, label) - weights add up per sentence; >= 1.0 flags it.
_PATTERNS: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|prompts?|rules|guidelines|directions|context|constraints)\b", re.I), 1.0,
     "Tells the reader to ignore its instructions"),
    (re.compile(r"\b(reveal|print|show|output|repeat|leak|display)\b.{0,30}\b(system\s+prompt|hidden\s+instructions?|your\s+instructions|initial\s+prompt)\b", re.I), 1.0,
     "Asks for the system prompt"),
    (re.compile(r"\byou\s+are\s+(now|no\s+longer)\b", re.I), 0.8, "Tries to reassign the assistant's role"),
    (re.compile(r"\b(system|admin(istrator)?|developer|root|god)\s+(override|mode|prompt|message|access|command)\b", re.I), 0.8,
     "Claims system or administrator authority"),
    (re.compile(r"\b(act|behave|respond|pretend)\s+(as|like)\s+(if|an?|the)\b", re.I), 0.5, "Role-play instruction"),
    (re.compile(r"\b(report|state|declare|output|answer|return|mark|rate)\b.{0,80}\b(100\s*%|full|maximum|complete)\s+(confidence|certainty)\b", re.I), 1.0,
     "Dictates the confidence of the answer"),
    (re.compile(r"\b(do\s+not|don'?t|never)\s+(mention|reveal|disclose|report|flag|show)\b.{0,50}\b(conflicts?|instructions?|this|discrepanc\w+|issues?|evidence)\b", re.I), 1.0,
     "Asks to hide information"),
    (re.compile(r"\bnew\s+instructions?\b|\binstructions?\s+for\s+(the\s+)?(ai|assistant|model|llm|chatbot)\b", re.I), 1.0,
     "Addresses instructions to an AI"),
    (re.compile(r"<\s*/?\s*(system|assistant|user|instructions?|prompt)\s*>", re.I), 1.0, "Contains chat-role markup"),
    (re.compile(r"(^|\s)(assistant|system|user)\s*:\s", re.I), 0.5, "Contains chat-role labels"),
    (re.compile(r"\b(jailbreak|dan\s+mode|prompt\s+injection)\b", re.I), 1.0, "Known jailbreak vocabulary"),
    (re.compile(r"\b(ai|assistant|model|llm|language\s+model|chatbot)\b.{0,60}\b(must|should|shall|will)\b", re.I), 0.5,
     "Directs an AI system"),
]


@dataclass
class InjectionFinding:
    text: str
    score: float
    reasons: list[str]
    hidden: bool
    severity: str


def scan_text(text: str, hidden: bool = False) -> list[InjectionFinding]:
    findings = []
    for sentence in split_sentences(text) or [text]:
        score, reasons = 0.0, []
        for pattern, weight, label in _PATTERNS:
            if pattern.search(sentence):
                score += weight
                reasons.append(label)
        if score >= 1.0 or (hidden and score >= 0.5):
            if hidden:
                reasons.insert(0, "Text is invisible in the rendered document")
            severity = "HIGH" if hidden or score >= 2.0 else "MEDIUM"
            findings.append(InjectionFinding(sentence, round(score, 2), reasons, hidden, severity))
    if hidden and not findings and len(text.strip()) > 40:
        # Invisible prose is suspicious even without known phrases.
        findings.append(InjectionFinding(text.strip()[:500], 0.5, ["Text is invisible in the rendered document"], True, "MEDIUM"))
    return findings


REDACTION = "[instruction-like text removed by VERITAS security layer]"


def redact(text: str, flagged_sentences: list[str]) -> str:
    for s in flagged_sentences:
        if s and s in text:
            text = text.replace(s, REDACTION)
    return text
