"""ablation.py — BM25 vs dense vs hybrid-RRF on the dispute corpus.

Gold = the single passage a reviewer would want first. Two query families:
  structured   the exact `query_for(reason_code)` string the graph uses (keyword-heavy)
  natural      how an analyst would actually phrase it (paraphrased, no reason code)
Reports R@1, R@3 and MRR per ranker. Needs requirements-dense.txt.

  python eval/ablation.py            -> results/ablation.md
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from disputedesk.dense import DenseIndex                    # noqa: E402
from disputedesk.models import ReasonCode                   # noqa: E402
from disputedesk.retrieval import Retriever, _rrf, query_for  # noqa: E402

D = "dispute_guidelines#"
STRUCTURED = [(query_for(rc), D + "reason-code-" + rc.value.replace(".", "-")) for rc in ReasonCode]

NATURAL = [
    ("customer says the parcel never arrived, what proof do we need to send", "reason-code-13-1"),
    ("chargeback on a subscription the customer claims they cancelled last month", "reason-code-13-2"),
    ("item arrived damaged and the cardholder is disputing the charge", "reason-code-13-3"),
    ("we already refunded this order but still got a chargeback", "reason-code-13-6"),
    ("the customer was charged twice for one order", "reason-code-12-6"),
    ("cardholder says they never made this online purchase, card must be stolen", "reason-code-10-4"),
    ("how many days do we have to respond to a dispute", "timelines-for-merchant"),
    ("what does it cost if we lose at arbitration", "escalation-to-pre-arbitration"),
    ("is it better to just accept a small dispute", "accepting-a-dispute"),
    ("payment failed, customer account debited, merchant got no confirmation — what does the RBI say", "rbi-harmonisation"),
    ("what are the stages a dispute goes through", "dispute-lifecycle"),
    ("which evidence do I need for each type of dispute", "evidence-requirements"),
]


def _score(rankings: list[list[int]], golds: list[str], ids: list[str]) -> dict:
    r1 = r3 = mrr = 0.0
    for order, gold in zip(rankings, golds):
        hit = [i for i, idx in enumerate(order) if gold in ids[idx]]
        rank = hit[0] + 1 if hit else None
        r1 += rank == 1
        r3 += bool(rank and rank <= 3)
        mrr += (1 / rank) if rank else 0
    n = len(golds)
    return {"R@1": r1 / n, "R@3": r3 / n, "MRR": mrr / n}


def main() -> str:
    ret = Retriever(dense=False)
    ids = [p.passage_id for p in ret.passages]
    dense = DenseIndex(ret.passages)
    sections = []
    for name, qs in (("structured (graph queries)", [(q, g.split("#")[1]) for q, g in STRUCTURED]),
                     ("natural-language (analyst queries)", NATURAL),
                     ("all", [(q, g.split("#")[1]) for q, g in STRUCTURED] + NATURAL)):
        queries, golds = [q for q, _ in qs], [g for _, g in qs]
        bm = [ret._bm25_rank(q) for q in queries]
        de = [dense.rank(q) for q in queries]
        hy = [_rrf([b, d]) for b, d in zip(bm, de)]
        rows = {"BM25": _score(bm, golds, ids), "dense (bge-small)": _score(de, golds, ids), "hybrid RRF": _score(hy, golds, ids)}
        sections.append(f"### {name} — n={len(qs)}\n\n| Ranker | R@1 | R@3 | MRR |\n|---|---|---|---|\n" +
                        "\n".join(f"| {k} | {v['R@1']:.2f} | {v['R@3']:.2f} | {v['MRR']:.2f} |" for k, v in rows.items()))
    md = ("# Retrieval ablation — BM25 vs dense vs hybrid\n\n"
          f"Corpus: {len(ids)} heading-chunked passages. Gold = one passage per query. "
          "Dense = BAAI/bge-small-en-v1.5 + FAISS inner product; hybrid = reciprocal-rank fusion (c=60).\n\n"
          + "\n\n".join(sections) + "\n")
    out = ROOT / "results" / "ablation.md"
    out.write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    print(main())
