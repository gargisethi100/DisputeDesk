"""run_eval.py — run the ten cases through the graph, score, write results/eval.md.

Metrics:
  action accuracy (after gate)   final_action == expected          <- the number that matters
  raw model accuracy (before)    proposed_action == expected       <- what the gate is worth
  citation faithfulness          all citations verified verbatim
  escalation rate                share of decided cases the gate/model sent to a human
  adversarial flagged            DSP009 screening hit
  tenant isolation               DSP010 raised TenantViolation

Usage:  python eval/run_eval.py            (provider from .env; mock by default)
        python eval/run_eval.py --out results/eval_bedrock.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv                       # noqa: E402
load_dotenv(ROOT / ".env")

from disputedesk.graph import run_until_review      # noqa: E402
from disputedesk.tools import TenantViolation       # noqa: E402
from eval.cases import CASES                        # noqa: E402


def run() -> tuple[list[dict], dict]:
    rows = []
    for c in CASES:
        row = {**c, "proposed": "-", "final": "-", "source": "-", "cits": "-", "verified": "-", "screen": "-", "reasons": ""}
        try:
            _, s = run_until_review(c["dispute_id"], c["merchant_id"])
        except TenantViolation:
            row.update(final="tenant_violation", proposed="tenant_violation")
            rows.append(row)
            continue
        r, g, v = s["recommendation"], s["gate"], s["verification"]
        row.update(proposed=r["action"], final=g["final_action"], source=r["source"], cits=len(r["citations"]),
                   verified=v["all_verified"], screen=s["screening"]["flagged"], reasons="; ".join(g["reasons"]))
        rows.append(row)

    decided = [r for r in rows if r["expected"] != "tenant_violation"]
    m = {
        "provider": os.getenv("DISPUTEDESK_LLM_PROVIDER", "mock"),
        "after_gate": sum(r["final"] == r["expected"] for r in rows), "n": len(rows),
        "raw": sum(r["proposed"] == r["expected"] for r in decided), "n_decided": len(decided),
        "faithful": sum(bool(r["verified"]) for r in decided if r["cits"] not in ("-", 0)),
        "n_cited": sum(1 for r in decided if r["cits"] not in ("-", 0)),
        "escalated": sum(r["final"] == "escalate" for r in decided),
        "adv_flagged": sum(bool(r["screen"]) for r in rows if r["flagged"]), "n_adv": sum(1 for r in rows if r["flagged"]),
        "tenant_ok": sum(r["final"] == "tenant_violation" for r in rows if r["expected"] == "tenant_violation"),
        "llm_used": sum(r["source"] == "llm" for r in decided),
    }
    return rows, m


def render(rows: list[dict], m: dict) -> str:
    pct = lambda a, b: f"{100*a/b:.0f}% ({a}/{b})" if b else "n/a"
    out = [f"# Eval — provider `{m['provider']}`", "",
           "| Metric | Value |", "|---|---|",
           f"| Action accuracy (after policy gate) | **{pct(m['after_gate'], m['n'])}** |",
           f"| Raw model accuracy (before gate) | {pct(m['raw'], m['n_decided'])} |",
           f"| Citation faithfulness (verbatim) | {pct(m['faithful'], m['n_cited'])} |",
           f"| Escalation rate | {pct(m['escalated'], m['n_decided'])} |",
           f"| Adversarial cases flagged | {m['adv_flagged']}/{m['n_adv']} |",
           f"| Cross-tenant cases blocked | {m['tenant_ok']}/1 |",
           f"| Recommendations from the LLM (vs heuristic) | {m['llm_used']}/{m['n_decided']} |",
           "", "| Case | Note | Expected | Proposed | Final | Src | Cits | Verified | Flagged | Gate reasons |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ok = "✅" if r["final"] == r["expected"] else "❌"
        out.append(f"| {r['dispute_id']} | {r['note']} | {r['expected']} | {r['proposed']} | {ok} {r['final']} | "
                   f"{r['source']} | {r['cits']} | {r['verified']} | {r['screen']} | {r['reasons']} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/eval.md")
    a = ap.parse_args()
    rows, m = run()
    md = render(rows, m)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(md, encoding="utf-8")
    print(md)
    sys.exit(0 if m["after_gate"] == m["n"] else 1)
