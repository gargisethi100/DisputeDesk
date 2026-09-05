from disputedesk.models import Citation, Passage
from disputedesk.verifier import verify_citations

P = Passage(passage_id="doc#x", heading="x",
            text="To contest, the merchant must provide tracking and signature-confirmed proof of delivery "
                 "matching the billing or shipping address on the order.")


def test_accepts_verbatim_and_punctuation_drift():
    exact = Citation(passage_id="doc#x", quote="tracking and signature-confirmed proof of delivery matching the billing")
    drift = Citation(passage_id="doc#x", quote="Tracking and signature-confirmed proof of delivery, matching the billing")
    curly = Citation(passage_id="doc#x", quote="“signature-confirmed proof of delivery”")
    v = verify_citations([exact, drift, curly], [P])
    assert v.all_verified, [x.reason for x in v.verdicts]


def test_rejects_paraphrase_unknown_passage_and_trivial_quote():
    para = Citation(passage_id="doc#x", quote="the merchant must show the goods were delivered on time")
    ghost = Citation(passage_id="doc#nope", quote="tracking and signature-confirmed proof of delivery")
    tiny = Citation(passage_id="doc#x", quote="delivery")
    v = verify_citations([para, ghost, tiny], [P])
    assert not v.all_verified
    assert [x.verified for x in v.verdicts] == [False, False, False]
    assert "not retrieved" in v.verdicts[1].reason
