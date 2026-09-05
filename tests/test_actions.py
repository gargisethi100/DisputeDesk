"""Invariant 2: one gated write, single-use token, no token from a rejection."""
import pytest

from disputedesk import mock_data as db
from disputedesk.actions import TokenError, mint_token, submit_dispute_response
from disputedesk.models import ApprovalToken, ReviewDecision

APPROVE = ReviewDecision(decision="approve", reviewer="ana@example.com")
BODY = "We contest this dispute."


def test_token_is_single_use_and_submit_is_idempotent():
    t = mint_token(APPROVE, "DSP001", BODY, db.NOW)
    first = submit_dispute_response(t, "DSP001", "contest", BODY, db.NOW)
    second = submit_dispute_response(t, "DSP001", "contest", BODY, db.NOW)
    assert first.status == "submitted"
    assert second.status == "duplicate_suppressed"
    assert first.idempotency_key == second.idempotency_key == t.digest


def test_submit_refuses_without_a_valid_token():
    t = mint_token(APPROVE, "DSP001", BODY, db.NOW)
    with pytest.raises(TokenError):
        submit_dispute_response(None, "DSP001", "contest", BODY, db.NOW)            # no token
    with pytest.raises(TokenError):
        submit_dispute_response(t, "DSP002", "contest", BODY, db.NOW)               # other dispute
    with pytest.raises(TokenError):
        submit_dispute_response(t, "DSP001", "contest", BODY + " and more", db.NOW)  # body tampered after approval
    forged = ApprovalToken(token_id="x", dispute_id="DSP001", reviewer="ana@example.com", digest="00" * 32, issued_at=db.NOW)
    with pytest.raises(TokenError):
        submit_dispute_response(forged, "DSP001", "contest", BODY, db.NOW)          # forged digest


def test_rejection_cannot_mint_a_token():
    with pytest.raises(TokenError):
        mint_token(ReviewDecision(decision="reject", reviewer="ana@example.com"), "DSP001", BODY, db.NOW)
    with pytest.raises(TokenError):
        mint_token(ReviewDecision(decision="approve", reviewer=""), "DSP001", BODY, db.NOW)   # anonymous approval
