# Design decisions

Every consequential choice in DisputeDesk, why it was made, and what was rejected to make it.
The format is deliberate: a decision you can't state an alternative for isn't a decision, it's a default.

---

# Part 1 — Evaluation

## Why evaluate an agent on ten cases instead of a hundred

**Chosen:** ten hand-designed disputes, each isolating exactly one path through the system.

Every case is there to make one thing fail if it's broken:

| Case | The one thing it tests |
|---|---|
| DSP001 | Required evidence present and supporting → contest goes through |
| DSP002 | Fraud path: AVS/CVV/3DS/device, a different evidence plan from 13.1 |
| DSP003 | Evidence *present* but pointing the wrong way — an unanswered complaint → accept |
| DSP004 | A derived fact, not a stored one: two captures on one card minutes apart → accept |
| DSP005 | The counter-intuitive one: a refund on file makes 13.6 **contestable**, not acceptable |
| DSP006 | Timeline comparison: cancellation before renewal → accept |
| DSP007 | Fraud on digital goods, where proof of delivery doesn't exist and mustn't be required |
| DSP008 | The gate overriding a model that is **right on the merits** |
| DSP009 | Prompt injection *and* missing evidence, so the flag isn't the only thing holding |
| DSP010 | Tenancy — the case must be unreachable, not merely filtered out |

**Rejected — a large generated set.** Hundreds of LLM-generated disputes would have produced a
prettier number and taught me nothing. You cannot design a case that isolates the deadline rule
from the evidence rule if the cases are random. Ten cases where I can name the failure each one
catches is a stronger artefact than five hundred where I can't.

**Rejected — real dispute data.** There isn't a public chargeback dataset with evidence bundles,
and inventing plausible-looking real data would be worse than clearly synthetic data.

**What this eval does not prove.** It does not measure whether the *win rate* at the card network
improves, because that needs outcome data that only an acquirer has. It measures whether the system
takes the defensible action on cases whose correct answer I can defend. Those are different claims
and the README says so.

## Why the headline metric is measured after the gate, and the raw one is published anyway

**Chosen:** report both. After the gate: 10/10. Before the gate, model alone: 8/9.

| Metric | Bedrock (Claude Sonnet) | Mock / heuristic |
|---|---|---|
| Action accuracy after the gate | 100% (10/10) | 100% (10/10) |
| Raw model accuracy before the gate | 89% (8/9) | 89% (8/9) |
| Citation faithfulness, verbatim | 100% (9/9) | 100% (9/9) |
| Escalation rate | 22% (2/9) | 22% (2/9) |
| Adversarial flagged | 1/1 | 1/1 |
| Cross-tenant blocked | 1/1 | 1/1 |

The eleven-point gap is the entire argument for the architecture, expressed as a number rather than
a claim. Publishing only the 10/10 would hide the thing that justifies the design. The one raw miss
in both columns is DSP008 — the model says contest, and it's *correct* about the evidence; it simply
doesn't own the deadline.

**Rejected — reporting only end-to-end accuracy.** It's the flattering number and it makes the
deterministic layer look decorative.

**Rejected — hiding the mock column.** It's identical to the live column, which is the point: the
rule-based fallback reaches the same decisions on these cases, so a model outage degrades quality,
not correctness. That's worth showing, not hiding.

## Why an LLM never judges this system

**Chosen:** every metric is computed by deterministic code. Citation faithfulness is a normalised
substring check. Action accuracy is string equality against a hand-labelled expectation.

**Rejected — LLM-as-judge.** For citation grounding it is strictly worse: a substring check has no
false negatives, costs nothing, and can't be talked out of its answer. A judge introduces a second
model's opinion into a security property. LLM-as-judge is listed as a *future* addition for one
thing only — draft letter quality — because that genuinely has no ground truth.

## Why the clock is frozen

**Chosen:** `mock_data.NOW` is a fixed instant; `now` travels in graph state; business logic never
calls `datetime.now()`.

DSP008's entire purpose is "the deadline passed yesterday". With a live clock that test flips from
green to red depending on the day you run it, and the eval stops being reproducible. The only place
allowed a wall clock is the audit writer, because "when was this line written" is a fact about the
log, not about the dispute.

**Rejected — relative offsets computed at import time.** Same instability, harder to see.

## The retrieval ablation, and the prior that didn't survive it

**Chosen:** BM25 as the shipped default; dense retrieval available behind a flag.

I had measured on a previous project (ClauseLens, on legal contracts) that BM25 beat dense
embeddings. I re-ran the comparison here rather than assuming it transferred:

