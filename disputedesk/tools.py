"""tools.py — read-only, tenant-scoped, audited data access.

INVARIANTS (tested):
  * There are NO write methods on `Toolbox`. The agent cannot change merchant data.
  * A `Toolbox` is bound to exactly one `merchant_id` at construction. Every record it
    returns passes `_assert_tenant`; a cross-tenant record raises `TenantViolation`
    and the denial is recorded before the exception propagates.
  * Every call — allowed or denied — is appended to `self.calls` for the audit log.
  * This module never imports or calls an LLM.

Why look up globally and then assert, rather than filtering the query by merchant?
Because the assert is the *guarantee* and the filter would only be an optimisation.
In production the backing store would be scoped too (defence in depth), but the
tool layer must be correct even if the store isn't.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable, TypeVar

from . import mock_data as db
from .models import (
    Communication, Dispute, Order, Refund, Shipment, Subscription, ToolCall, Transaction,
)

T = TypeVar("T")


class TenantViolation(PermissionError):
    """Raised when a record belonging to another merchant is touched."""


class RecordNotFound(LookupError):
    pass


class Toolbox:
    """Read-only data tools for ONE merchant."""

    def __init__(self, merchant_id: str) -> None:
        if merchant_id not in db.MERCHANTS:
            raise RecordNotFound(f"unknown merchant {merchant_id}")
        self.merchant_id = merchant_id
        self.calls: list[ToolCall] = []

    # ------------------------------------------------------------------ guards
    def _assert_tenant(self, record: T, tool: str, args: dict) -> T:
        owner = getattr(record, "merchant_id", None)
        if owner != self.merchant_id:
            # Record the denial BEFORE raising so the audit trail shows the attempt.
            self.calls.append(ToolCall(
                tool=tool, args=args, ok=False,
                detail=f"TenantViolation: record belongs to {owner}, toolbox bound to {self.merchant_id}",
            ))
            raise TenantViolation(f"{tool}{args}: record belongs to {owner}, not {self.merchant_id}")
        return record

    def _assert_all(self, records: Iterable[T], tool: str, args: dict) -> list[T]:
        return [self._assert_tenant(r, tool, args) for r in records]

    def _ok(self, tool: str, args: dict, detail: str = "") -> None:
        self.calls.append(ToolCall(tool=tool, args=args, ok=True, detail=detail))

    # ------------------------------------------------------------------ reads
    def get_dispute(self, dispute_id: str) -> Dispute:
        args = {"dispute_id": dispute_id}
        rec = db.DISPUTES.get(dispute_id)
        if rec is None:
            raise RecordNotFound(dispute_id)
        self._assert_tenant(rec, "get_dispute", args)
        self._ok("get_dispute", args, f"{rec.reason_code.value} · respond_by={rec.respond_by.date()}")
        return rec

    def get_transaction(self, transaction_id: str) -> Transaction:
        args = {"transaction_id": transaction_id}
        rec = db.TRANSACTIONS.get(transaction_id)
        if rec is None:
            raise RecordNotFound(transaction_id)
        self._assert_tenant(rec, "get_transaction", args)
        self._ok("get_transaction", args, f"avs={rec.avs_match} cvv={rec.cvv_match} 3ds={rec.three_ds_authenticated}")
        return rec

    def get_order(self, order_id: str) -> Order:
        args = {"order_id": order_id}
        rec = db.ORDERS.get(order_id)
        if rec is None:
            raise RecordNotFound(order_id)
        self._assert_tenant(rec, "get_order", args)
        self._ok("get_order", args, f"{len(rec.items)} item(s), digital={rec.digital_delivery}")
        return rec

    def get_shipment(self, order_id: str) -> Shipment | None:
        args = {"order_id": order_id}
        rec = db.SHIPMENTS.get(order_id)
        if rec is None:
            self._ok("get_shipment", args, "no shipment record")
            return None
        self._assert_tenant(rec, "get_shipment", args)
        self._ok("get_shipment", args, f"delivered={rec.delivered_at is not None} pod={rec.proof_of_delivery_ref}")
        return rec

    def get_refund_history(self, transaction_id: str) -> list[Refund]:
        args = {"transaction_id": transaction_id}
        recs = [r for r in db.REFUNDS if r.transaction_id == transaction_id]
        recs = self._assert_all(recs, "get_refund_history", args)
        self._ok("get_refund_history", args, f"{len(recs)} refund(s)")
        return recs

    def get_customer_communications(self, order_id: str) -> list[Communication]:
        args = {"order_id": order_id}
        recs = [c for c in db.COMMUNICATIONS if c.order_id == order_id]
        recs = self._assert_all(recs, "get_customer_communications", args)
        self._ok("get_customer_communications", args, f"{len(recs)} message(s)")
        return recs

    def get_subscription(self, transaction_id: str) -> Subscription | None:
        args = {"transaction_id": transaction_id}
        rec = db.SUBSCRIPTIONS.get(transaction_id)
        if rec is None:
            self._ok("get_subscription", args, "no subscription")
            return None
        self._assert_tenant(rec, "get_subscription", args)
        self._ok("get_subscription", args, f"cancelled_at={rec.cancelled_at}")
        return rec

    def get_related_transactions(self, transaction_id: str, window_minutes: int = 10) -> list[Transaction]:
        """Other captures on the same card + merchant within ±window. Used for 12.6 duplicate checks."""
        args = {"transaction_id": transaction_id, "window_minutes": window_minutes}
        base = db.TRANSACTIONS.get(transaction_id)
        if base is None:
            raise RecordNotFound(transaction_id)
        self._assert_tenant(base, "get_related_transactions", args)
        w = timedelta(minutes=window_minutes)
        recs = [
            t for t in db.TRANSACTIONS.values()
            if t.transaction_id != transaction_id
            and t.merchant_id == base.merchant_id
            and t.card_last4 == base.card_last4
            and abs(t.captured_at - base.captured_at) <= w
        ]
        self._ok("get_related_transactions", args, f"{len(recs)} sibling capture(s)")
        return recs
