"""
marketplaces/amazon/lqs.py

AmazonLQSScorer — implements BaseLQSScorer for the Amazon marketplace.

Two-pass scoring:
  Pass 1 (A9)    — deterministic, amazon/a9_scorer.py
  Pass 2 (Rufus) — LLM-evaluated, amazon/rufus_scorer.py

lqs_score sources (in priority order):
  1. listing.lqs_score_override  — caller passes the score from pipeline.predict_lqs()
  2. _content_lqs(listing)       — text-based quality heuristic (standalone fallback)

Overall score = a9×0.40 + rufus×0.35 + lqs×0.25  (per d1_lqs.md spec)
"""
from __future__ import annotations

import math

from marketplaces.base_lqs import BaseLQSScorer, ListingInput, LQSOutput
from marketplaces.amazon.a9_scorer import score_a9
from marketplaces.amazon.rufus_scorer import score_rufus, score_rufus_slim


# ── GMV / CTR projection tables ───────────────────────────────────────────────

# (min_score, max_score): (ctr_range_str, ctr_delta_low, ctr_delta_high, cvr_delta_low, cvr_delta_high)
_SCORE_BANDS = [
    (85, 100, "3.5–5.5%", 0.30, 0.60, 0.20, 0.45),
    (70,  84, "2.5–4.0%", 0.15, 0.35, 0.10, 0.25),
    (55,  69, "1.5–2.8%", 0.05, 0.18, 0.03, 0.15),
    (0,   54, "0.8–1.8%", 0.00, 0.05, 0.00, 0.05),
]

_VISITS: int = 500       # daily page visits (default assumption)
_AOV: float = 1850.0     # average order value, INR
_BASE_CTR: float = 0.025
_BASE_CVR: float = 0.020


def _gmv_range(overall: int) -> tuple[str, str]:
    """Return (projected_ctr_range, gmv_impact_inr)."""
    band = _SCORE_BANDS[-1]
    for lo, hi, ctr_str, cdl, cdh, vdl, vdh in _SCORE_BANDS:
        if lo <= overall <= hi:
            band = (lo, hi, ctr_str, cdl, cdh, vdl, vdh)
            break
    _, _, ctr_str, cdl, cdh, vdl, vdh = band  # type: ignore[misc]

    gmv_low  = _VISITS * _BASE_CTR * _BASE_CVR * _AOV * 30
    gmv_high = (
        _VISITS
        * (_BASE_CTR * (1 + cdh))
        * (_BASE_CVR * (1 + vdh))
        * _AOV
        * 30
    )

    def _fmt(v: float) -> str:
        return f"₹{v:,.0f}"

    return ctr_str, f"{_fmt(gmv_low)}–{_fmt(gmv_high)}/month"


# ── A9 flag → fix-priority mapping ────────────────────────────────────────────

_A9_FLAG_FIXES: dict[str, dict] = {
    "CRITICAL_KW_MISS": {
        "dimension": "a9.title_keyword",
        "impact_score": 95,
        "fix_suggestion": "Add your primary keyword to the title immediately — its absence means Amazon won't index this listing for that query.",
    },
    "BROWSE_NODE_MISSING": {
        "dimension": "a9.browse_node",
        "impact_score": 90,
        "fix_suggestion": "Set a specific browse node with at least 2 hierarchy levels (e.g. 'Electronics/Headphones/In-Ear') to enable category indexation.",
    },
    "BACKEND_OVER_BYTE_LIMIT": {
        "dimension": "a9.backend_keywords",
        "impact_score": 85,
        "fix_suggestion": "Trim backend search terms to ≤249 bytes — Amazon ignores the entire field when it exceeds the limit.",
    },
    "TITLE_TOO_LONG": {
        "dimension": "a9.title_structure",
        "impact_score": 70,
        "fix_suggestion": "Trim title to ≤200 characters. Remove filler phrases; keep Brand + primary KW + top 2 spec attributes.",
    },
    "TOO_FEW_BULLETS": {
        "dimension": "a9.bullet_compliance",
        "impact_score": 65,
        "fix_suggestion": "Add bullets to reach exactly 5. Each missing bullet forfeits A9 keyword indexation opportunities and reduces Rufus context.",
    },
    "MOBILE_KEYWORD_MISSING": {
        "dimension": "a9.mobile_optimisation",
        "impact_score": 60,
        "fix_suggestion": "Move the primary keyword to the first 80 characters of the title — 70% of Amazon traffic is mobile and truncates there.",
    },
    "KEYWORD_AFTER_WORD_10": {
        "dimension": "a9.title_keyword",
        "impact_score": 55,
        "fix_suggestion": "Reposition the primary keyword within the first 5 words of the title for maximum A9 indexation weight.",
    },
    "BACKEND_UNDERUTILISED": {
        "dimension": "a9.backend_keywords",
        "impact_score": 40,
        "fix_suggestion": "Expand backend search terms to use at least 200 of the 249 available bytes with non-duplicate, complementary terms.",
    },
    "TITLE_UNDER_OPTIMISED": {
        "dimension": "a9.title_structure",
        "impact_score": 35,
        "fix_suggestion": "Extend title to 80–200 characters. Include brand, primary keyword, product type, and at least one spec attribute.",
    },
    "KEYWORD_STUFFED_TITLE": {
        "dimension": "a9.title_structure",
        "impact_score": 50,
        "fix_suggestion": "Add natural-language connectors between keywords. A9 penalises titles with fewer than 8% function words.",
    },
    "BACKEND_HAS_DUPLICATES": {
        "dimension": "a9.backend_keywords",
        "impact_score": 25,
        "fix_suggestion": "Remove repeated words from backend search terms — duplicates waste your byte budget without indexation benefit.",
    },
    "BROWSE_NODE_TOO_BROAD": {
        "dimension": "a9.browse_node",
        "impact_score": 30,
        "fix_suggestion": "Use a leaf-level browse node with ≥2 hierarchy levels rather than just the top-level category.",
    },
    "NO_ATTRIBUTES": {
        "dimension": "a9.attribute_completeness",
        "impact_score": 20,
        "fix_suggestion": "Populate structured product attributes (colour, size, model) to improve variation indexation.",
    },
}


