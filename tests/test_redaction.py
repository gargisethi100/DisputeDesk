"""Invariant 5: nothing reaches a model without redaction."""
from disputedesk import mock_data as db
from disputedesk.analysis import build_analyst_prompt, make_redactor
from disputedesk.policy import gather_evidence
from disputedesk.redaction import Redactor
from disputedesk.retrieval import Retriever, query_for
from disputedesk.tools import Toolbox

SAMPLE = (
    "Hi Priya Raman, ship to 14 Lakeview Apartments, Koramangala, Bengaluru 560034. "
    "Call +91 98450 12345 or mail priya.raman@example.com. UPI priya@okhdfcbank, "
    "IFSC HDFC0001234, account 123456789012.\nRegards,\nPriya Raman"
)


def _redactor():
    o = db.ORDERS["ORD1001"]
    return make_redactor(o)


def test_masks_every_pii_class():
    r = _redactor()
    masked = r.redact(SAMPLE)
    for raw in ("Priya Raman", "14 Lakeview", "98450 12345", "priya.raman@example.com",
                "priya@okhdfcbank", "HDFC0001234", "123456789012"):
        assert raw not in masked, raw
    for ph in ("[NAME_1]", "[ADDRESS_1]", "[PHONE_1]", "[EMAIL_1]", "[VPA_1]", "[IFSC_1]", "[ACCOUNT_1]"):
        assert ph in masked, ph
    assert not r.has_leak(masked)


def test_restore_roundtrips():
    r = _redactor()
    assert r.restore(r.redact(SAMPLE)) == SAMPLE
    assert r.masked_count >= 7


def test_has_leak_is_strict_on_raw_and_clean_on_placeholders():
    r = Redactor(known={"NAME": ["Priya Raman"]})
    assert r.has_leak("call Priya Raman")
    assert r.has_leak("mail x@y.com")
    assert not r.has_leak("call [NAME_1] at [PHONE_1]\nRegards,\n[NAME_1]")


def test_every_analyst_prompt_is_leak_free():
    """The assert inside build_analyst_prompt is the guard; this proves it holds for all seeds."""
    ret = Retriever()
    for did, d in db.DISPUTES.items():
        if d.merchant_id != "MER001":
            continue
        tb = Toolbox("MER001")
        bundle = gather_evidence(tb, d)
        order = tb.get_order(tb.get_transaction(d.transaction_id).order_id)
        r = make_redactor(order)
        prompt = build_analyst_prompt(d, bundle, ret.search(query_for(d.reason_code)), r, db.NOW)
        assert not r.has_leak(prompt), did
        assert order.customer_name not in prompt and order.customer_email not in prompt
        assert order.shipping_address not in prompt
