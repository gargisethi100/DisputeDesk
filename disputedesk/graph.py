"""graph.py — the LangGraph workflow. Nodes are thin: each calls one module and stores
Pydantic `model_dump()` dicts in state.

  load_dispute -> gather_evidence -> retrieve_policy -> recommend -> verify_citations
  -> policy_gate -> draft_response -> [INTERRUPT: human review] -> submit

`interrupt_before=["submit"]` is a property of the compiled graph, not an if-statement.
Every run pauses. `resume_with_decision` injects the ReviewDecision and continues; the
submit node is the only place `actions.submit_dispute_response` is called.
"""
from __future__ import annotations

import operator
import uuid
from datetime import datetime
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from . import actions, audit
from .analysis import draft_response, make_redactor, recommend
from .llm import get_provider
from .mock_data import NOW
from .models import (
    Dispute, DraftResponse, EvidenceBundle, GateDecision, Passage, Recommendation,
    ReviewDecision, ScreeningResult, VerificationResult,
)
from .policy import gather_evidence, policy_gate
from .retrieval import Retriever, query_for
from .screening import screen
from .tools import Toolbox
from .verifier import verify_citations


class DisputeState(TypedDict, total=False):
    dispute_id: str
    merchant_id: str
    now: str                                  # ISO; the frozen clock, never datetime.now()
    dispute: dict
    screening: dict
    evidence: dict
    passages: list[dict]
    recommendation: dict
    verification: dict
    gate: dict
    draft: dict
    pii_masked_count: int
    tool_calls: Annotated[list[dict], operator.add]
    audit: Annotated[list[dict], operator.add]
    decision: dict                            # ReviewDecision, injected at the interrupt
    final_body: str
    token: dict
    receipt: dict
    outcome: str                              # submitted | rejected | duplicate_suppressed


_RETRIEVER: Retriever | None = None


def _retriever() -> Retriever:
    global _RETRIEVER
    if _RETRIEVER is None:
        _RETRIEVER = Retriever()
    return _RETRIEVER


def _now(state: DisputeState) -> datetime:
    return datetime.fromisoformat(state["now"])


def _calls(tb: Toolbox) -> list[dict]:
    return [c.model_dump(mode="json") for c in tb.calls]


def _log(node: str, message: str, **data) -> list[dict]:
    return [{"node": node, "message": message, "data": data}]


# --------------------------------------------------------------------------- nodes
def load_dispute(state: DisputeState) -> DisputeState:
    tb = Toolbox(state["merchant_id"])
    d = tb.get_dispute(state["dispute_id"])         # TenantViolation propagates to the caller
    s = screen(d.customer_message)
    return {"dispute": d.model_dump(mode="json"), "screening": s.model_dump(mode="json"), "tool_calls": _calls(tb),
            "audit": _log("load_dispute", f"{d.reason_code.value} loaded; screening flagged={s.flagged}", hits=s.hits)}


def gather_evidence_node(state: DisputeState) -> DisputeState:
    tb = Toolbox(state["merchant_id"])
    d = Dispute(**state["dispute"])
    b = gather_evidence(tb, d)
    return {"evidence": b.model_dump(mode="json"), "tool_calls": _calls(tb),
            "audit": _log("gather_evidence", f"{len(b.items)} items, missing_required={[k.value for k in b.missing_required]}")}


def retrieve_policy(state: DisputeState) -> DisputeState:
    d = Dispute(**state["dispute"])
    hits = _retriever().search(query_for(d.reason_code), k=4)
    return {"passages": [p.model_dump(mode="json") for p in hits],
            "audit": _log("retrieve_policy", "retrieved " + ", ".join(p.passage_id.split("#")[1] for p in hits))}


def recommend_node(state: DisputeState) -> DisputeState:
    tb = Toolbox(state["merchant_id"])
    d = Dispute(**state["dispute"])
    order = tb.get_order(tb.get_transaction(d.transaction_id).order_id)
    redactor = make_redactor(order)
    rec = recommend(get_provider(), d, EvidenceBundle(**state["evidence"]),
                    [Passage(**p) for p in state["passages"]], redactor, _now(state))
    return {"recommendation": rec.model_dump(mode="json"), "pii_masked_count": redactor.masked_count, "tool_calls": _calls(tb),
            "audit": _log("recommend", f"{rec.source} proposed {rec.action} ({rec.confidence:.2f}), "
                          f"{len(rec.citations)} citation(s), {redactor.masked_count} PII values masked")}


def verify_citations_node(state: DisputeState) -> DisputeState:
    rec = Recommendation(**state["recommendation"])
    v = verify_citations(rec.citations, [Passage(**p) for p in state["passages"]])
    return {"verification": v.model_dump(mode="json"),
            "audit": _log("verify_citations", f"all_verified={v.all_verified}",
                          failed=[x.citation.quote[:50] for x in v.verdicts if not x.verified])}


