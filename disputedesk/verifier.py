"""verifier.py — verbatim citation verification. Grounding is checked, not trusted.

Every quote the model cites must appear verbatim in the passage it claims to cite.
This is a normalised substring check: zero LLM cost, no judge, no false negatives
from another model's opinion. An unverified citation blocks a contest (policy_gate).

Normalisation (ported from ClauseLens): LLMs silently tidy punctuation when quoting —
"China ,otherwise" becomes "China, otherwise". Collapsing whitespace, case, and the
spaces around punctuation keeps the check strict against fabrication without
false-flagging benign reformatting.

This module never imports or calls an LLM.
"""
from __future__ import annotations

import re

from .models import Citation, CitationVerdict, Passage, VerificationResult

# Punctuation is dropped entirely, not just de-spaced: the check becomes "same words in
# the same order". An inserted comma is not fabrication; a changed word still is.
_PUNCT_RE = re.compile(r"[" + re.escape(r",.;:!?()[]\"'/-–—“”‘’") + r"]")


def normalise(s: str) -> str:
    s = _PUNCT_RE.sub(" ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def verify_citations(citations: list[Citation], passages: list[Passage]) -> VerificationResult:
    by_id = {p.passage_id: p for p in passages}
    verdicts: list[CitationVerdict] = []
    for c in citations:
        p = by_id.get(c.passage_id)
        if p is None:
            verdicts.append(CitationVerdict(citation=c, verified=False, reason="cited passage was not retrieved"))
            continue
        if len(c.quote.strip()) < 12:
            verdicts.append(CitationVerdict(citation=c, verified=False, reason="quote too short to be meaningful"))
            continue
        ok = normalise(c.quote) in normalise(p.text)
        verdicts.append(CitationVerdict(citation=c, verified=ok, reason="" if ok else "quote not found verbatim in passage"))
    return VerificationResult(all_verified=all(v.verified for v in verdicts), verdicts=verdicts)
