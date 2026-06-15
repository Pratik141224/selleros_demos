"""
shared/llm_client.py

Compatibility shim — provides the same call_json() interface as LQS/shared/llm_client.py
so LQS internal scorers (rufus_scorer.py) can resolve `from shared.llm_client import call_json`
when imported via the enrichment_api (where selleros_demos/shared/ wins in sys.modules).
"""
from __future__ import annotations

import json
import os
import re

import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. Required by LQS Rufus scorer."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def call_json(
    system: str,
    user: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2000,
) -> dict:
    """
    Matches LQS/shared/llm_client.call_json() exactly.
    Called by LQS rufus_scorer.py for Rufus readiness scoring.
    """
    msg = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = msg.content[0].text
    return _extract_json(raw)
