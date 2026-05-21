"""
shared/claude_client.py
Reusable Anthropic API wrapper for both demos.
"""

import os
import json
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()


def get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY not set. "
            "Run: export ANTHROPIC_API_KEY=sk-ant-your-key-here"
        )
    return anthropic.Anthropic(api_key=api_key)


def call_claude(system: str, user: str, max_tokens: int = 4096) -> dict:
    """
    Make a single Claude API call.
    Returns parsed JSON dict or raises ValueError if response isn't valid JSON.
    """
    client = get_client()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[
            {
                "role": "user",
                "content": user
            }
        ]
    )

    raw_text = "".join(
        block.text for block in message.content
        if hasattr(block, "text")
    )

    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()
    # Remove trailing fence
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned non-JSON response.\n"
            f"Error: {e}\n"
            f"Raw response (first 500 chars):\n{raw_text[:500]}"
        )
