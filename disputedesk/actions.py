"""actions.py — the ONE side-effecting call in the codebase, and the token that gates it.

  mint_token      only from an approve/edit ReviewDecision. A reject has no code path here.
  submit_dispute_response
                  requires an ApprovalToken whose digest matches (dispute, reviewer, body).
                  A token is spent on first use; a second call with the same token returns the
                  original receipt marked duplicate_suppressed — nothing is filed twice.

The digest doubles as the idempotency key. Forging a token means forging a SHA-256 over
content the reviewer approved; tampering with the body after approval invalidates it.
Registries are in-memory for the demo (production: a table with a unique constraint).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from .models import Action, ApprovalToken, ReviewDecision, SubmissionReceipt


class TokenError(PermissionError):
    pass


_SPENT: dict[str, SubmissionReceipt] = {}     # digest -> receipt of the first (only) submission


def _digest(dispute_id: str, reviewer: str, body: str) -> str:
    return hashlib.sha256(f"{dispute_id}\x1f{reviewer}\x1f{body}".encode("utf-8")).hexdigest()


def mint_token(decision: ReviewDecision, dispute_id: str, final_body: str, now: datetime) -> ApprovalToken:
    if decision.decision == "reject":
        raise TokenError("a rejection cannot mint an approval token")
    if not decision.reviewer:
        raise TokenError("reviewer identity is required to mint a token")
    return ApprovalToken(
        token_id=str(uuid.uuid4()), dispute_id=dispute_id, reviewer=decision.reviewer,
        digest=_digest(dispute_id, decision.reviewer, final_body), issued_at=now)


def submit_dispute_response(token: ApprovalToken, dispute_id: str, action: Action, body: str,
                            now: datetime) -> SubmissionReceipt:
    if not isinstance(token, ApprovalToken):
        raise TokenError("submission requires an ApprovalToken")
    if token.dispute_id != dispute_id:
        raise TokenError("token was issued for a different dispute")
    if token.digest != _digest(dispute_id, token.reviewer, body):
        raise TokenError("token does not match the content being submitted")
    if token.digest in _SPENT:
        prior = _SPENT[token.digest]
        return prior.model_copy(update={"status": "duplicate_suppressed"})

    # ---- the write. Mocked: a real integration replaces this block only.
    receipt = SubmissionReceipt(dispute_id=dispute_id, action=action, idempotency_key=token.digest,
                                submitted_at=now, status="submitted")
    _SPENT[token.digest] = receipt
    return receipt


def reset_registry() -> None:
    """Tests only."""
    _SPENT.clear()
