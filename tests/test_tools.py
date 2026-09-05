"""Invariant 1: read-only, tenant-scoped, audited."""
import inspect

import pytest

from disputedesk import mock_data as db
from disputedesk.tools import TenantViolation, Toolbox

_WRITE_VERBS = ("set", "put", "post", "update", "delete", "create", "write", "submit", "save", "remove", "patch")


def test_toolbox_has_no_write_methods():
    public = [n for n, m in inspect.getmembers(Toolbox, inspect.isfunction) if not n.startswith("_")]
    assert public, "no public methods found?"
    for name in public:
        assert name.startswith("get_"), f"{name} is not a read"
        assert not name.startswith(_WRITE_VERBS)


def test_cross_tenant_read_raises_and_is_denied_in_audit():
    tb = Toolbox("MER001")
    with pytest.raises(TenantViolation):
        tb.get_dispute("DSP010")            # belongs to MER002
    denials = [c for c in tb.calls if not c.ok]
    assert len(denials) == 1 and denials[0].tool == "get_dispute"
    # the same record IS visible to its own tenant
    assert Toolbox("MER002").get_dispute("DSP010").merchant_id == "MER002"


def test_every_read_is_audited():
    tb = Toolbox("MER001")
    tb.get_dispute("DSP001")
    tb.get_transaction("TXN1001")
    tb.get_order("ORD1001")
    tb.get_shipment("ORD1001")
    tb.get_refund_history("TXN1001")
    tb.get_customer_communications("ORD1001")
    tb.get_subscription("TXN1001")
    tb.get_related_transactions("TXN1001")
    assert [c.tool for c in tb.calls] == [
        "get_dispute", "get_transaction", "get_order", "get_shipment", "get_refund_history",
        "get_customer_communications", "get_subscription", "get_related_transactions"]
    assert all(c.ok for c in tb.calls)


def test_no_pan_anywhere_in_dataset():
    """Only card_last4 exists. A 13-19 digit run anywhere in the seed data would be a PAN."""
    import re
    blob = " ".join(str(v) for coll in (db.DISPUTES, db.TRANSACTIONS, db.ORDERS) for v in coll.values())
    assert not re.search(r"(?<!\d)\d{13,19}(?!\d)", blob)
