import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISPUTEDESK_LLM_PROVIDER", "mock")
os.environ.setdefault("DISPUTEDESK_DENSE_RETRIEVAL", "0")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Fresh token registry and a throwaway audit file for every test."""
    from disputedesk import actions, audit
    actions.reset_registry()
    monkeypatch.setattr(audit, "AUDIT_DIR", tmp_path)
    monkeypatch.setattr(audit, "AUDIT_FILE", tmp_path / "reviews.jsonl")
    yield
    actions.reset_registry()
