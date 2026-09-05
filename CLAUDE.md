# DisputeDesk — context for Claude Code

## What this is
A safe chargeback-response agent. LLM proposes → deterministic policy gate disposes → human approves → one gated write.
Read `README.md` (architecture + security model) before changing anything. Owner: Gargi Sethi.

## Commands
```bash
pip install -r requirements.txt && cp .env.example .env
python cli.py DSP001 --approve          # end-to-end, mock mode
python cli.py DSP009                    # adversarial case (injection flagged)
python -m pytest -q                     # must stay green
python eval/run_eval.py                 # 10 cases -> results/eval.md (must stay 10/10 after gate)
streamlit run app.py
```

## Non-negotiable invariants (tests enforce most of these — keep them green)
1. `disputedesk/tools.py` has NO write methods. New data access = new read-only method on `Toolbox`, tenant-scoped via `_assert_tenant`.
2. Only `actions.submit_dispute_response` has side effects; it needs a single-use `ApprovalToken`. Never call it outside the `submit` graph node.
3. The graph stays compiled with `interrupt_before=["submit"]`. Do not remove the human pause.
4. `policy.policy_gate` may only DOWNGRADE the model's action (contest → escalate/accept). Never let it upgrade.
5. Nothing reaches a model without passing through `Redactor.redact`; `assert not redactor.has_leak(prompt)` stays.
6. `verifier.py`, `policy.py`, `screening.py`, `redaction.py`, `tools.py` never import or call an LLM.
7. Every artefact crossing a node boundary is a Pydantic model in `models.py`; state holds `model_dump()` dicts.
8. `mock_data.NOW` is the frozen clock; use `state["now"]`, never `datetime.now()`, in business logic.

## Layout
- `disputedesk/graph.py` — LangGraph nodes/edges, `run_until_review`, `resume_with_decision`
- `disputedesk/policy.py` — `EVIDENCE_PLAN`, `gather_evidence`, `policy_gate`
- `disputedesk/analysis.py` — prompts, `recommend` (LLM + heuristic fallback), `draft_response`, `make_redactor`
- `disputedesk/retrieval.py` — BM25 [+ optional dense] over `corpus/*.md` chunked on `## ` headings
- `disputedesk/llm.py` — `BedrockProvider` (converse API) and `MockProvider`; `get_provider()` reads `DISPUTEDESK_LLM_PROVIDER`
- `eval/`, `tests/`, `infra/` (Dockerfile at root; ECS task def + IAM policy + DEPLOY.md)

## Do NOT
- Add FastAPI/Celery/a second service. One Streamlit container is the deliverable.
- Use any payment gateway's name or logo in the app name or UI.
- Put real credentials anywhere in the repo; `.env` is gitignored.
- Rewrite modules wholesale — the owner must be able to explain every line in an interview. Prefer small, commented diffs.