def policy_gate_node(state: DisputeState) -> DisputeState:
    g = policy_gate(Recommendation(**state["recommendation"]), EvidenceBundle(**state["evidence"]),
                    Dispute(**state["dispute"]), _now(state), VerificationResult(**state["verification"]),
                    ScreeningResult(**state["screening"]))
    return {"gate": g.model_dump(mode="json"),
            "audit": _log("policy_gate", f"{g.proposed_action} -> {g.final_action}" + (" (DOWNGRADED)" if g.downgraded else ""),
                          reasons=g.reasons)}


def draft_response_node(state: DisputeState) -> DisputeState:
    tb = Toolbox(state["merchant_id"])
    d = Dispute(**state["dispute"])
    order = tb.get_order(tb.get_transaction(d.transaction_id).order_id)
    draft = draft_response(get_provider(), d, EvidenceBundle(**state["evidence"]), GateDecision(**state["gate"]),
                           Recommendation(**state["recommendation"]), make_redactor(order))
    return {"draft": draft.model_dump(mode="json"), "tool_calls": _calls(tb),
            "audit": _log("draft_response", f"{draft.source} draft, {len(draft.body)} chars")}


def submit(state: DisputeState) -> DisputeState:
    """Runs only after the human interrupt. The single place the write can happen."""
    decision = ReviewDecision(**state["decision"])
    gate = GateDecision(**state["gate"])
    draft = DraftResponse(**state["draft"])
    now = _now(state)
    body = decision.edited_body if (decision.decision == "edit" and decision.edited_body) else draft.body

    record = {
        "dispute_id": state["dispute_id"], "merchant_id": state["merchant_id"], "reviewer": decision.reviewer,
        "decision": decision.decision, "proposed_action": gate.proposed_action, "final_action": gate.final_action,
        "gate_reasons": gate.reasons, "screening_hits": state["screening"]["hits"],
        "pii_masked_count": state.get("pii_masked_count", 0),
        "tool_calls": state["tool_calls"], "denials": [c for c in state["tool_calls"] if not c["ok"]],
        "model_source": state["recommendation"]["source"], "citations_verified": state["verification"]["all_verified"],
    }

    if decision.decision == "reject":
        audit.write_review_record({**record, "outcome": "rejected"})
        return {"outcome": "rejected", "final_body": body,
                "audit": _log("submit", "rejected by reviewer — nothing filed", reviewer=decision.reviewer)}

    token = actions.mint_token(decision, state["dispute_id"], body, now)
    receipt = actions.submit_dispute_response(token, state["dispute_id"], gate.final_action, body, now)
    audit.write_review_record({**record, "outcome": receipt.status, "idempotency_key": receipt.idempotency_key})
    return {"token": token.model_dump(mode="json"), "receipt": receipt.model_dump(mode="json"), "final_body": body, "outcome": receipt.status,
            "audit": _log("submit", f"{receipt.status} as {gate.final_action}", idempotency_key=receipt.idempotency_key[:12])}


# --------------------------------------------------------------------------- build
def build_graph():
    g = StateGraph(DisputeState)
    g.add_node("load_dispute", load_dispute)
    g.add_node("gather_evidence", gather_evidence_node)
    g.add_node("retrieve_policy", retrieve_policy)
    g.add_node("recommend", recommend_node)
    g.add_node("verify_citations", verify_citations_node)
    g.add_node("policy_gate", policy_gate_node)
    g.add_node("draft_response", draft_response_node)
    g.add_node("submit", submit)
    g.add_edge(START, "load_dispute")
    g.add_edge("load_dispute", "gather_evidence")
    g.add_edge("gather_evidence", "retrieve_policy")
    g.add_edge("retrieve_policy", "recommend")
    g.add_edge("recommend", "verify_citations")
    g.add_edge("verify_citations", "policy_gate")
    g.add_edge("policy_gate", "draft_response")
    g.add_edge("draft_response", "submit")
    g.add_edge("submit", END)
    return g.compile(checkpointer=MemorySaver(), interrupt_before=["submit"])   # the human pause


GRAPH = build_graph()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def run_until_review(dispute_id: str, merchant_id: str, now: datetime = NOW) -> tuple[str, DisputeState]:
    thread_id = str(uuid.uuid4())
    state = GRAPH.invoke({"dispute_id": dispute_id, "merchant_id": merchant_id, "now": now.isoformat(),
                          "tool_calls": [], "audit": []}, _config(thread_id))
    return thread_id, state


def resume_with_decision(thread_id: str, decision: ReviewDecision) -> DisputeState:
    GRAPH.update_state(_config(thread_id), {"decision": decision.model_dump(mode="json")})
    return GRAPH.invoke(None, _config(thread_id))
