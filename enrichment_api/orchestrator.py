"""
enrichment_api/orchestrator.py

Parallel orchestration for the AI Enrichment API.
All step functions fail gracefully — exceptions log a warning and return safe defaults.
"""
from __future__ import annotations

import logging
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Path priority: _ROOT first so selleros_demos/shared/ wins for shared.* imports
# (selleros_demos/shared/ now has llm_client.py + keyword_bridge.py shims for LQS).
# _COMP_ROOT enables `from src.services.*` imports in CompetitorAnalysis.
# _LQS is added inside run_lqs() so `config` resolves to LQS/config.py there.
_ROOT      = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_COMP_ROOT = os.path.join(_ROOT, "CompetitorAnalysis")
_LQS       = os.path.join(_ROOT, "LQS")

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _COMP_ROOT not in sys.path:
    sys.path.insert(0, _COMP_ROOT)

from shared.zyte_client import fetch_own_listing
from shared.s3_cache import get as cache_get, put as cache_put

_KG_PREFIX  = os.getenv("S3_RAW_PREFIX_KG",  "KeywordGap")
_TE_PREFIX  = os.getenv("S3_RAW_PREFIX_TE",  "TextEnhancement")
_LQS_PREFIX = os.getenv("S3_RAW_PREFIX_LQS", "LQS")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sanitize(obj):
    """Recursively replace NaN/Inf floats with None so json.dumps never chokes."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


# ── Step functions ─────────────────────────────────────────────────────────────

def fetch_listing(asin: str, marketplace: str = "IN") -> dict:
    return fetch_own_listing(asin, marketplace)


def run_competitors(asin: str, force_refresh: bool = False) -> list[dict]:
    try:
        from src.services.competitor_service import find_competitors  # _COMP_ROOT in sys.path
        result = find_competitors(asin)
        return _sanitize(result.get("competitors") or [])
    except Exception as exc:
        logger.warning("run_competitors(%s) failed — %s", asin, exc)
        return []


def _comp_summaries(comps: list[dict]) -> list[dict]:
    """Normalise CompetitorAnalysis competitor dicts to the shape keyword_gap/abd_optimizer expect."""
    return [
        {
            "title":       c.get("title", ""),
            "bullets":    (c.get("bullet_points") or c.get("bullets") or [])[:3],
            "description": (c.get("description") or "")[:300],
        }
        for c in comps
    ]


def run_keyword_gap(
    asin: str,
    listing: dict,
    comp_summaries: list[dict],
    force_refresh: bool = False,
) -> dict:
    if asin and not force_refresh:
        cached = cache_get(_KG_PREFIX, asin)
        if cached:
            return cached

    try:
        from keyword_gap.agents import run_keyword_gap_analysis
        result = run_keyword_gap_analysis(
            title=listing.get("title", ""),
            bullets=listing.get("bullets", []),
            description=listing.get("description", ""),
            competitors=comp_summaries,
            category=listing.get("leaf_category_name", "custom"),
            asin=asin,
        )
        if asin:
            cache_put(_KG_PREFIX, asin, result)
        return result
    except Exception as exc:
        logger.warning("run_keyword_gap(%s) failed — %s", asin, exc)
        return {}


def run_lqs(asin: str, country: str = "IN", force_refresh: bool = False) -> dict:
    """
    Direct Python call into LQS asin_pipeline.

    Results are cached under S3: LQS/{asin}/latest.json  (14-day TTL)
                                  LQS/{asin}/history/{ts}.json  (append-only)

    Pass force_refresh=True to bypass the cache and write a fresh snapshot.

    sys.path ordering ensures:
      - selleros_demos/shared/ (cached) → resolves shared.llm_client + shared.keyword_bridge via shims
      - LQS/ added here → resolves marketplaces.*, lqs_pipeline.*, config (LQS/config.py)
      - CompetitorAnalysis/config/ has no __init__.py → namespace portion, LQS/config.py wins
    """
    if asin and not force_refresh:
        cached = cache_get(_LQS_PREFIX, asin)
        if cached:
            return cached

    try:
        if _LQS not in sys.path:
            sys.path.append(_LQS)
        from marketplaces.amazon.asin_pipeline import run as lqs_run
        result = _sanitize(lqs_run(asin, country))
        if asin and result:
            cache_put(_LQS_PREFIX, asin, result)
        return result
    except Exception as exc:
        logger.warning("run_lqs(%s) failed — %s", asin, exc)
        return {}


def get_a9_context(listing: dict) -> dict:
    """Run the deterministic A9 scorer via integration_bridge (no LLM)."""
    try:
        from abd_optimizer.integration_bridge import get_lqs_scores
        return get_lqs_scores(
            title=listing.get("title", ""),
            bullets=listing.get("bullets", []),
            description=listing.get("description", ""),
        )
    except Exception as exc:
        logger.warning("get_a9_context failed — %s", exc)
        return {}


def _lqs_context_for_enhance(lqs_result: dict, kw_result: dict) -> dict:
    """
    Build the lqs_context dict for run_enhance from already-computed LQS and
    keyword gap results.  Using the real pipeline scores avoids asking Claude to
    re-score the original listing in Pass 1, which would produce divergent values.

    Falls back gracefully — if a field is missing the key is omitted so
    run_ab_optimization keeps its existing fallback behaviour.
    """
    target = next(
        (r for r in lqs_result.get("results", []) if r.get("label") == "TARGET"),
        {},
    )
    scores = target.get("scores", {})

    ctx: dict = {}
    if scores.get("a9_compliance") is not None:
        ctx["a9_score"] = scores["a9_compliance"]
    if scores.get("rufus_readiness") is not None:
        ctx["rufus_readiness"] = scores["rufus_readiness"]
    # seller_keywords is the deterministic set already present in the listing
    seller_kws = kw_result.get("seller_keywords", [])
    if seller_kws:
        ctx["keywords_found"] = len(seller_kws)
    if target.get("flags"):
        ctx["flags"] = target["flags"]
    return ctx


def _extract_missing_keywords(kw_result: dict) -> list[str]:
    critical  = [i["keyword"] for i in kw_result.get("missing_critical",  []) if i.get("keyword")]
    secondary = [i["keyword"] for i in kw_result.get("missing_secondary", []) if i.get("keyword")]
    return (critical + secondary)[:10]


def run_enhance(
    asin: str,
    listing: dict,
    comp_summaries: list[dict],
    a9_context: dict,
    missing_keywords: list[str],
    force_refresh: bool = False,
) -> dict:
    if asin and not force_refresh:
        cached = cache_get(_TE_PREFIX, asin)
        if cached:
            return cached

    try:
        from abd_optimizer.agents import run_ab_optimization
        result = run_ab_optimization(
            title=listing.get("title", ""),
            bullets=listing.get("bullets", []),
            description=listing.get("description", ""),
            category=listing.get("leaf_category_name", "electronics"),
            competitor_context=comp_summaries or None,
            lqs_context=a9_context or None,
            missing_keywords=missing_keywords or None,
        )
        if asin:
            cache_put(_TE_PREFIX, asin, result)
        return result
    except Exception as exc:
        logger.warning("run_enhance(%s) failed — %s", asin, exc)
        return {}


# ── Main orchestrator ──────────────────────────────────────────────────────────

def run_enrich(
    asin: str,
    country: str = "IN",
    steps: list[str] | None = None,
    force_refresh: bool = False,
) -> dict:
    """
    Orchestrated enrichment pipeline with parallel phases.

    Phase 1 (parallel):  fetch_own_listing + find_competitors
    Phase 2 (parallel):  keyword_gap + a9_score + full_lqs_pipeline
    Phase 3 (sequential): abd_enhance  (consumes Phase 2 outputs)
    """
    steps_set = set(steps or ["competitors", "keywords", "lqs", "enhance"])
    t0 = time.perf_counter()

    # Phase 1 — fetch listing + competitors in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_listing = pool.submit(fetch_listing, asin, country)
        f_comps   = pool.submit(run_competitors, asin, force_refresh) if "competitors" in steps_set else None

    listing   = f_listing.result()
    comps     = (f_comps.result() if f_comps else []) or []
    summaries = _comp_summaries(comps)

    # Phase 2 — keyword gap + full LQS in parallel
    # (a9_context is derived from lqs_result after this phase — no extra call needed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_kw  = pool.submit(run_keyword_gap, asin, listing, summaries, force_refresh) if "keywords" in steps_set else None
        f_lqs = pool.submit(run_lqs, asin, country, force_refresh)                     if "lqs"      in steps_set else None

    kw_result  = (f_kw.result()  if f_kw  else {}) or {}
    lqs_result = (f_lqs.result() if f_lqs else {}) or {}

    # Build lqs_context for Enhancement from the real LQS + keyword gap scores.
    # If LQS wasn't requested, fall back to the deterministic-only A9 scorer.
    if "enhance" in steps_set:
        if lqs_result:
            a9_context = _lqs_context_for_enhance(lqs_result, kw_result)
        else:
            a9_context = get_a9_context(listing)
    else:
        a9_context = {}

    missing_kws = _extract_missing_keywords(kw_result)

    # Phase 3 — text enhancement (sequential, uses Phase 2 outputs)
    enhance_result = (
        run_enhance(asin, listing, summaries, a9_context, missing_kws, force_refresh)
        if "enhance" in steps_set else {}
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    return {
        "asin":        asin,
        "listing":     listing,
        "competitors": comps,
        "keyword_gap": kw_result,
        "lqs":         lqs_result,
        "enhancement": enhance_result,
        "meta": {
            "cached":            False,
            "elapsed_ms":        elapsed_ms,
            "competitors_count": len(comps),
            "keywords_injected": len(missing_kws),
            "steps_run":         sorted(steps_set),
        },
    }
