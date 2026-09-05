"""app.py — Streamlit reviewer UI. A thin wrapper over the graph: nothing here decides anything.

The UI shows the reviewer exactly what the audit log records: what was read, what the model
proposed, what the gate did and why, the cited passages with the verbatim quote highlighted,
and an editable draft. Approve / edit / reject resumes the paused graph.
"""
from __future__ import annotations

import html
import os
import re

import streamlit as st
from dotenv import load_dotenv

from disputedesk import audit
from disputedesk import mock_data as db
from disputedesk.graph import resume_with_decision, run_until_review
from disputedesk.models import ReviewDecision
from disputedesk.tools import TenantViolation

load_dotenv()
st.set_page_config(page_title="DisputeDesk", page_icon="⚖️", layout="wide")

PROVIDER = os.getenv("DISPUTEDESK_LLM_PROVIDER", "mock")


def _highlight(text: str, quote: str) -> str:
    """Return HTML with `quote` marked inside `text` (whitespace-insensitive match)."""
    safe = html.escape(text)
    if quote:
        pat = re.compile(r"\s+".join(re.escape(w) for w in html.escape(quote).split()), re.I)
        safe = pat.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe, count=1)
    return f"<div style='white-space:pre-wrap;font-size:0.9rem'>{safe}</div>"


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.title("⚖️ DisputeDesk")
    st.caption("LLM proposes · policy gate disposes · human approves · one gated write")
    merchant_id = st.selectbox("Acting as merchant", list(db.MERCHANTS), format_func=lambda m: f"{m} — {db.MERCHANTS[m].name}")
    dispute_id = st.selectbox("Dispute", list(db.DISPUTES))
    reviewer = st.text_input("Reviewer", os.getenv("DISPUTEDESK_REVIEWER", "analyst@example.com"))
    st.caption(f"provider: `{PROVIDER}` · clock frozen at {db.NOW.date()}")
    if st.button("Run dispute", type="primary", width="stretch"):
        st.session_state.pop("final", None)
        try:
            thread_id, state = run_until_review(dispute_id, merchant_id)
            st.session_state.update(thread_id=thread_id, state=state, denied=None)
        except TenantViolation as e:
            st.session_state.update(thread_id=None, state=None, denied=str(e))

# ------------------------------------------------------------------ main
if st.session_state.get("denied"):
    st.error(f"**Denied at the tool layer.** {st.session_state['denied']}")
    st.info("The toolbox is bound to one merchant at construction. A record belonging to another merchant "
            "raises `TenantViolation` before the agent can read it — this attempt is in the audit log as a denial.")
    st.stop()

s = st.session_state.get("state")
if not s:
    st.markdown("### Pick a dispute and press **Run dispute**")
    st.markdown("Try **DSP001** (approve path), **DSP008** (gate overrides a correct model on deadline), "
                "**DSP009** (prompt injection flagged, gate holds), **DSP010** (unreachable from MER001).")
    st.stop()

d, g, r, ev = s["dispute"], s["gate"], s["recommendation"], s["evidence"]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Dispute", d["dispute_id"], d["reason_code"])
c2.metric("Amount", f"{d['amount_paise']/100:,.2f} {d['currency']}", f"card •••• {d['card_last4']}")
c3.metric("Respond by", d["respond_by"][:10])
c4.metric("PII masked before prompt", s.get("pii_masked_count", 0))
c5.metric("Injection screen", "FLAGGED" if s["screening"]["flagged"] else "clean", ", ".join(s["screening"]["hits"]) or None)

# gate banner
if g["final_action"] == "escalate":
    st.warning(f"**Gate: {g['proposed_action']} → escalate**" + ("  (DOWNGRADED)" if g["downgraded"] else "") +
               "\n\n" + "\n".join(f"- {x}" for x in g["reasons"]))
else:
    st.success(f"**Gate: {g['proposed_action']} → {g['final_action']}** — no rule fired; the model's proposal stands")

