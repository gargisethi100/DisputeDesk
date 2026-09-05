"""screening.py — heuristic prompt-injection screening for untrusted text.

The customer's message is evidence the agent MUST read, and the customer is an
adversary in the dispute. So we assume it may contain instructions aimed at the model.

Design rule: screening FLAGS, it never DECIDES. A hit routes the case to a human and
lands in the audit log; the policy gate is what changes the action. Heuristics get
bypassed — that's fine, because nothing that actually stops harm (tenant scoping,
redaction, the approval token, the gate) depends on this detector firing.

This module never imports or calls an LLM.
"""
from __future__ import annotations

import re

from .models import ScreeningResult

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_previous", re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions?\b", re.I)),
    ("disregard", re.compile(r"\bdisregard\s+(?:all\s+|your\s+|the\s+)?(?:previous|prior|instructions?|rules?|guidelines?)\b", re.I)),
    ("role_override", re.compile(r"\byou\s+are\s+now\s+(?:a|an|the)\b", re.I)),
    ("system_marker", re.compile(r"(?m)^\s*(?:system|assistant|developer)\s*:", re.I)),
    ("new_instructions", re.compile(r"\bnew\s+instructions?\b|\bupdated\s+instructions?\b", re.I)),
    ("action_directive", re.compile(r"\b(?:output|return|set)\s+action\s*=\s*\w+", re.I)),
    ("confidence_directive", re.compile(r"\bconfidence\s*(?:=|of|to)\s*1(?:\.0+)?\b", re.I)),
    ("bypass_human", re.compile(r"\b(?:do\s+not|don't|never)\s+(?:escalate|involve|notify|alert)\s+(?:to\s+)?(?:a\s+)?(?:human|reviewer|person)\b", re.I)),
    ("base64_blob", re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/])")),
    # zero-width / bidi-override characters used to hide instructions from human readers
    ("unicode_control", re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069]")),
]


def screen(text: str) -> ScreeningResult:
    hits = [name for name, pat in _PATTERNS if pat.search(text or "")]
    return ScreeningResult(flagged=bool(hits), hits=hits)


def fence(text: str) -> str:
    """Wrap untrusted text so the prompt can state, structurally, that it is data."""
    safe = (text or "").replace("</untrusted_customer_message>", "[/untrusted]")
    return f"<untrusted_customer_message>\n{safe}\n</untrusted_customer_message>"
