"""redaction.py — PII never reaches a model.

Two mechanisms, layered:
  1. Known-entity masking. We OWN the merchant records, so we know the customer's exact
     name, email, phone and address. Exact-string replacement is deterministic and
     catches things a regex can't (addresses, unusual names).
  2. Regex masking for anything free-text might contain that we didn't know about:
     emails, Indian phone numbers, UPI VPAs, IFSC codes, long account-like digit runs,
     and sign-off lines ("Regards, <name>").

Placeholders look like `[NAME_1]`, `[EMAIL_2]`. `restore()` reverses the mapping — it is
called ONLY when producing reviewer-facing output, never on anything sent to a model.
`has_leak()` is asserted on every prompt before it leaves the process.

This module never imports or calls an LLM.
"""
from __future__ import annotations

import re
from collections import defaultdict

# Order matters: EMAIL before VPA (both contain '@'; email requires a dotted TLD, VPA does not).
_REGEX_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("VPA", re.compile(r"\b[\w.-]{2,}@[a-z]{3,}\b", re.IGNORECASE)),
    ("PHONE", re.compile(r"(?:\+91[\s-]?)?(?<!\d)[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("ACCOUNT", re.compile(r"(?<!\d)\d{11,16}(?!\d)")),
    ("SIGNATURE", re.compile(r"(?im)^(?:regards|thanks|thank you|sincerely|best|cheers)[,.]?\s*\n\s*([^\n]{2,60})$")),
]


class Redactor:
    def __init__(self, known: dict[str, list[str]] | None = None) -> None:
        # known: {"NAME": ["Priya Raman"], "ADDRESS": [...], ...}
        self._known = {k: [v for v in vs if v] for k, vs in (known or {}).items()}
        self._forward: dict[str, str] = {}   # original -> placeholder
        self._reverse: dict[str, str] = {}   # placeholder -> original
        self._counters: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------ core
    def _placeholder(self, kind: str, original: str) -> str:
        if original in self._forward:
            return self._forward[original]
        self._counters[kind] += 1
        ph = f"[{kind}_{self._counters[kind]}]"
        self._forward[original] = ph
        self._reverse[ph] = original
        return ph

    @staticmethod
    def _regex_hits(text: str):
        """Yield (kind, target) for every PII-shaped match that is not already a placeholder."""
        for kind, pat in _REGEX_PATTERNS:
            for m in pat.finditer(text):
                target = m.group(1) if m.lastindex else m.group(0)
                if target.startswith("[") and target.endswith("]"):
                    continue
                yield kind, target

    def redact(self, text: str) -> str:
        if not text:
            return text
        out = text
        # 1. known entities, longest first so "Priya Raman" is masked before "Priya"
        for kind, values in self._known.items():
            for val in sorted(values, key=len, reverse=True):
                if val in out:
                    out = out.replace(val, self._placeholder(kind, val))
        # 2. regex sweep for anything we didn't know about
        for kind, target in list(self._regex_hits(out)):
            out = out.replace(target, self._placeholder(kind, target))
        return out

    def restore(self, text: str) -> str:
        """Reviewer-facing only. Never call on text bound for a model."""
        out = text
        for ph, original in self._reverse.items():
            out = out.replace(ph, original)
        return out

    def has_leak(self, text: str) -> bool:
        """True if any known entity or PII-shaped pattern is present in `text`."""
        for values in self._known.values():
            if any(v in text for v in values):
                return True
        return any(True for _ in self._regex_hits(text))

    @property
    def masked_count(self) -> int:
        return len(self._reverse)

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._reverse)