| Query family | BM25 R@1 | dense (bge-small) R@1 | hybrid RRF R@1 |
|---|---|---|---|
| Structured — what the graph actually sends (reason code + keywords), n=6 | 1.00 | 1.00 | 1.00 |
| Natural language — how an analyst would phrase it, n=12 | 0.58 | **0.75** | **0.75** |

**The prior did not transfer.** On paraphrased queries dense wins clearly. But the graph never sends
paraphrased queries — it knows the reason code and sends it, and on those every ranker is perfect.
So BM25 ships (no torch in the container, 200 MB smaller, no cold-start model load) and dense is
documented as the upgrade path *if* free-text analyst search is ever added to the UI.

The honest version of this finding is more interesting than the convenient one: I was wrong about
transfer, the measurement caught it, and the shipping decision still went to BM25 — for a different
reason than I originally believed.

**Rejected — shipping hybrid because it scored best overall.** It scores best on queries this system
never issues. That's paying real cost for a benchmark artefact.

---

# Part 2 — Architecture

Each decision below: what was chosen, why, what was rejected, and what the choice costs.

## The model proposes, a deterministic function disposes

**Chosen.** `analysis.recommend` returns an action, a confidence and citations. `policy.policy_gate`
— plain Python, no model — decides what may be *proposed* to a human.

**Why.** The model's failure mode is confident wrongness on a sympathetic-looking evidence bundle.
The constraints that matter (deadline passed, required evidence missing, citation unverifiable) are
all mechanically checkable. Anything mechanically checkable should not be delegated to a sampler.

**Rejected — trusting the model with the final action.** One bad sample files an irreversible
response.
**Rejected — a scoring function** (`0.4·evidence + 0.3·confidence + …`). It produces a number a
reviewer can't argue with. The gate produces a *list of reasons*, and the reasons are the product.
**Rejected — a second model reviewing the first.** Two samplers, twice the cost, no guarantee.

**Cost.** The gate can only enforce rules I thought of. A novel failure mode passes through it
untouched, and only the human catches it.

## The gate can only move toward `escalate` — never toward a commitment

**Chosen.** `final_action ∈ {proposed_action, escalate}`, asserted in code at the end of the function
and tested across every dispute × 24 input combinations.

**Why.** The original spec said the gate may downgrade "contest → escalate or accept". I narrowed it.
**Accept is also an irreversible commitment** — you concede the money. A gate that converts a contest
into an accept is a gate making a business decision on its own. Escalate is the only action that
commits to nothing, so the lattice gets exactly one sink.

**Rejected — allowing contest → accept.** Above.
**Rejected — allowing the gate to upgrade when evidence is overwhelming.** Then the gate is a second
decision-maker rather than a constraint, and "the model can never cause an action it didn't propose"
stops being true.

**Cost.** More escalations than strictly necessary — a human looks at cases that a bolder system
would auto-accept.

## Tenant isolation is bound at construction, and asserted rather than filtered

**Chosen.** `Toolbox(merchant_id)`. Every returned record passes `_assert_tenant`, which raises
`TenantViolation` and records the denial *before* the exception propagates.

**Why.** A filter is an optimisation; an assert is a guarantee. The tool layer has to be correct even
if the backing store isn't scoped. And binding at construction means there's no per-call merchant
argument for a caller to get wrong.

**Rejected — a `merchant_id` parameter on each method.** One forgotten argument is a cross-tenant read.
**Rejected — filtering the query by merchant.** Correct in the happy path, silent when it's wrong: a
filtered query returns *nothing* rather than raising, so a bug looks like an empty result.
**Rejected — enforcing tenancy in the prompt.** Then isolation depends on a model following instructions.

**Cost.** Every read touches a global lookup before the check. Irrelevant here; in production the
store would be scoped too, as defence in depth rather than as the only defence.

## The toolbox has no write methods at all

**Chosen.** Every public method is `get_*`. A test enumerates the class by introspection and fails if
anything else appears.

**Why.** "The agent only reads" is a much stronger claim when it's structural rather than behavioural.
The test means a future contributor can't quietly add `update_dispute` without the suite going red.

**Rejected — read/write tools with permission checks.** Now correctness depends on every check being
right, forever.
**Rejected — documenting the convention in a comment.** Comments don't fail builds.

## Evidence gathering follows a fixed plan per reason code

**Chosen.** `EVIDENCE_PLAN: ReasonCode → (required, optional)`. The agent calls exactly those tools.
The model does not choose tools.

**Why.** Which evidence is *admissible* is a lookup table published by the card networks, not a
reasoning problem. 13.1 is won with proof of delivery; 10.4 with authentication and device data.
Submitting the wrong evidence for a reason code loses automatically. There is nothing here for a
model to be clever about, and making it a table means the gate can check "required evidence present"
mechanically.

