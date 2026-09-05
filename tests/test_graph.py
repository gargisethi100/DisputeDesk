"""Invariant 3: the graph pauses before submit; reject files nothing; approve files once."""
import pytest

from disputedesk import audit
from disputedesk.graph import GRAPH, resume_with_decision, run_until_review
from disputedesk.models import ReviewDecision
from disputedesk.tools import TenantViolation


def test_graph_interrupts_before_submit_and_resumes_on_approval():
    thread_id, s = run_until_review("DSP001", "MER001")
    assert s["draft"] and "receipt" not in s and "token" not in s
    assert GRAPH.get_state({"configurable": {"thread_id": thread_id}}).next == ("submit",)

    final = resume_with_decision(thread_id, ReviewDecision(decision="approve", reviewer="ana@example.com"))
    assert final["outcome"] == "submitted" and final["receipt"]["action"] == "contest"
    rec = audit.read_review_records()[-1]
    assert rec["dispute_id"] == "DSP001" and rec["reviewer"] == "ana@example.com" and rec["outcome"] == "submitted"
    assert rec["tool_calls"] and rec["denials"] == []


def test_reject_files_nothing_but_is_audited():
    thread_id, _ = run_until_review("DSP001", "MER001")
    final = resume_with_decision(thread_id, ReviewDecision(decision="reject", reviewer="ana@example.com", note="wrong POD"))
    assert final["outcome"] == "rejected" and "receipt" not in final and "token" not in final
    assert audit.read_review_records()[-1]["outcome"] == "rejected"


def test_cross_tenant_dispute_never_enters_the_graph():
    with pytest.raises(TenantViolation):
        run_until_review("DSP010", "MER001")
