"""
shared/keyword_bridge.py

Compatibility shim — provides the same get_keywords_for_listing() interface as
LQS/shared/keyword_bridge.py so asin_pipeline.py resolves `from shared.keyword_bridge`
when imported via the enrichment_api (where selleros_demos/shared/ wins in sys.modules).

Path note: __file__ here is selleros_demos/shared/keyword_bridge.py, so _SELLEROS_ROOT
is one level up (not two as in LQS/shared/keyword_bridge.py).
"""
from __future__ import annotations

import logging
import os
import re
import sys

logger = logging.getLogger(__name__)

_SELLEROS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _SELLEROS_ROOT not in sys.path:
    sys.path.insert(0, _SELLEROS_ROOT)

_SKIP = {"with", "for", "from", "this", "that", "have", "plus", "best", "also", "your"}


def _primary_from_title(title: str) -> str:
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
    Matches LQS/shared/keyword_bridge.get_keywords_for_listing() exactly.
    Called by LQS asin_pipeline.py (Step 2.5) to enrich ListingInput keywords.
    Returns ("", []) on any failure so the LQS pipeline degrades gracefully.
    """
    try:
        from keyword_gap.agents import run_keyword_gap_analysis

        result = run_keyword_gap_analysis(
            title=title,
            bullets=bullets,
            description=description,
            competitors=competitors or [],
            category=category,
            target_locale=target_locale,
        )

        critical = [i["keyword"] for i in result.get("missing_critical", []) if i.get("keyword")]
        secondary = [i["keyword"] for i in result.get("missing_secondary", []) if i.get("keyword")]
        secondary_kws = (critical + secondary)[:8]
        primary_kw = _primary_from_title(title)

        logger.debug("keyword_bridge: primary=%r  secondary=%s", primary_kw, secondary_kws)
        return primary_kw, secondary_kws

    except Exception as exc:
        logger.warning("keyword_bridge: gap analysis failed — %s", exc)
        return "", []