**Rejected — LLM tool planning.** It's the obvious next step and it's named as such in the README,
but it would have to be constrained to the same read-only toolbox with the fixed plan as a floor —
otherwise the gate loses its ability to say "you're missing what this reason code requires".

**Cost.** The agent can't notice that some unusual piece of evidence would help. This is the top
item in the limitations section, stated plainly rather than hidden.

## Citations are verified by substring matching, not by trust or by a judge

**Chosen.** Each quote must appear verbatim in the passage it cites, after normalisation. An
unverified citation blocks a contest via the gate. Quotes under 12 characters are rejected outright.

**Why.** This converts "please cite your sources" (which every system says) into "an unverifiable
citation cannot influence the outcome" (which is mechanically true).

**The normalisation is a deliberate loosening.** I started with ClauseLens's version, which only
collapsed spaces *around* punctuation. Testing showed the model inserting a comma and failing an
otherwise perfect quote. So punctuation is now stripped entirely — the check is "same words, same
order". The asymmetry justifies it: a false rejection costs one escalation (safe), a missed
fabrication costs a wrong contest (unsafe). Loosen toward the safe error.

**Rejected — exact string matching.** Fails constantly on benign reformatting; the metric would
under-report and the gate would escalate everything.
**Rejected — semantic similarity above a threshold.** A fabricated rule that *sounds* like the real
one scores high. That's precisely the attack.

## Injection screening flags; it never decides

**Chosen.** `screening.py` returns `{flagged, hits}`. The gate reads that flag alongside everything
else. A hit routes the case to a human and lands in the audit log. It never directly changes the action.

**Why.** The moment untrusted input can change control flow — even in the "safe" direction — the
attacker has a lever. A customer who discovers that certain phrases force an escalation has found a
way to delay every dispute against them.

**Rejected — auto-accepting or auto-rejecting on a screening hit.** Above.
**Rejected — an LLM-based injection classifier.** A model guarding a model, and it would break the
rule that five modules never call an LLM.

**Cost.** The heuristics are bypassable and I say so out loud. That's tolerable *only* because
nothing which actually prevents harm depends on this firing — tenancy, redaction, the token and the
gate all hold whether or not the detector notices.

## PII masking is two layers, neither of them a model

**Chosen.** Layer 1 replaces entities we *own* (name, email, phone, address from the order record,
plus the derived `P. Raman` signature form) by exact string match, longest first. Layer 2 sweeps for
shapes we didn't know about: emails, Indian mobiles, UPI VPAs, IFSC codes, 11–16 digit runs,
sign-off lines. `assert not redactor.has_leak(prompt)` runs before every model call.

**Why.** Regexes can't find "14 Lakeview Apartments, Koramangala" — but we don't need them to, we
have the address in our own records. Exact masking of known entities is deterministic; regex is the
net for free text.

**Rejected — an NER model (Presidio, spaCy).** Probabilistic, a third model in the loop, and it
breaks the no-LLM rule for that module.
**Rejected — masking at storage time.** The human reviewer needs the real text; only the prompt path
needs masking.

**A bug worth naming.** `has_leak` originally re-ran the raw regexes and fired on `Regards,\n[NAME_1]`
— a placeholder sitting in signature position. The leak check and the masker now share one function,
because if they disagree about what "clean" means, one of them is lying.

**Cost.** The placeholder map lives in graph state. In production it belongs server-side and
encrypted; that's in the deferred list.

## The approval is a capability token, not a boolean

**Chosen.** `ApprovalToken` is minted only by `mint_token`, only from an approve/edit decision. Its
SHA-256 digest covers `(dispute_id, reviewer, exact body)`. It's spent on first use, and the digest
doubles as the idempotency key.

**Why.** Three properties fall out of one hash. *Binding* — edit the letter after approval and the
digest stops matching, so "approve with edits" mints over the edited text. *Idempotency* — a
double-click, refresh or retry returns the original receipt marked `duplicate_suppressed`. *Forgery
resistance* — a hand-built token with an invented digest fails the recompute.

**Rejected — an `approved: bool` on graph state.** Any node can set it; it binds to nothing; a retry
files twice.
**Rejected — a per-dispute lock.** Prevents concurrency, doesn't bind to content.
**Rejected — letting a rejection produce a token with a `rejected` flag.** There is deliberately *no
code path* from a rejection to a token. Absence of a path beats a correct branch.

## The human pause is a property of the compiled graph

**Chosen.** LangGraph `StateGraph` compiled with `interrupt_before=["submit"]` and a checkpointer.

