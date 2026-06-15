"""
shared/llm_client.py

Thin Anthropic SDK wrapper used by all marketplace LLM passes.
Handles JSON extraction from the model response so callers only
deal with plain dicts.
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
                "ANTHROPIC_API_KEY is not set. "
                "Export it before running any LLM-based scorer."
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _extract_json(text: str) -> dict:
    """Strip markdown fences if present, then parse JSON."""
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
    Call the Anthropic API and return a parsed JSON dict.

    Raises:
        json.JSONDecodeError   — if the model returns malformed JSON
        anthropic.APIError     — on API-level failures
        EnvironmentError       — if ANTHROPIC_API_KEY is missing
    """
    msg = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = msg.content[0].text
    return _extract_json(raw)
