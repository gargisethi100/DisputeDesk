"""llm.py — model providers. The ONLY module (with analysis.py) that talks to a model.

  BedrockProvider  Claude via Amazon Bedrock `converse`. Auth is IAM (env creds, profile,
                   or the ECS task role) — there is no API key in the codebase.
  MockProvider     Returns an empty completion. `analysis.recommend` treats that exactly
                   like a malformed model reply and takes the heuristic path, so mock mode
                   exercises the same fallback a production outage would.

`get_provider()` reads DISPUTEDESK_LLM_PROVIDER (default: mock).
"""
from __future__ import annotations

import os
from typing import Protocol

from dotenv import load_dotenv

try:                                    # corporate SSL-inspection proxies: trust the OS store
    import truststore
    truststore.inject_into_ssl()
except Exception:                       # pragma: no cover
    pass

load_dotenv()


class LLMProvider(Protocol):
    name: str
    last_usage: dict

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str: ...


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self.last_usage: dict = {}

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        return ""                       # -> schema validation fails -> heuristic fallback


class BedrockProvider:
    name = "bedrock"

    def __init__(self) -> None:
        import boto3                    # imported lazily so mock mode needs no AWS SDK setup
        self.model_id = os.environ["BEDROCK_MODEL_ID"]
        self.region = os.getenv("AWS_REGION", "ap-south-1")
        self._client = boto3.client("bedrock-runtime", region_name=self.region)
        self.last_usage: dict = {}

    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        resp = self._client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.0},
        )
        self.last_usage = resp.get("usage", {})
        return "".join(part.get("text", "") for part in resp["output"]["message"]["content"])


def get_provider() -> LLMProvider:
    kind = os.getenv("DISPUTEDESK_LLM_PROVIDER", "mock").lower()
    if kind == "bedrock":
        return BedrockProvider()
    if kind == "mock":
        return MockProvider()
    raise ValueError(f"unknown DISPUTEDESK_LLM_PROVIDER={kind!r} (use mock | bedrock)")
