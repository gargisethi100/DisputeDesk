"""retrieval.py — heading-chunked corpus, BM25 always on, optional dense + RRF.

Why BM25 first: dispute rules are keyword-heavy — reason codes ("13.1"), stage names
("pre-arbitration"), day counts. Lexical match is the strongest signal, which is also
what ClauseLens measured on a legal corpus (BM25 R@5 .54 vs dense .47). Dense retrieval
is an opt-in ablation (`DISPUTEDESK_DENSE_RETRIEVAL=1`), fused with reciprocal-rank
fusion so neither ranker's raw scores need calibrating against the other.

Chunking on `## ` headings keeps each passage a self-contained rule, so a verbatim
quote from it is meaningful to a reviewer.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from .models import Passage, ReasonCode

CORPUS_DIR = Path(os.getenv("DISPUTEDESK_CORPUS_DIR", "corpus"))

RC_NAMES = {
    ReasonCode.FRAUD_CNP: "fraud card-absent environment unauthorised transaction",
    ReasonCode.DUPLICATE: "duplicate processing charged twice",
    ReasonCode.NOT_RECEIVED: "merchandise services not received delivery",
    ReasonCode.RECURRING_CANCELLED: "cancelled recurring transaction subscription",
    ReasonCode.NOT_AS_DESCRIBED: "not as described defective merchandise",
    ReasonCode.CREDIT_NOT_PROCESSED: "credit not processed refund",
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _tokens(s: str) -> list[str]:
    # keep "13.1" as one token — reason codes are the strongest lexical signal
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", s.lower())


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[Passage]:
    passages: list[Passage] = []
    for md in sorted(corpus_dir.glob("*.md")):
        heading, buf = None, []
        for line in md.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if heading and "".join(buf).strip():
                    passages.append(Passage(passage_id=f"{md.stem}#{_slug(heading)}", heading=heading, text="\n".join(buf).strip()))
                heading, buf = line[3:].strip(), []
            elif heading is not None:
                buf.append(line)
        if heading and "".join(buf).strip():
            passages.append(Passage(passage_id=f"{md.stem}#{_slug(heading)}", heading=heading, text="\n".join(buf).strip()))
    return passages


def query_for(reason_code: ReasonCode) -> str:
    return f"reason code {reason_code.value} {RC_NAMES[reason_code]} evidence merchant response timeline"


class Retriever:
    def __init__(self, passages: list[Passage] | None = None, dense: bool | None = None) -> None:
        self.passages = passages if passages is not None else load_corpus()
        self._bm25 = BM25Okapi([_tokens(p.heading + " " + p.text) for p in self.passages])
        self.dense_enabled = (os.getenv("DISPUTEDESK_DENSE_RETRIEVAL", "0") == "1") if dense is None else dense
        self._dense = None
        if self.dense_enabled:
            try:
                from .dense import DenseIndex   # optional extra; see requirements-dense.txt
                self._dense = DenseIndex(self.passages)
            except Exception as e:              # missing deps -> degrade to BM25, loudly
                print(f"[retrieval] dense retrieval requested but unavailable ({e}); using BM25 only")
                self.dense_enabled = False

    # ---- rankers return ordered lists of passage indices
    def _bm25_rank(self, query: str) -> list[int]:
        scores = self._bm25.get_scores(_tokens(query))
        return sorted(range(len(scores)), key=lambda i: -scores[i])

    def search(self, query: str, k: int = 4) -> list[Passage]:
        bm25 = self._bm25_rank(query)
        if not self._dense:
            order = bm25
        else:
            dense = self._dense.rank(query)
            order = _rrf([bm25, dense])
        out = []
        for rank, i in enumerate(order[:k]):
            p = self.passages[i].model_copy()
            p.score = 1.0 / (rank + 1)
            out.append(p)
        return out


def _rrf(rankings: list[list[int]], c: int = 60) -> list[int]:
    """Reciprocal-rank fusion: score(d) = Σ 1/(c + rank_r(d))."""
    fused: dict[int, float] = {}
    for r in rankings:
        for rank, idx in enumerate(r):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (c + rank + 1)
    return sorted(fused, key=lambda i: -fused[i])
