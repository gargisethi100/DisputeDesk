"""Invariant 4: the gate only ever moves toward escalate."""
import itertools

import pytest

from disputedesk import mock_data as db
from disputedesk.models import Citation, Recommendation, ScreeningResult, VerificationResult, CitationVerdict
from disputedesk.policy import CONFIDENCE_FLOOR, gather_evidence, policy_gate
from disputedesk.tools import Toolbox

CLEAN = ScreeningResult(flagged=False, hits=[])
FLAGGED = ScreeningResult(flagged=True, hits=["ignore_previous"])
OK = VerificationResult(all_verified=True, verdicts=[])
CIT = [Citation(passage_id="p", quote="some verbatim words from the passage")]


def _bundle(did):
    tb = Toolbox("MER001")
    d = tb.get_dispute(did)
    return d, gather_evidence(tb, d)


def _rec(action, conf=0.9, cits=CIT):
    return Recommendation(action=action, confidence=conf, rationale="t", citations=cits, source="heuristic")


def test_downgrades_contest_past_deadline():
    d, b = _bundle("DSP008")                       # respond_by is yesterday
    g = policy_gate(_rec("contest"), b, d, db.NOW, OK, CLEAN)
    assert g.final_action == "escalate" and g.downgraded
    assert any("deadline passed" in r for r in g.reasons)


def test_blocks_contest_on_missing_required_evidence():
    d, b = _bundle("DSP009")                       # no proof of delivery
    assert b.missing_required
    g = policy_gate(_rec("contest"), b, d, db.NOW, OK, CLEAN)
    assert g.final_action == "escalate"
    assert any("missing required evidence" in r for r in g.reasons)


def test_blocks_contest_on_unverified_citation_or_no_citation():
    d, b = _bundle("DSP001")
    bad = VerificationResult(all_verified=False, verdicts=[CitationVerdict(citation=CIT[0], verified=False, reason="x")])
    assert policy_gate(_rec("contest"), b, d, db.NOW, bad, CLEAN).final_action == "escalate"
    assert policy_gate(_rec("contest", cits=[]), b, d, db.NOW, OK, CLEAN).final_action == "escalate"
    # and a clean contest passes
    assert policy_gate(_rec("contest"), b, d, db.NOW, OK, CLEAN).final_action == "contest"


def test_flag_and_low_confidence_escalate_any_commitment():
    d, b = _bundle("DSP001")
    assert policy_gate(_rec("accept"), b, d, db.NOW, OK, FLAGGED).final_action == "escalate"
    assert policy_gate(_rec("contest", conf=CONFIDENCE_FLOOR - 0.01), b, d, db.NOW, OK, CLEAN).final_action == "escalate"


@pytest.mark.parametrize("did", [d for d, x in db.DISPUTES.items() if x.merchant_id == "MER001"])
def test_gate_never_upgrades(did):
    """For every dispute and every combination of inputs, final ∈ {proposed, escalate}."""
    d, b = _bundle(did)
    bad = VerificationResult(all_verified=False, verdicts=[CitationVerdict(citation=CIT[0], verified=False, reason="x")])
    for action, conf, ver, scr in itertools.product(("contest", "accept", "escalate"), (0.2, 0.95), (OK, bad), (CLEAN, FLAGGED)):
        g = policy_gate(_rec(action, conf), b, d, db.NOW, ver, scr)
        assert g.final_action in (action, "escalate")
        if action == "escalate":
            assert g.final_action == "escalate" and not g.downgraded
        if action == "accept":
            assert g.final_action != "contest"
