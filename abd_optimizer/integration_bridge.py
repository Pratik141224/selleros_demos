"""
abd_optimizer/integration_bridge.py

Bridges to LQS and Keyword Gap for pre-fetching data before ABD optimization.

Both functions fail gracefully — any exception returns an empty default so
run_ab_optimization() continues unaffected.

LQS bridge  : loads a9_scorer.py directly via importlib (no package __init__)
              to avoid the rufus_scorer → LQS/shared/llm_client import chain.
              Returns a9 compliance score and flags from the current listing.

Keyword Gap : calls run_keyword_gap_analysis() via direct Python import.
              Identical pattern to LQS/shared/keyword_bridge.py.
              Returns up to 10 missing keywords (critical + secondary).
"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys

logger = logging.getLogger(__name__)

_SELLEROS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_LQS_ROOT      = os.path.join(_SELLEROS_ROOT, "LQS")

# SELLEROS_ROOT uses insert(0) so selleros_demos/shared/ takes precedence over
# LQS/shared/ when resolving `shared.*` imports (both dirs have a shared/ package).
if _SELLEROS_ROOT not in sys.path:
    sys.path.insert(0, _SELLEROS_ROOT)
# LQS_ROOT uses append so it has lower priority than SELLEROS_ROOT.
if _LQS_ROOT not in sys.path:
    sys.path.append(_LQS_ROOT)


_A9_SCORER_PATH = os.path.join(_LQS_ROOT, "marketplaces", "amazon", "a9_scorer.py")


def _load_score_a9():
    """Load score_a9 directly from a9_scorer.py — bypasses package __init__ so
    rufus_scorer.py (which imports LQS/shared/llm_client) is never loaded.

    Module must be registered in sys.modules before exec_module so that the
    @dataclass decorator can resolve cls.__module__ via sys.modules lookup.
    """
    spec = importlib.util.spec_from_file_location("_lqs_a9_scorer", _A9_SCORER_PATH)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.score_a9


# ── LQS bridge ────────────────────────────────────────────────────────────────

def get_lqs_scores(
    title: str,
    bullets: list[str],
    description: str = "",
    category: str = "electronics",
    backend_keywords: str = "",
    brand: str = "",
    primary_keyword: str = "",
    secondary_keywords: list[str] | None = None,
) -> dict:
    """
    Run the deterministic A9 scorer (no LLM) and return the current listing's
    compliance score and flags.

    Returns:
        {"a9_score": int, "flags": list[str]}  on success
        {}                                       on any failure
    """
    try:
        score_a9 = _load_score_a9()

        result = score_a9(
            title=title,
            bullets=bullets,
            description=description,
            backend_keywords=backend_keywords,
            brand=brand,
            category=category,
            primary_keyword=primary_keyword,
            secondary_keywords=secondary_keywords or [],
        )

        logger.debug("LQS bridge: a9_score=%d  flags=%s", result.score, result.flags)
        return {
            "a9_score": result.score,
            "flags":    result.flags,
        }

    except Exception as exc:
        logger.warning("LQS bridge: a9 scoring failed — %s", exc)
        return {}


# ── Keyword Gap bridge ─────────────────────────────────────────────────────────

def get_missing_keywords(
    title: str,
    bullets: list[str],
    description: str = "",
    competitors: list[dict] | None = None,
    category: str = "electronics",
    target_locale: str = "IN",
    asin: str = "",
) -> list[str]:
    """
    Call keyword_gap.agents.run_keyword_gap_analysis() and return up to 10
    missing keywords (critical first, then secondary) for injection into ABD prompts.

    Pass asin so the keyword gap agent can auto-fetch competitor listings from
    CompetitorAnalysis when no competitor_context is supplied.

    Returns [] on any failure.
    """
    try:
        from keyword_gap.agents import run_keyword_gap_analysis  # late import

        result = run_keyword_gap_analysis(
            title=title,
            bullets=bullets,
            description=description,
            competitors=competitors or [],
            category=category,
            target_locale=target_locale,
            asin=asin,
        )

        critical  = [i["keyword"] for i in result.get("missing_critical",  []) if i.get("keyword")]
        secondary = [i["keyword"] for i in result.get("missing_secondary", []) if i.get("keyword")]
        keywords  = (critical + secondary)[:10]

        logger.debug("Keyword Gap bridge: %d keywords — %s", len(keywords), keywords)
        return keywords

    except Exception as exc:
        logger.warning("Keyword Gap bridge: gap analysis failed — %s", exc)
        return []
