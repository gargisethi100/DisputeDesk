"""app.py — the reviewer's case file. A thin window over the graph: nothing here decides anything.

Layout: case header with the gate's verdict as a stamp; the working record on the left
(evidence, recommendation with cited passages, reads made); the decision on the right
(why the gate ruled as it did, the editable letter, file / reject); the review ledger below.
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from disputedesk import audit
from disputedesk import mock_data as db
from disputedesk.graph import resume_with_decision, run_until_review
from disputedesk.models import ReviewDecision
from disputedesk.tools import TenantViolation
from eval.cases import CASES

load_dotenv()
st.set_page_config(page_title="DisputeDesk", layout="wide", initial_sidebar_state="expanded")
PROVIDER = os.getenv("DISPUTEDESK_LLM_PROVIDER", "mock")

REASON_NAMES = {
    "10.4": "Fraud, card not present", "12.6": "Duplicate processing", "13.1": "Merchandise not received",
    "13.2": "Cancelled recurring charge", "13.3": "Not as described or defective", "13.6": "Credit not processed",
}
EVIDENCE_NAMES = {
    "proof_of_delivery": "Proof of delivery", "order_confirmation": "Order confirmation",
    "avs_cvv_match": "AVS and CVV match", "three_ds_authentication": "3-D Secure authentication",
    "device_signals": "Device signals", "refund_record": "Refund record", "customer_communications": "Customer messages",
    "terms_accepted": "Terms accepted at checkout", "subscription_record": "Subscription record", "duplicate_check": "Duplicate capture check",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600;700&display=swap');
:root{--ground:#F3F5F7;--surface:#FFFFFF;--ink:#16212B;--muted:#4A5763;--rule:#D3DAE1;--accent:#0F5C6E;--accent-deep:#0B4756;
      --filed:#1F6F4A;--held:#9A5B00;--blocked:#A32D2D;
      --tint-accent:#DFEDF0;--tint-filed:#E2F1E8;--tint-held:#FBEFD9;--tint-blocked:#F8E3E3;--tint-grey:#E8ECEF;--mark:#FFF0B8;}
html,body,p,li,td,th,h1,h2,h3,h4,label,input,textarea,button,select,
.stMarkdown,.stCaption,[data-testid="stSidebar"] p,[data-testid="stSidebar"] label,[data-testid="stExpander"] summary p,
[data-testid="stDataFrame"] *:not([class*="material"]){font-family:'Public Sans',system-ui,-apple-system,sans-serif}
[data-testid="stIconMaterial"],.material-symbols-rounded,span[class*="material-symbols"]{font-family:'Material Symbols Rounded' !important}
[data-testid="stAppViewContainer"]{background:var(--ground)}
header[data-testid="stHeader"]{background:transparent}
#MainMenu,footer{visibility:hidden}
.block-container{padding-top:1rem;padding-bottom:4rem;max-width:1240px}
[data-testid="stSidebar"]{background:var(--surface);border-right:1px solid var(--rule)}
[data-testid="stSidebar"] .block-container{padding-top:1.6rem}
p,li,td,th{font-size:16px;line-height:1.55;color:var(--ink)}
.dd-brand{font-size:19px;font-weight:700;letter-spacing:-.01em;margin:0;color:var(--accent)}
.dd-brand-sub{color:var(--muted);font-size:14px;margin:.15rem 0 1.1rem}
.dd-topbar{display:flex;justify-content:space-between;align-items:center;background:var(--accent);color:#fff;
           padding:.75rem 1.2rem;border-radius:6px;margin-bottom:1.4rem}
.dd-topbar .dd-brand{color:#fff}
.dd-topbar .ctx{color:#DCEBEF;font-size:14px}
.chip{display:inline-block;padding:.18rem .6rem;border-radius:999px;font-size:13.5px;font-weight:600;line-height:1.3;white-space:nowrap}
.chip.accent{background:var(--tint-accent);color:var(--accent-deep)}
.chip.filed{background:var(--tint-filed);color:var(--filed)}
.chip.held{background:var(--tint-held);color:var(--held)}
.chip.blocked{background:var(--tint-blocked);color:var(--blocked)}
.chip.grey{background:var(--tint-grey);color:var(--muted)}
.dd-case{display:grid;grid-template-columns:1fr auto;gap:2rem;align-items:start;padding:1.2rem 1.4rem;background:var(--surface);
         border:1px solid var(--rule);border-radius:8px;margin-bottom:.6rem}
.dd-case h1{font-size:30px;font-weight:700;letter-spacing:-.02em;margin:0 0 .35rem;line-height:1.1}
.dd-case .reason{font-size:17px;margin:0 0 .75rem;display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
.dd-case .facts{display:flex;flex-wrap:wrap;gap:.4rem 1.6rem;font-variant-numeric:tabular-nums;font-size:16px}
.dd-case .facts b{font-weight:700;font-size:20px}
.dd-case .facts .late{color:var(--blocked);font-weight:700}
.dd-case .facts .soon{color:var(--held);font-weight:700}
.dd-flags{margin-top:.8rem;display:flex;gap:.5rem;flex-wrap:wrap}
.stamp{display:inline-block;border:3px double var(--c);color:var(--c);padding:.6rem 1.2rem .55rem;border-radius:6px;
       font-weight:700;font-size:22px;letter-spacing:.14em;line-height:1;text-align:center;min-width:12rem;
       transform:rotate(-2deg);margin-top:.3rem;background:var(--t)}
.stamp small{display:block;font-weight:500;font-size:12px;letter-spacing:.02em;margin-top:.45rem;text-transform:none}
.stamp.filed{--c:var(--filed);--t:var(--tint-filed)} .stamp.held{--c:var(--held);--t:var(--tint-held)}
.stamp.blocked{--c:var(--blocked);--t:var(--tint-blocked)} .stamp.accent{--c:var(--accent);--t:var(--tint-accent)}
h2.dd{font-size:19px;font-weight:700;letter-spacing:-.01em;margin:1.6rem 0 .7rem;padding:0 0 .35rem;position:relative}
h2.dd:after{content:"";position:absolute;left:0;bottom:0;width:2.4rem;height:3px;background:var(--accent);border-radius:2px}
h2.dd span{color:var(--muted);font-weight:400;font-size:15px;margin-left:.5rem}
table.ev{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--rule);border-radius:8px;overflow:hidden}
table.ev th{text-align:left;font-weight:600;color:var(--muted);font-size:13.5px;padding:.6rem .8rem;background:var(--tint-grey);border-bottom:1px solid var(--rule)}
table.ev td{padding:.65rem .8rem;border-bottom:1px solid #E7EBEF;vertical-align:top;font-size:15px}
table.ev tr:last-child td{border-bottom:none}
table.ev td.name{white-space:nowrap;font-weight:600}
table.ev td.detail{color:var(--ink)}
table.ev .req{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;background:var(--accent);margin-right:.55rem;vertical-align:middle}
table.ev .opt{display:inline-block;width:.55rem;height:.55rem;border-radius:50%;border:1.5px solid var(--accent);margin-right:.55rem;vertical-align:middle}
.legend{font-size:13.5px;color:var(--muted);margin:.5rem 0 0}
.missing{color:var(--blocked);font-weight:700;margin:.7rem 0 0}
.rec{background:var(--surface);border:1px solid var(--rule);border-left:5px solid var(--accent);border-radius:8px;padding:1rem 1.2rem;margin:.3rem 0 .9rem}
.rec .head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.45rem}
.rec .action{font-weight:700;font-size:18px;color:var(--accent-deep)}
.rec .conf{color:var(--muted);font-variant-numeric:tabular-nums}
.rec p{margin:0}
.cite{border:1px solid var(--rule);border-left:5px solid var(--accent);border-radius:8px;padding:.7rem 1rem;margin:.6rem 0;background:var(--surface);font-size:15px;line-height:1.55}
.cite .src{color:var(--muted);font-size:13.5px;margin-bottom:.3rem}
.cite .src b{color:var(--ink);font-weight:600}
.cite.bad{border-left-color:var(--blocked)}
.cite mark{background:var(--mark);color:var(--ink);padding:0 .15em;border-radius:3px}
.why{border-radius:8px;padding:1rem 1.2rem;margin:.3rem 0 1rem;background:var(--t);border:1px solid var(--c)}
.why.filed{--c:var(--filed);--t:var(--tint-filed)} .why.held{--c:var(--held);--t:var(--tint-held)}
.why .lead{font-weight:700;margin:0 0 .4rem}
.why ul{margin:0;padding-left:1.1rem} .why li{margin:.2rem 0}
.letter{background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:1.3rem 1.5rem;white-space:pre-wrap;line-height:1.65;font-size:15px}
.receipt{background:var(--tint-filed);border:1px solid var(--filed);border-radius:8px;padding:1rem 1.2rem}
.receipt .k{color:var(--muted);font-size:13.5px}
.receipt code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}
.denied{background:var(--tint-blocked);border:1px solid var(--blocked);border-radius:8px;padding:1.1rem 1.3rem;max-width:44rem}
.denied h3{margin:0 0 .4rem;font-size:19px;font-weight:700;color:var(--blocked)}
.queue td.amt{text-align:right;font-variant-numeric:tabular-nums}
.stButton>button{border-radius:6px;font-weight:600;padding:.55rem 1rem}
.stButton>button[kind="secondary"]{border:1.5px solid var(--accent);color:var(--accent-deep)}
.stTextArea textarea{font-family:'Public Sans',system-ui,sans-serif;font-size:15px;line-height:1.55;border-radius:8px}
[data-testid="stExpander"] details{border-radius:8px;background:var(--surface)}
@media (prefers-reduced-motion: reduce){.stamp{transform:none}}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def esc(s) -> str:
    return html.escape(str(s))


def money(paise: int, cur: str) -> str:
    return f"{'₹' if cur == 'INR' else cur + ' '}{paise / 100:,.2f}"


def days_left(respond_by: str) -> tuple[str, str]:
    d = (datetime.fromisoformat(respond_by) - db.NOW).total_seconds() / 86400
    if d < 0:
        return f"{abs(int(d))} day{'s' if abs(int(d)) != 1 else ''} past the deadline", "late"
    if d < 1:
        return "less than a day left", "soon"
    return f"{int(d)} days left", ""


def highlight(text: str, quote: str) -> str:
    safe = esc(text)
    if quote:
        pat = re.compile(r"\s+".join(re.escape(w) for w in esc(quote).split()), re.I)
        safe = pat.sub(lambda m: f"<mark>{m.group(0)}</mark>", safe, count=1)
    return safe


def stamp(final: str, proposed: str, downgraded: bool) -> str:
    if final == "escalate":
        return f"<div class='stamp held'>ESCALATE<small>{'gate overrode ' + proposed if downgraded else 'model and gate agree'}</small></div>"
    cls = "filed" if final == "contest" else "accent"
    return f"<div class='stamp {cls}'>{final.upper()}<small>model and gate agree</small></div>"


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("<p class='dd-brand'>DisputeDesk</p><p class='dd-brand-sub'>Chargeback responses, reviewed before anything is filed.</p>", unsafe_allow_html=True)
    merchant_id = st.selectbox("Acting for merchant", list(db.MERCHANTS), format_func=lambda m: f"{db.MERCHANTS[m].name} ({m})")
    dispute_id = st.selectbox("Case", list(db.DISPUTES))
    reviewer = st.text_input("Reviewer", os.getenv("DISPUTEDESK_REVIEWER", "analyst@example.com"))
    if st.button("Open case", type="primary", width="stretch"):
        st.session_state.pop("final", None)
        try:
            thread_id, state = run_until_review(dispute_id, merchant_id)
            st.session_state.update(thread_id=thread_id, state=state, denied=None)
        except TenantViolation as e:
            st.session_state.update(thread_id=None, state=None, denied=str(e))

# deep link: ?case=DSP009&merchant=MER001 opens a case on load (handy for demos and bookmarks)
qp_case = st.query_params.get("case")
if qp_case and "state" not in st.session_state and "denied" not in st.session_state and qp_case in db.DISPUTES:
    qp_merchant = st.query_params.get("merchant", merchant_id)
    try:
        thread_id, state = run_until_review(qp_case, qp_merchant)
        st.session_state.update(thread_id=thread_id, state=state, denied=None)
        merchant_id = qp_merchant
    except TenantViolation as e:
        st.session_state.update(thread_id=None, state=None, denied=str(e))

merchant_name = db.MERCHANTS[merchant_id].name
st.markdown(f"<div class='dd-topbar'><span class='dd-brand'>DisputeDesk</span><span class='ctx'>{esc(merchant_name)}, reviewer {esc(reviewer)}</span></div>", unsafe_allow_html=True)

# ------------------------------------------------------------------ denied
if st.session_state.get("denied"):
    st.markdown(
        f"<div class='denied'><h3>This case belongs to another merchant</h3>"
        f"<p>{esc(st.session_state['denied'])}</p>"
        f"<p>The tools are bound to {esc(merchant_name)} when they are created, so a record from another merchant is refused before "
        f"anything is read. The refusal is written to the audit log. Switch merchant in the sidebar to open it legitimately.</p></div>",
        unsafe_allow_html=True)
    st.stop()

# ------------------------------------------------------------------ empty state: the queue
s = st.session_state.get("state")
if not s:
    st.markdown("<h2 class='dd' style='margin-top:.2rem'>Cases waiting for review</h2>"
                "<p style='margin:0 0 .9rem'>Select a case in the sidebar to open it.</p>", unsafe_allow_html=True)
    rows = []
    for c in CASES:
        d = db.DISPUTES[c["dispute_id"]]
        left, _ = days_left(d.respond_by.isoformat())
        rows.append(f"<tr><td class='name'>{d.dispute_id}</td><td>{db.MERCHANTS[d.merchant_id].name}</td>"
                    f"<td>{REASON_NAMES[d.reason_code.value]} <span class='chip accent'>{d.reason_code.value}</span></td><td class='amt'>{money(d.amount_paise, d.currency)}</td>"
                    f"<td>{d.respond_by:%d %b}, {left}</td><td class='detail'>{esc(c['note'])}</td></tr>")
    st.markdown("<table class='ev queue'><tr><th>Case</th><th>Merchant</th><th>Reason</th><th style='text-align:right'>Amount</th><th>Respond by</th><th>What this case shows</th></tr>"
                + "".join(rows) + "</table>", unsafe_allow_html=True)
    st.stop()

# ------------------------------------------------------------------ case header
d, g, r, ev, scr = s["dispute"], s["gate"], s["recommendation"], s["evidence"], s["screening"]
left_txt, left_cls = days_left(d["respond_by"])
n_pii = s.get("pii_masked_count", 0)
flags = (f"<span class='chip {'blocked' if scr['flagged'] else 'filed'}'>Screening: {'flagged, ' + ', '.join(scr['hits']) if scr['flagged'] else 'clean'}</span>"
         f"<span class='chip accent'>Masked before the model: {n_pii} detail{'s' if n_pii != 1 else ''}</span>")
st.markdown(
    f"<div class='dd-case'><div>"
    f"<h1>Case {esc(d['dispute_id'])}</h1>"
    f"<p class='reason'>{REASON_NAMES[d['reason_code']]}<span class='chip accent'>reason code {d['reason_code']}</span></p>"
    f"<div class='facts'><span><b>{money(d['amount_paise'], d['currency'])}</b></span><span>card ending {d['card_last4']}</span>"
    f"<span>respond by {datetime.fromisoformat(d['respond_by']):%d %b %Y}, <span class='{left_cls}'>{left_txt}</span></span></div>"
    f"<div class='dd-flags'>{flags}</div>"
    f"</div><div>{stamp(g['final_action'], g['proposed_action'], g['downgraded'])}</div></div>",
    unsafe_allow_html=True)

col_l, col_r = st.columns([7, 5], gap="large")

# ------------------------------------------------------------------ left: the record
with col_l:
    st.markdown(f"<h2 class='dd'>Evidence for {d['reason_code']}</h2>", unsafe_allow_html=True)
    rows = []
    for it in ev["items"]:
        req = it["kind"] in ev["required"]
        held = "<span class='chip filed'>held</span>" if it["present"] else "<span class='chip blocked'>missing</span>"
        sup = ("<span class='chip filed'>yes</span>" if it["supports_merchant"] else
               "<span class='chip blocked'>no</span>" if it["supports_merchant"] is False else "<span class='chip grey'>n/a</span>")
        rows.append(f"<tr><td class='name'><span class='{'req' if req else 'opt'}'></span>{EVIDENCE_NAMES.get(it['kind'], it['kind'])}</td>"
                    f"<td>{held}</td><td>{sup}</td><td class='detail'>{esc(it['summary'])}</td></tr>")
    st.markdown("<table class='ev'><tr><th>Item</th><th>Status</th><th>Helps merchant</th><th>Detail</th></tr>" + "".join(rows) + "</table>"
                "<p class='legend'>Filled dot: required for this reason code. Hollow: supporting. Details are shown to you unmasked; the model saw placeholders.</p>",
                unsafe_allow_html=True)
    if ev["missing_required"]:
        st.markdown("<p class='missing'>Missing required evidence: " + ", ".join(EVIDENCE_NAMES.get(k, k) for k in ev["missing_required"]) + "</p>", unsafe_allow_html=True)

    src = "the model" if r["source"] == "llm" else "the rule-based fallback"
    st.markdown(f"<h2 class='dd'>Recommendation<span>from {src}</span></h2>", unsafe_allow_html=True)
    st.markdown(f"<div class='rec'><div class='head'><span class='action'>{r['action'].capitalize()}</span>"
                f"<span class='conf'>confidence {r['confidence']:.2f}</span></div><p>{esc(r['rationale'])}</p></div>", unsafe_allow_html=True)
    by_id = {p["passage_id"]: p for p in s["passages"]}
    for cit, v in zip(r["citations"], s["verification"]["verdicts"]):
        p = by_id.get(cit["passage_id"])
        status = "<span class='chip filed'>quoted verbatim</span>" if v["verified"] else f"<span class='chip blocked'>not verified</span> {esc(v['reason'])}"
        body = highlight(p["text"], cit["quote"]) if p else esc(cit["quote"])
        st.markdown(f"<div class='cite {'bad' if not v['verified'] else ''}'><div class='src'>Cites <b>{esc(p['heading'] if p else cit['passage_id'])}</b>, {status}</div>{body}</div>",
                    unsafe_allow_html=True)

    denials = [c for c in s["tool_calls"] if not c["ok"]]
    with st.expander(f"Reads made: {len(s['tool_calls'])}" + (f", {len(denials)} refused" if denials else ", none refused")):
        st.table([{"": "ok" if c["ok"] else "refused", "tool": c["tool"], "arguments": ", ".join(f"{k}={v}" for k, v in c["args"].items()), "result": c["detail"]} for c in s["tool_calls"]])
    with st.expander(f"Passages retrieved: {len(s['passages'])}"):
        for p in s["passages"]:
            st.markdown(f"**{esc(p['heading'])}**  \n{esc(p['text'])}")

# ------------------------------------------------------------------ right: the decision
with col_r:
    st.markdown("<h2 class='dd'>Decision</h2>", unsafe_allow_html=True)
    if g["final_action"] == "escalate":
        lead = f"The gate overrode the model's <b>{g['proposed_action']}</b> and sent this to you because:" if g["downgraded"] else "Both the model and the gate say a person should decide this:"
        st.markdown(f"<div class='why held'><p class='lead'>{lead}</p><ul>" + "".join(f"<li>{esc(x)}</li>" for x in g["reasons"]) + "</ul></div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='why filed'><p class='lead'>No gate rule fired. The model's <b>{g['final_action']}</b> stands, pending your approval.</p>"
                    f"<ul><li>deadline not passed</li><li>required evidence present</li><li>confidence above the floor</li><li>every citation verified verbatim</li><li>customer message clean</li></ul></div>",
                    unsafe_allow_html=True)

    final = st.session_state.get("final")
    if final:
        if final.get("receipt"):
            rc = final["receipt"]
            st.markdown(f"<div class='receipt'><p class='lead' style='margin:0 0 .3rem;font-weight:600'>Filed as {rc['action']}</p>"
                        f"<p class='k'>Filed once. A repeat with the same approval returns the same receipt.</p>"
                        f"<p class='k'>Idempotency key <code>{rc['idempotency_key']}</code></p></div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='why held'><p class='lead'>Rejected. Nothing was filed; the rejection is in the ledger.</p></div>", unsafe_allow_html=True)
        st.markdown("<h2 class='dd'>Letter as filed</h2>" if final.get("receipt") else "<h2 class='dd'>Draft, not filed</h2>", unsafe_allow_html=True)
        st.markdown(f"<div class='letter'>{esc(final['final_body'])}</div>", unsafe_allow_html=True)
    else:
        draft_src = "written by the model" if s["draft"]["source"] == "llm" else "from the template"
        st.markdown(f"<h2 class='dd'>Response letter<span>{draft_src}</span></h2>", unsafe_allow_html=True)
        body = st.text_area("Response letter", s["draft"]["body"], height=300, label_visibility="collapsed")
        escalated = g["final_action"] == "escalate"
        if escalated:
            st.markdown("<p class='legend'>Escalated cases cannot be filed from here. Reject to close it, or resolve the reasons above and open the case again.</p>", unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3)
        decision = None
        if b1.button("Approve and file", type="primary", width="stretch", disabled=escalated):
            decision = ReviewDecision(decision="approve", reviewer=reviewer)
        if b2.button("File with my edits", width="stretch", disabled=escalated):
            decision = ReviewDecision(decision="edit", reviewer=reviewer, edited_body=body)
        if b3.button("Reject, file nothing", width="stretch"):
            decision = ReviewDecision(decision="reject", reviewer=reviewer)
        if decision:
            st.session_state["final"] = resume_with_decision(st.session_state["thread_id"], decision)
            st.rerun()

# ------------------------------------------------------------------ ledger
st.markdown("<h2 class='dd' style='margin-top:2rem'>Review ledger<span>every completed review, newest last</span></h2>", unsafe_allow_html=True)
recs = audit.read_review_records(20)
if recs:
    st.dataframe([{"when": rec.get("written_at", "")[:19].replace("T", " "), "case": rec.get("dispute_id"), "merchant": rec.get("merchant_id"),
                   "reviewer": rec.get("reviewer"), "decision": rec.get("decision"), "model proposed": rec.get("proposed_action"),
                   "gate ruled": rec.get("final_action"), "outcome": rec.get("outcome"), "details masked": rec.get("pii_masked_count"),
                   "reads refused": len(rec.get("denials", []))} for rec in recs], width="stretch", hide_index=True)
else:
    st.markdown("<p class='legend'>No reviews completed yet in this session.</p>", unsafe_allow_html=True)
with st.expander("What happened in this run, step by step"):
    for a_ in s["audit"]:
        st.markdown(f"**{a_['node']}** {esc(a_['message'])}" + (f"  \n<span class='legend'>{esc(a_['data'])}</span>" if a_["data"] else ""), unsafe_allow_html=True)