tab_ev, tab_tools, tab_cite, tab_draft, tab_audit = st.tabs(["Evidence", "Tool calls", "Policy & citations", "Draft & decide", "Audit log"])

with tab_ev:
    st.caption("Fixed evidence plan for this reason code. `*` = required. Summaries shown here are PII-restored; the model saw the masked versions.")
    for it in ev["items"]:
        star = "★" if it["kind"] in ev["required"] else "○"
        icon = "✅" if it["supports_merchant"] else ("❌" if it["supports_merchant"] is False else "⚪")
        st.markdown(f"{star} **{it['kind']}** {icon} present=`{it['present']}` supports_merchant=`{it['supports_merchant']}`  \n{it['summary']}")
    if ev["missing_required"]:
        st.error("Missing required evidence: " + ", ".join(ev["missing_required"]))

with tab_tools:
    st.caption("Every read the agent made, in order. Denials appear here too.")
    st.table([{"ok": "✅" if c["ok"] else "⛔", "tool": c["tool"], "args": str(c["args"]), "detail": c["detail"]} for c in s["tool_calls"]])

with tab_cite:
    st.markdown(f"**Recommendation ({r['source']})** — `{r['action']}` at confidence `{r['confidence']:.2f}`")
    st.write(r["rationale"])
    by_id = {p["passage_id"]: p for p in s["passages"]}
    for cit, v in zip(r["citations"], s["verification"]["verdicts"]):
        p = by_id.get(cit["passage_id"])
        st.markdown(f"{'✅ verified verbatim' if v['verified'] else '❌ ' + v['reason']} — **{p['heading'] if p else cit['passage_id']}**")
        if p:
            st.markdown(_highlight(p["text"], cit["quote"]), unsafe_allow_html=True)
    with st.expander("All retrieved passages"):
        for p in s["passages"]:
            st.markdown(f"**{p['heading']}** `{p['passage_id']}`")
            st.write(p["text"])

with tab_draft:
    final = st.session_state.get("final")
    if final:
        st.success(f"Outcome: **{final['outcome']}**")
        if final.get("receipt"):
            rc = final["receipt"]
            st.code(f"filed as {rc['action']}\nidempotency_key {rc['idempotency_key']}\nstatus {rc['status']}")
        st.text(final["final_body"])
    else:
        st.caption(f"Draft source: `{s['draft']['source']}`. Edit freely — an edited body mints a token over the edited text.")
        body = st.text_area("Response body", s["draft"]["body"], height=260)
        a, b, c = st.columns(3)
        decision = None
        if a.button("✅ Approve", width="stretch", disabled=g["final_action"] == "escalate"):
            decision = ReviewDecision(decision="approve", reviewer=reviewer)
        if b.button("✏️ Approve with edits", width="stretch", disabled=g["final_action"] == "escalate"):
            decision = ReviewDecision(decision="edit", reviewer=reviewer, edited_body=body)
        if c.button("⛔ Reject", width="stretch"):
            decision = ReviewDecision(decision="reject", reviewer=reviewer)
        if g["final_action"] == "escalate":
            st.info("Escalated cases cannot be approved from here: nothing is filed. Reject to close, or resolve the gate reasons upstream.")
        if decision:
            st.session_state["final"] = resume_with_decision(st.session_state["thread_id"], decision)
            st.rerun()

with tab_audit:
    st.caption("Per-node log for this run, then the persisted JSONL of completed reviews.")
    for a_ in s["audit"]:
        st.markdown(f"`{a_['node']}` {a_['message']}" + (f"  \n<small>{html.escape(str(a_['data']))}</small>" if a_["data"] else ""), unsafe_allow_html=True)
    recs = audit.read_review_records(20)
    if recs:
        st.dataframe([{k: rec.get(k) for k in ("written_at", "dispute_id", "merchant_id", "reviewer", "decision",
                                               "proposed_action", "final_action", "outcome", "pii_masked_count")} for rec in recs],
                     width="stretch")
