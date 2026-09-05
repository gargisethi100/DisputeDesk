"""audit.py — persistent audit trail: one JSON line per completed review.

Business logic uses the frozen clock (`state["now"]`). The audit writer is the one
place a wall-clock timestamp is allowed, because "when was this written" is a fact
about the log, not about the dispute.

In production this becomes an append-only table; JSONL keeps the demo dependency-free.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path(os.getenv("DISPUTEDESK_AUDIT_DIR", "audit"))
AUDIT_FILE = AUDIT_DIR / "reviews.jsonl"


def write_review_record(record: dict) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    record = {"written_at": datetime.now(timezone.utc).isoformat(), **record}
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return AUDIT_FILE


def read_review_records(limit: int = 50) -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines[-limit:] if l.strip()]
