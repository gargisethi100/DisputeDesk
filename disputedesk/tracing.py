"""tracing.py — optional Langfuse tracing on the two model calls only (recommend, draft).

No-op unless LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are set and `langfuse` is installed.
Deterministic nodes are not traced: they have nothing to measure but wall-clock, and the
audit log already records their outputs. Tracing exists to answer "what did the model cost
and how long did it take", per run.
"""
from __future__ import annotations

import functools
import os
import time

_client = None   # None = not initialised, False = unavailable


def _lf():
    global _client
    if _client is None:
        if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import Langfuse
                _client = Langfuse()
            except Exception as e:                       # pragma: no cover
                print(f"[tracing] langfuse unavailable: {e}")
                _client = False
        else:
            _client = False
    return _client or None


def traced(name: str):
    """Wrap a function whose first argument is an LLMProvider."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(provider, *args, **kwargs):
            t0 = time.perf_counter()
            out = fn(provider, *args, **kwargs)
            lf = _lf()
            if lf:
                meta = {"provider": getattr(provider, "name", "?"), "latency_ms": round((time.perf_counter() - t0) * 1000),
                        "model": getattr(provider, "model_id", None), "result": getattr(out, "source", None)}
                usage = getattr(provider, "last_usage", {}) or {}
                try:                                                   # langfuse v3
                    gen = lf.start_generation(name=name, model=meta["model"], metadata=meta)
                    gen.update(usage_details={"input": usage.get("inputTokens", 0), "output": usage.get("outputTokens", 0)})
                    gen.end()
                except AttributeError:                                 # langfuse v2
                    lf.trace(name=name, metadata={**meta, "usage": usage})
                lf.flush()
            return out
        return wrapper
    return deco