**Why.** The pause isn't an `if` a future contributor can forget to write — it's structural, and a
test asserts the graph's next node is `submit` after a run. The checkpointer means a paused review is
resumable state rather than a live process.

**Rejected — a hand-rolled loop with a confirmation prompt.** The pause becomes a line of code
instead of a property of the graph.
**Rejected — two services with a queue between them** (explicitly out of scope in CLAUDE.md). One
container is the deliverable; a second service adds deployment surface and proves nothing extra.

**Cost.** `MemorySaver` loses state when the process dies. Postgres checkpointer is in the deferred list.

## Every boundary artefact is a Pydantic model

**Chosen.** `models.py` defines everything that crosses a node. Graph state holds
`model_dump(mode="json")` dicts; each node reconstructs what it needs.

**Why.** The model's output is untrusted text. Parsing it into a strict schema — and *rejecting*
what doesn't fit — is the first defence. `confidence: Field(ge=0, le=1)` means a model returning
1.5 never constructs. Everything downstream operates on validated objects.

**Rejected — dicts or dataclasses.** No validation at the exact boundary where validation matters.

**Cost.** Re-parsing on every node. It's cheap, and it's a free second validation.

**One modelling choice worth defending:** `EvidenceItem` carries *two* booleans — `present` (do we
hold this record?) and `supports_merchant` (does it help?). My first version collapsed them and was
wrong: a refund record that exists **wins** a 13.6 contest, while a subscription record showing the
charge came after cancellation **loses** a 13.2. Presence and helpfulness are orthogonal.

## The mock provider returns an empty string

**Chosen.** `MockProvider.complete()` returns `""`, which fails JSON parsing, which triggers the
heuristic recommender — the identical path a garbled live response takes.

**Why.** The offline demo path and the production-outage path are the same code. The fallback is
exercised on every mock run instead of rotting until the day it's needed.

**Rejected — canned per-dispute JSON responses.** Mock mode would then look plausible while never
testing the fallback, and the "the demo can't die on a model outage" claim would be untested.

**Related:** the heuristic recommender is deliberately **deadline-blind**. If it checked deadlines,
DSP008 would come out `escalate` from the model and the gate would have nothing to demonstrate.
Separation of concerns, made visible.

## Money is an integer in paise

**Chosen.** `amount_paise: int` everywhere; formatting happens only at display.

**Why.** Floating-point money in a payments system is the kind of thing an interviewer notices.

## The corpus is public regulator and network rules, not a gateway's documentation

**Chosen.** Twelve `##`-chunked passages paraphrased from the RBI turn-around-time circular and the
publicly documented Visa/Mastercard reason codes and time limits. Every source URL in the README.

**Why.** Three reasons. It's unambiguously public. It keeps a specific payment gateway's name and
content out of a public repo. And regulator-level material signals awareness of the actual compliance
frame, which lands harder at a payments company than vendor-specific docs.

**Rejected — copying a gateway's dispute docs.** Grey area on reuse, and it puts their brand in my repo.
**Rejected — inventing the rules.** The whole project is about grounding; a fabricated corpus would
undercut the one claim that matters. The passages were written from fetched sources, not from memory.

**Chunking on `##` headings** rather than fixed-size windows, so each passage is one self-contained
rule — which is what makes a verbatim quote from it meaningful to a reviewer, and makes the
`passage_id` in a citation human-readable.

## Five modules never import an LLM

**Chosen.** `tools.py`, `redaction.py`, `screening.py`, `policy.py`, `verifier.py` — enforced as an
invariant in CLAUDE.md.

**Why.** It's what lets "the security properties are deterministic" mean something concrete: those
properties live in ordinary functions with no sampling in them, unit-testable to exhaustion.

---

# Part 3 — What I'd change

Ordered by how much I'd want it, not by effort.

1. **LLM tool planning**, constrained to the same read-only toolbox, with `EVIDENCE_PLAN` as a floor
   rather than the whole story. The single biggest capability gap.
2. **Calibrate the confidence floor.** 0.70 is a number I chose. Self-reported LLM confidence is
   weakly calibrated; with outcome data it should be fitted, and probably differ per reason code.
3. **An auto-submit band.** The gate already computes everything needed to define one. It should be
   earned from production outcomes, never shipped on day one against an irreversible action.
4. **Authentication and roles.** The reviewer is currently a text field. Production needs SSO with
   analyst and approver as distinct roles — the person who drafts shouldn't be the person who files.
5. **Postgres** for the checkpointer and the audit trail, replacing `MemorySaver` and JSONL.
6. **LLM-as-judge on draft letter quality** — the one place where there's no ground truth to check
   against deterministically.