def _a9_fix_priority(flags: list[str]) -> list[dict]:
    fixes = []
    for flag in flags:
        base_flag = flag.split(":")[0]  # strip e.g. "SUPERLATIVE_FOUND:best"
        if base_flag in _A9_FLAG_FIXES:
            entry = {"issue": base_flag, **_A9_FLAG_FIXES[base_flag]}
            fixes.append(entry)
    fixes.sort(key=lambda x: x["impact_score"], reverse=True)
    return fixes[:5]


# ── text-based LQS heuristic (fallback when no ML score is provided) ───────────

def _content_lqs(listing: ListingInput) -> int:
    """
    Lightweight content-quality score (0–100) used when the caller has not
    provided a lqs_score_override from the existing ML pipeline.

    This is intentionally simpler than the ML model — it measures listing
    completeness rather than predicted market performance.
    """
    s = 0.0

    # Title (20 pts)
    tl = len(listing.title)
    if 80 <= tl <= 200:
        s += 20
    elif tl >= 50:
        s += 10
    elif tl >= 30:
        s += 5

    # Bullets (20 pts)
    non_empty = [b for b in listing.bullets if b.strip()]
    s += min(len(non_empty) * 4, 20)

    # Description (15 pts)
    dl = len(listing.description.strip())
    if dl >= 500:
        s += 15
    elif dl >= 100:
        s += 10
    elif dl >= 50:
        s += 5

    # A+ content (10 pts)
    if listing.aplus_content and listing.aplus_content.strip():
        s += 10

    # Backend keywords (15 pts)
    if listing.backend_keywords:
        bk = len(listing.backend_keywords.encode("utf-8"))
        if bk >= 200:
            s += 15
        elif bk >= 100:
            s += 8
        elif bk >= 50:
            s += 4

    # Images (10 pts)
    s += min(len(listing.images) * 2, 10)

    # Attributes (10 pts)
    na = len(listing.attributes)
    if na >= 5:
        s += 10
    elif na >= 3:
        s += 6
    elif na >= 1:
        s += 3

    return min(100, int(round(s)))


# ── scorer ─────────────────────────────────────────────────────────────────────

