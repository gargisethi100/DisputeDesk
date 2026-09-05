"""policy.py — evidence plan per reason code, evidence gathering, and the policy gate.

Two deterministic pieces:

  EVIDENCE_PLAN / gather_evidence
      Which evidence is admissible depends on the reason code, not on judgement.
      13.1 is won with proof of delivery; 10.4 with AVS/CVV + device signals. Submitting
      the wrong evidence loses automatically. So the plan is a lookup table and the agent
      follows it — the model does NOT choose tools. (Stated limitation; next step is
      LLM tool-planning constrained to the same read-only toolbox.)

  policy_gate
      The LLM proposes; this function disposes. It may only move the action toward
      `escalate` — the one action that is not an irreversible commitment. It can never
      turn accept into contest, or escalate into either. Every rule that fires is
      recorded as a reason so the reviewer sees exactly why the model was overridden.

This module never imports or calls an LLM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, NamedTuple

from .models import (
    Dispute, EvidenceBundle, EvidenceItem, EvidenceKind, GateDecision, Order,
    ReasonCode, Recommendation, ScreeningResult, Transaction, VerificationResult,
)
from .tools import Toolbox

CONFIDENCE_FLOOR = 0.70          # below this, a commitment needs a human
DEADLINE_BUFFER_HOURS = 24       # too close to the deadline to safely file


class Plan(NamedTuple):
    required: list[EvidenceKind]
    optional: list[EvidenceKind]


EVIDENCE_PLAN: dict[ReasonCode, Plan] = {
    ReasonCode.NOT_RECEIVED: Plan(
        required=[EvidenceKind.PROOF_OF_DELIVERY, EvidenceKind.ORDER_CONFIRMATION],
        optional=[EvidenceKind.CUSTOMER_COMMS]),
    ReasonCode.FRAUD_CNP: Plan(
        required=[EvidenceKind.AVS_CVV_MATCH, EvidenceKind.ORDER_CONFIRMATION],
        optional=[EvidenceKind.THREE_DS, EvidenceKind.DEVICE_SIGNALS, EvidenceKind.PROOF_OF_DELIVERY]),
    ReasonCode.NOT_AS_DESCRIBED: Plan(
        required=[EvidenceKind.ORDER_CONFIRMATION, EvidenceKind.CUSTOMER_COMMS],
        optional=[EvidenceKind.PROOF_OF_DELIVERY, EvidenceKind.TERMS_ACCEPTED]),
    ReasonCode.DUPLICATE: Plan(
        required=[EvidenceKind.DUPLICATE_CHECK],
        optional=[EvidenceKind.ORDER_CONFIRMATION]),
    ReasonCode.CREDIT_NOT_PROCESSED: Plan(
        required=[EvidenceKind.REFUND_RECORD],
        optional=[EvidenceKind.CUSTOMER_COMMS]),
    ReasonCode.RECURRING_CANCELLED: Plan(
        required=[EvidenceKind.SUBSCRIPTION_RECORD, EvidenceKind.TERMS_ACCEPTED],
        optional=[EvidenceKind.CUSTOMER_COMMS]),
}


# --------------------------------------------------------------------------- #
# Evidence collectors — one per kind. Each returns an EvidenceItem with:
#   present          do we hold a record of this kind at all?
#   supports_merchant if present, does it help the merchant's case?
# The distinction matters: a refund record that EXISTS helps a 13.6 contest; a
# subscription record that shows the charge came AFTER cancellation hurts a 13.2 one.
# --------------------------------------------------------------------------- #
Collector = Callable[[Toolbox, Dispute, Transaction, Order], EvidenceItem]


def _order_confirmation(tb, d, txn, order) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.ORDER_CONFIRMATION, present=True, supports_merchant=True,
        summary=f"Order {order.order_id} placed {order.placed_at.date()} for {', '.join(order.items)}; "
                f"ship-to {order.shipping_address}; card ending {txn.card_last4}",
        source_tool="get_order")


def _proof_of_delivery(tb, d, txn, order) -> EvidenceItem:
    s = tb.get_shipment(order.order_id)
    if s is None or s.delivered_at is None or not s.proof_of_delivery_ref:
        detail = "no shipment record" if s is None else f"{s.carrier} {s.tracking_id} shipped {s.shipped_at.date() if s.shipped_at else '?'}, NOT delivered"
        return EvidenceItem(kind=EvidenceKind.PROOF_OF_DELIVERY, present=False, supports_merchant=None,
                            summary=f"No proof of delivery: {detail}", source_tool="get_shipment")
    return EvidenceItem(
        kind=EvidenceKind.PROOF_OF_DELIVERY, present=True, supports_merchant=True,
        summary=f"{s.carrier} {s.tracking_id} delivered {s.delivered_at.date()}, signed '{s.delivery_signature}', "
                f"POD ref {s.proof_of_delivery_ref}",
        source_tool="get_shipment")


def _avs_cvv(tb, d, txn, order) -> EvidenceItem:
    present = txn.avs_match is not None and txn.cvv_match is not None
    return EvidenceItem(
        kind=EvidenceKind.AVS_CVV_MATCH, present=present,
        supports_merchant=(bool(txn.avs_match) and bool(txn.cvv_match)) if present else None,
        summary=f"AVS match={txn.avs_match}, CVV match={txn.cvv_match}", source_tool="get_transaction")


def _three_ds(tb, d, txn, order) -> EvidenceItem:
    present = txn.three_ds_authenticated is not None
    return EvidenceItem(
        kind=EvidenceKind.THREE_DS, present=present,
        supports_merchant=bool(txn.three_ds_authenticated) if present else None,
        summary=f"3-D Secure authenticated={txn.three_ds_authenticated}", source_tool="get_transaction")


def _device(tb, d, txn, order) -> EvidenceItem:
    present = txn.device_id is not None
    return EvidenceItem(
        kind=EvidenceKind.DEVICE_SIGNALS, present=present,
        supports_merchant=bool(txn.device_seen_before) if present else None,
        summary=f"device {txn.device_id} seen_before={txn.device_seen_before}, ip_country={txn.ip_country}",
        source_tool="get_transaction")


def _refund(tb, d, txn, order) -> EvidenceItem:
    processed = [r for r in tb.get_refund_history(txn.transaction_id) if r.status == "processed"]
    if not processed:
        return EvidenceItem(kind=EvidenceKind.REFUND_RECORD, present=False, supports_merchant=None,
                            summary="No processed refund on this transaction", source_tool="get_refund_history")
    r = processed[0]
    return EvidenceItem(
        kind=EvidenceKind.REFUND_RECORD, present=True, supports_merchant=True,
        summary=f"Refund {r.refund_id} for {r.amount_paise/100:.2f} {d.currency} processed {r.issued_at.date()}",
        source_tool="get_refund_history")


def _comms(tb, d, txn, order) -> EvidenceItem:
    msgs = tb.get_customer_communications(order.order_id)
    outbound = [m for m in msgs if m.direction == "outbound"]
    return EvidenceItem(
        kind=EvidenceKind.CUSTOMER_COMMS, present=bool(msgs),
        supports_merchant=bool(outbound) if msgs else None,   # did the merchant engage at all?
        summary=(f"{len(msgs)} message(s), {len(outbound)} outbound. Latest: "
                 f"{msgs[-1].direction} {msgs[-1].sent_at.date()}: {msgs[-1].body}") if msgs else "No communications on file",
        source_tool="get_customer_communications")


def _terms(tb, d, txn, order) -> EvidenceItem:
    present = order.terms_accepted_at is not None
    return EvidenceItem(
        kind=EvidenceKind.TERMS_ACCEPTED, present=present, supports_merchant=present or None,
        summary=f"Terms accepted at checkout {order.terms_accepted_at.date()}" if present else "No terms-acceptance record",
        source_tool="get_order")


def _subscription(tb, d, txn, order) -> EvidenceItem:
    s = tb.get_subscription(txn.transaction_id)
    if s is None:
        return EvidenceItem(kind=EvidenceKind.SUBSCRIPTION_RECORD, present=False, supports_merchant=None,
                            summary="No subscription record", source_tool="get_subscription")
    charged_after_cancel = s.cancelled_at is not None and s.cancelled_at <= s.renewal_charged_at
    return EvidenceItem(
        kind=EvidenceKind.SUBSCRIPTION_RECORD, present=True, supports_merchant=not charged_after_cancel,
        summary=f"{s.plan}: cancelled_at={s.cancelled_at.date() if s.cancelled_at else None}, "
                f"renewal charged {s.renewal_charged_at.date()}"
                + (" — charge is AFTER cancellation" if charged_after_cancel else ""),
        source_tool="get_subscription")


def _duplicate_check(tb, d, txn, order) -> EvidenceItem:
    sibs = tb.get_related_transactions(txn.transaction_id)
    return EvidenceItem(
        kind=EvidenceKind.DUPLICATE_CHECK, present=True, supports_merchant=not sibs,
        summary=("No sibling capture on the same card within 10 minutes" if not sibs else
                 f"Sibling capture(s) found: {', '.join(t.transaction_id for t in sibs)} — looks like a genuine duplicate"),
        source_tool="get_related_transactions")


COLLECTORS: dict[EvidenceKind, Collector] = {
    EvidenceKind.ORDER_CONFIRMATION: _order_confirmation,
    EvidenceKind.PROOF_OF_DELIVERY: _proof_of_delivery,
    EvidenceKind.AVS_CVV_MATCH: _avs_cvv,
    EvidenceKind.THREE_DS: _three_ds,
    EvidenceKind.DEVICE_SIGNALS: _device,
    EvidenceKind.REFUND_RECORD: _refund,
    EvidenceKind.CUSTOMER_COMMS: _comms,
    EvidenceKind.TERMS_ACCEPTED: _terms,
    EvidenceKind.SUBSCRIPTION_RECORD: _subscription,
    EvidenceKind.DUPLICATE_CHECK: _duplicate_check,
}


def gather_evidence(tb: Toolbox, dispute: Dispute) -> EvidenceBundle:
    plan = EVIDENCE_PLAN[dispute.reason_code]
    txn = tb.get_transaction(dispute.transaction_id)
    order = tb.get_order(txn.order_id)
    items = [COLLECTORS[k](tb, dispute, txn, order) for k in plan.required + plan.optional]
    present = {i.kind for i in items if i.present}
    return EvidenceBundle(
        dispute_id=dispute.dispute_id, items=items, required=list(plan.required),
        missing_required=[k for k in plan.required if k not in present])


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def policy_gate(
    rec: Recommendation,
    bundle: EvidenceBundle,
    dispute: Dispute,
    now: datetime,
    verification: VerificationResult,
    screening: ScreeningResult,
) -> GateDecision:
    """Deterministic. Returns `rec.action` unchanged or `escalate` — nothing else."""
    reasons: list[str] = []
    hours_left = (dispute.respond_by - now).total_seconds() / 3600

    # Rules that apply to ANY commitment (contest or accept)
    if hours_left <= 0:
        reasons.append(f"response deadline passed ({dispute.respond_by.date()}); a human must decide next steps")
    elif hours_left < DEADLINE_BUFFER_HOURS:
        reasons.append(f"under {DEADLINE_BUFFER_HOURS}h to deadline ({hours_left:.0f}h left)")
    if rec.confidence < CONFIDENCE_FLOOR:
        reasons.append(f"confidence {rec.confidence:.2f} below floor {CONFIDENCE_FLOOR:.2f}")
    if screening.flagged:
        reasons.append(f"customer message flagged by injection screening: {', '.join(screening.hits)}")

    # Rules about the STRENGTH of a contest — irrelevant to an accept
    if rec.action == "contest":
        if bundle.missing_required:
            reasons.append("missing required evidence: " + ", ".join(k.value for k in bundle.missing_required))
        if not rec.citations:
            reasons.append("contest proposed without any policy citation")
        elif not verification.all_verified:
            bad = [v.citation.quote[:60] for v in verification.verdicts if not v.verified]
            reasons.append("citation(s) failed verbatim verification: " + " | ".join(bad))

    if rec.action == "escalate":
        final, downgraded = "escalate", False
    elif reasons:
        final, downgraded = "escalate", True
    else:
        final, downgraded = rec.action, False

    # The invariant, stated in code: the gate never invents a commitment.
    assert final in (rec.action, "escalate")
    return GateDecision(proposed_action=rec.action, final_action=final, downgraded=downgraded, reasons=reasons)
