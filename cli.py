"""cli.py — run one dispute through the graph from the terminal.

  python cli.py DSP001 --approve
  python cli.py DSP009                       # stops at the human interrupt
  python cli.py DSP010                       # TenantViolation from MER001
  python cli.py DSP010 --merchant MER002 --approve
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from disputedesk.graph import resume_with_decision, run_until_review
from disputedesk.models import ReviewDecision
from disputedesk.tools import TenantViolation

load_dotenv()


def _hr(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 70 - len(title)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dispute_id")
    ap.add_argument("--merchant", default="MER001")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--edit", metavar="BODY", help="approve with an edited response body")
    ap.add_argument("--reviewer", default=os.getenv("DISPUTEDESK_REVIEWER", "analyst@example.com"))
    args = ap.parse_args()

    try:
        thread_id, s = run_until_review(args.dispute_id, args.merchant)
    except TenantViolation as e:
        print(f"\nDENIED — {e}\n(the toolbox is bound to {args.merchant}; this record is not visible to it)")
        return 2

    d = s["dispute"]
    _hr(f"{d['dispute_id']}  reason {d['reason_code']}  {d['amount_paise']/100:.2f} {d['currency']}  respond_by {d['respond_by'][:10]}")
    print(f"provider={os.getenv('DISPUTEDESK_LLM_PROVIDER','mock')}  screening={'FLAGGED '+str(s['screening']['hits']) if s['screening']['flagged'] else 'clean'}  pii_masked={s.get('pii_masked_count',0)}")

    _hr("tool calls")
    for c in s["tool_calls"]:
        print(f"  {'OK ' if c['ok'] else 'DENY'} {c['tool']}{c['args']}  {c['detail']}")

    _hr("evidence")
    ev = s["evidence"]
    for it in ev["items"]:
        star = "*" if it["kind"] in ev["required"] else " "
        print(f"  {star} {it['kind']:<26} present={it['present']!s:<5} supports={it['supports_merchant']!s:<5} {it['summary'][:90]}")
    if ev["missing_required"]:
        print("  MISSING REQUIRED:", ", ".join(ev["missing_required"]))

    r = s["recommendation"]
    _hr(f"recommendation ({r['source']})")
    print(f"  action={r['action']}  confidence={r['confidence']:.2f}")
    print(f"  {r['rationale']}")
    for c, v in zip(r["citations"], s["verification"]["verdicts"]):
        print(f"  [{'✓' if v['verified'] else '✗'}] {c['passage_id'].split('#')[1]}: “{c['quote'][:100]}”" + (f"  ({v['reason']})" if not v['verified'] else ""))

    g = s["gate"]
    _hr("policy gate")
    print(f"  {g['proposed_action']} -> {g['final_action']}" + ("  (DOWNGRADED)" if g["downgraded"] else ""))
    for reason in g["reasons"]:
        print(f"  - {reason}")

    _hr(f"draft ({s['draft']['source']})")
    print("  " + s["draft"]["body"].replace("\n", "\n  "))

    if not (args.approve or args.reject or args.edit):
        _hr("paused at human review")
        print("  re-run with --approve / --reject / --edit BODY")
        return 0

    kind = "reject" if args.reject else ("edit" if args.edit else "approve")
    decision = ReviewDecision(decision=kind, reviewer=args.reviewer, edited_body=args.edit)
    final = resume_with_decision(thread_id, decision)
    _hr(f"outcome: {final['outcome']}")
    if final.get("receipt"):
        rc = final["receipt"]
        print(f"  filed as {rc['action']}  idempotency_key={rc['idempotency_key'][:16]}…  status={rc['status']}")
    for a in final["audit"]:
        print(f"  audit/{a['node']}: {a['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