class AmazonLQSScorer(BaseLQSScorer):
    """
    Amazon marketplace LQS scorer.

    Usage:
        from marketplaces.amazon import AmazonLQSScorer
        from marketplaces.base_lqs import ListingInput

        scorer = AmazonLQSScorer()
        result = scorer.score(ListingInput(title="...", bullets=[...], ...))
        print(result.to_dict())

    To integrate with the existing ML pipeline score:
        listing = ListingInput(..., lqs_score_override=int(ml_lqs_score))
        result = scorer.score(listing)
    """

    platform = "amazon"

    def score_for_comparison(self, listing: ListingInput) -> LQSOutput:
        """
        Competitor scoring — full A9 pass + slim Rufus (scores only, no fix suggestions).
        Saves ~400 output tokens per competitor vs the full score() call.
        Returns complete scores and dimension_breakdown; flags/fix_priority are A9-only.
        """
        listing.validate()

        a9 = score_a9(
            title=listing.title, bullets=listing.bullets,
            description=listing.description, backend_keywords=listing.backend_keywords,
            browse_node=listing.browse_node, brand=listing.brand,
            category=listing.category, aplus_content=listing.aplus_content,
            attributes=listing.attributes, primary_keyword=listing.primary_keyword,
            secondary_keywords=listing.secondary_keywords,
        )
        rufus = score_rufus_slim(
            title=listing.title, bullets=listing.bullets,
            description=listing.description, qa_pairs=listing.qa_pairs,
            review_summary=listing.review_summary, aplus_content=listing.aplus_content,
            a9_flags=a9.flags,
        )

        lqs_score = (
            listing.lqs_score_override
            if listing.lqs_score_override is not None
            else _content_lqs(listing)
        )
        lqs_score = max(0, min(100, lqs_score))

        overall = max(0, min(100, int(
            a9.score * 0.40 + rufus.score * 0.35 + lqs_score * 0.25
        )))
        ctr_range, gmv_range = _gmv_range(overall)

        return LQSOutput(
            scores={
                "a9_compliance":   a9.score,
                "rufus_readiness": rufus.score,
                "lqs_score":       lqs_score,
                "overall":         overall,
            },
            dimension_breakdown={"a9": a9.breakdown, "rufus": rufus.breakdown},
            flags=[],        # scores only — no flags for competitors
            fix_priority=[],  # scores only — no fixes for competitors
            projected_ctr_range=ctr_range,
            gmv_impact_inr=gmv_range,
        )

    def score(self, listing: ListingInput) -> LQSOutput:
        listing.validate()

        # ── Pass 1: A9 (deterministic) ─────────────────────────────────────
        a9 = score_a9(
            title=listing.title,
            bullets=listing.bullets,
            description=listing.description,
            backend_keywords=listing.backend_keywords,
            browse_node=listing.browse_node,
            brand=listing.brand,
            category=listing.category,
            aplus_content=listing.aplus_content,
            attributes=listing.attributes,
            primary_keyword=listing.primary_keyword,
            secondary_keywords=listing.secondary_keywords,
        )

        # ── Pass 2: Rufus (LLM) ────────────────────────────────────────────
        rufus = score_rufus(
            title=listing.title,
            bullets=listing.bullets,
            description=listing.description,
            qa_pairs=listing.qa_pairs,
            review_summary=listing.review_summary,
            aplus_content=listing.aplus_content,
            a9_flags=a9.flags,
        )

        # ── lqs_score: ML pipeline override or content heuristic ────────────
        lqs_score = (
            listing.lqs_score_override
            if listing.lqs_score_override is not None
            else _content_lqs(listing)
        )
        lqs_score = max(0, min(100, lqs_score))

        # ── Overall weighted score ──────────────────────────────────────────
        overall = max(0, min(100, int(
            a9.score    * 0.40 +
            rufus.score * 0.35 +
            lqs_score   * 0.25
        )))

        # ── Fix priority: merge A9 deterministic + Rufus LLM ───────────────
        a9_fixes  = _a9_fix_priority(a9.flags)
        all_fixes = a9_fixes + rufus.fix_priority
        # Re-sort combined list by impact_score, keep top 5
        all_fixes.sort(key=lambda x: x.get("impact_score", 0), reverse=True)
        top_fixes = all_fixes[:5]

        # ── Flags: combine A9 + Rufus, critical flags first ────────────────
        critical = {"CRITICAL_KW_MISS", "BROWSE_NODE_MISSING", "BACKEND_OVER_BYTE_LIMIT"}
        high     = {"TITLE_TOO_LONG", "TOO_FEW_BULLETS", "MOBILE_KEYWORD_MISSING"}

        def _severity(flag: str) -> int:
            base = flag.split(":")[0]
            if base in critical: return 0
            if base in high:     return 1
            return 2

        combined_flags = a9.flags + rufus.flags
        seen: set[str] = set()
        ordered_flags = []
        for f in sorted(combined_flags, key=_severity):
            if f not in seen:
                seen.add(f)
                ordered_flags.append(f)

        # ── GMV / CTR projections ───────────────────────────────────────────
        ctr_range, gmv_range = _gmv_range(overall)

        return LQSOutput(
            scores={
                "a9_compliance":   a9.score,
                "rufus_readiness": rufus.score,
                "lqs_score":       lqs_score,
                "overall":         overall,
            },
            dimension_breakdown={
                "a9":    a9.breakdown,
                "rufus": rufus.breakdown,
            },
            flags=ordered_flags,
            fix_priority=top_fixes,
            projected_ctr_range=ctr_range,
            gmv_impact_inr=gmv_range,
        )
