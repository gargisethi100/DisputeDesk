"""models.py — every artefact that crosses a node boundary is a Pydantic model.

Why Pydantic at every boundary: the LLM's output is untrusted text. Parsing it into a
strict schema (and rejecting anything that doesn't fit) is the first line of defence.
Everything downstream — verifier, gate, token — operates on validated objects, never
on raw strings. Graph state stores `model_dump()` dicts so LangGraph can checkpoint it.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Domain vocabulary
# --------------------------------------------------------------------------- #

class ReasonCode(str, Enum):
    """Card-network dispute reason codes (Visa-style numbering, used widely by
    Indian acquirers). The code decides which evidence is even admissible."""
    FRAUD_CNP = "10.4"             # fraud — card-absent environment
    DUPLICATE = "12.6"             # duplicate processing
    NOT_RECEIVED = "13.1"          # merchandise / services not received
    RECURRING_CANCELLED = "13.2"   # cancelled recurring transaction
    NOT_AS_DESCRIBED = "13.3"      # not as described or defective
    CREDIT_NOT_PROCESSED = "13.6"  # credit not processed


# `escalate` is the only action that is NOT a commitment. contest and accept both file
# something irreversible with the network. The policy gate may only move toward escalate.
Action = Literal["contest", "accept", "escalate"]


class EvidenceKind(str, Enum):
    PROOF_OF_DELIVERY = "proof_of_delivery"
    ORDER_CONFIRMATION = "order_confirmation"
    AVS_CVV_MATCH = "avs_cvv_match"
    THREE_DS = "three_ds_authentication"
    DEVICE_SIGNALS = "device_signals"
    REFUND_RECORD = "refund_record"
    CUSTOMER_COMMS = "customer_communications"
    TERMS_ACCEPTED = "terms_accepted"
    SUBSCRIPTION_RECORD = "subscription_record"
    DUPLICATE_CHECK = "duplicate_check"


# --------------------------------------------------------------------------- #
# Merchant-system records (what the read-only tools return)
# --------------------------------------------------------------------------- #

class Merchant(BaseModel):
    merchant_id: str
    name: str


class Dispute(BaseModel):
    dispute_id: str
    merchant_id: str
    transaction_id: str
    reason_code: ReasonCode
    amount_paise: int                      # money in minor units, never float
    currency: str = "INR"
    opened_at: datetime
    respond_by: datetime                   # the hard deadline the gate enforces
    customer_message: str                  # UNTRUSTED — screened + fenced before any prompt
    card_last4: str                        # the only card data that exists anywhere
    status: Literal["open", "responded", "accepted", "escalated"] = "open"


class Transaction(BaseModel):
    transaction_id: str
    merchant_id: str
    order_id: str
    amount_paise: int
    captured_at: datetime
    card_last4: str
    avs_match: bool | None = None
    cvv_match: bool | None = None
    three_ds_authenticated: bool | None = None
    ip_country: str | None = None
    device_id: str | None = None
    device_seen_before: bool | None = None


class Order(BaseModel):
    order_id: str
    merchant_id: str
    customer_name: str                     # PII
    customer_email: str                    # PII
    customer_phone: str                    # PII
    shipping_address: str                  # PII
    items: list[str]
    placed_at: datetime
    terms_accepted_at: datetime | None = None
    digital_delivery: bool = False


class Shipment(BaseModel):
    order_id: str
    merchant_id: str
    carrier: str
    tracking_id: str
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    delivery_signature: str | None = None  # PII
    proof_of_delivery_ref: str | None = None


class Refund(BaseModel):
    refund_id: str
    merchant_id: str
    transaction_id: str
    amount_paise: int
    issued_at: datetime
    status: Literal["processed", "pending", "failed"]


class Communication(BaseModel):
    order_id: str
    merchant_id: str
    channel: Literal["email", "chat", "phone"]
    direction: Literal["inbound", "outbound"]
    sent_at: datetime
    body: str                              # may contain PII


class Subscription(BaseModel):
    subscription_id: str
    merchant_id: str
    transaction_id: str
    plan: str
    cancelled_at: datetime | None = None
    renewal_charged_at: datetime


# --------------------------------------------------------------------------- #
# Agent artefacts (produced by nodes)
# --------------------------------------------------------------------------- #

class ToolCall(BaseModel):
    """One audited read. `ok=False` records a denial (e.g. TenantViolation)."""
    tool: str
    args: dict
    ok: bool
    detail: str = ""


class EvidenceItem(BaseModel):
    kind: EvidenceKind
    present: bool                          # do we hold a record of this kind at all?
    supports_merchant: bool | None = None  # if present: does it help the merchant's case?
    summary: str                           # human-readable; redacted before any prompt
    source_tool: str


class EvidenceBundle(BaseModel):
    dispute_id: str
    items: list[EvidenceItem]
    required: list[EvidenceKind]
    missing_required: list[EvidenceKind]


class Passage(BaseModel):
    passage_id: str                        # "<doc>#<slugified-heading>"
    heading: str
    text: str
    score: float = 0.0


class Citation(BaseModel):
    passage_id: str
    quote: str                             # must be VERBATIM in the passage (verifier checks)


class Recommendation(BaseModel):
    """What the model (or heuristic) proposes. Never final."""
    action: Action
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citations: list[Citation] = []
    source: Literal["llm", "heuristic"]


class CitationVerdict(BaseModel):
    citation: Citation
    verified: bool
    reason: str = ""


class VerificationResult(BaseModel):
    all_verified: bool
    verdicts: list[CitationVerdict]


class ScreeningResult(BaseModel):
    flagged: bool
    hits: list[str]                        # names of the patterns that fired


class GateDecision(BaseModel):
    """Deterministic. `final_action` is always `proposed_action` or `escalate`."""
    proposed_action: Action
    final_action: Action
    downgraded: bool
    reasons: list[str]


class DraftResponse(BaseModel):
    subject: str
    body: str                              # PII restored here — reviewer-facing only
    evidence_refs: list[EvidenceKind]
    source: Literal["llm", "template"]


class ReviewDecision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    reviewer: str
    edited_body: str | None = None
    note: str = ""


class ApprovalToken(BaseModel):
    """Single-use capability. Only `actions.mint_token` creates one, and only from an
    approve/edit decision. Its digest doubles as the submission idempotency key."""
    token_id: str
    dispute_id: str
    reviewer: str
    digest: str
    issued_at: datetime


class SubmissionReceipt(BaseModel):
    dispute_id: str
    action: Action
    idempotency_key: str
    submitted_at: datetime
    status: Literal["submitted", "duplicate_suppressed"]


class AuditEntry(BaseModel):
    node: str
    message: str
    data: dict = {}
