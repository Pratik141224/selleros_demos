"""
shared/keyword_bridge.py

Bridge: calls the selleros_demos keyword_gap module to derive
primary_keyword + secondary_keywords for LQS ListingInput enrichment.

Designed to fail gracefully — any exception returns ("", []) so the
LQS pipeline continues with auto-extracted keywords as fallback.
"""
from __future__ import annotations

import logging
import os
import re
import sys

logger = logging.getLogger(__name__)

# Ensure selleros_demos root is on sys.path so keyword_gap.agents can resolve
# its own `from shared.llm_router import ...` import correctly.
_SELLEROS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SELLEROS_ROOT not in sys.path:
    sys.path.insert(0, _SELLEROS_ROOT)

_SKIP = {"with", "for", "from", "this", "that", "have", "plus", "best", "also", "your"}


def _primary_from_title(title: str) -> str:
    """Deterministically extract the two most likely primary keyword tokens from a title."""
    words = [
        w for w in re.findall(r'\b[a-z][a-z0-9]*\b', title.lower())
        if len(w) > 3 and w not in _SKIP
    ]
    if len(words) >= 2:
        return f"{words[0]} {words[1]}"
    return words[0] if words else ""


def get_keywords_for_listing(
    title: str,
    bullets: list[str],
    description: str = "",
    competitors: list[dict] | None = None,
    category: str = "electronics",
    target_locale: str = "IN",
) -> tuple[str, list[str]]:
    """
    Call keyword_gap.agents.run_keyword_gap_analysis() and extract
    (primary_keyword, secondary_keywords) for injection into ListingInput.

    primary_keyword  — deterministically extracted from the listing title.
    secondary_keywords — up to 8 gap keywords from missing_critical +
                         missing_secondary in the gap analysis output.

    Returns ("", []) on any failure so the caller can degrade gracefully.
    """
    try:
        from keyword_gap.agents import run_keyword_gap_analysis  # late import (heavy)

        result = run_keyword_gap_analysis(
            title=title,
            bullets=bullets,
            description=description,
            competitors=competitors or [],
            category=category,
            target_locale=target_locale,
        )

        critical = [
            item["keyword"]
            for item in result.get("missing_critical", [])
            if item.get("keyword")
        ]
        secondary_raw = [
            item["keyword"]
            for item in result.get("missing_secondary", [])
            if item.get("keyword")
        ]
        secondary_kws = (critical + secondary_raw)[:8]
        primary_kw = _primary_from_title(title)

        logger.debug(
            "keyword_bridge: primary=%r  secondary=%s",
            primary_kw, secondary_kws,
        )
        return primary_kw, secondary_kws

    except Exception as exc:
        logger.warning("keyword_bridge: gap analysis failed — %s", exc)
        return "", []
