"""
marketplaces/amazon/asin_pipeline.py

Full ASIN-driven Amazon marketplace LQS pipeline:

  1. Ingest  — fetch target + competitor raw Zyte dicts via Ingestion.ingest()
  2. Map     — convert each Zyte dict → ListingInput via ZyteMapper (field_map.yaml)
  3. Score   — run AmazonLQSScorer on target and each competitor (competitors in parallel)
  4. Insights — generate gap report, dimension gaps, and seller feedback

The pipeline reuses all existing Zyte + competitor-discovery infrastructure.
Only the scoring layer is new.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from lqs_pipeline.Ingestion import ingest
from marketplaces.amazon.lqs import AmazonLQSScorer
from marketplaces.amazon.lqs_insights import generate_marketplace_insights
from marketplaces.amazon.zyte_mapper import map_zyte_to_listing_input
from marketplaces.base_lqs import ListingInput, LQSOutput
from shared.keyword_bridge import get_keywords_for_listing

logger = logging.getLogger(__name__)

_scorer = AmazonLQSScorer()


# ── internal helpers ───────────────────────────────────────────────────────────

def _score_one(label: str, asin: str, title: str, listing: ListingInput) -> dict:
    """Full scoring (A9 + Rufus with fix suggestions). Used for TARGET only."""
    result: LQSOutput = _scorer.score(listing)
    return {"label": label, "asin": asin, "title": title, **result.to_dict()}


def _score_competitor(label: str, asin: str, title: str, listing: ListingInput) -> dict:
    """Slim scoring (A9 + Rufus scores only, no fix suggestions). Saves ~400 output tokens per competitor."""
    result: LQSOutput = _scorer.score_for_comparison(listing)
    return {"label": label, "asin": asin, "title": title, **result.to_dict()}


def _title_from_raw(raw: dict) -> str:
    return (raw.get("product_name") or raw.get("title") or "")[:120]


def _asin_from_raw(raw: dict, fallback: str = "") -> str:
    return (raw.get("asin") or fallback).upper()


# ── public pipeline ────────────────────────────────────────────────────────────

def run(asin: str, country: str = "IN") -> dict:
    """
    Run the full marketplace LQS pipeline for an ASIN.

    Returns:
        {
            "source":           str,        # e.g. "direct (ASIN B0G2MM7VH9)"
            "target_asin":      str,
            "results":          list[dict], # scored products (TARGET + COMP-N)
            "gap_report":       dict,
            "score_comparison": list[dict],
            "dimension_gaps":   list[dict],
            "feedback":         dict,
        }

    Raises:
        RuntimeError  — Zyte returned no data / no category found
        ValueError    — bad ASIN format
    """
    asin = asin.strip().upper()
    logger.info("asin_pipeline.run: ASIN=%s country=%s", asin, country)

    # ── Step 1: Ingest ─────────────────────────────────────────────────────
    ingested = ingest(mode="asin", asin=asin)
    target_raw = ingested["target"]
    comp_raws  = ingested["competitors"]
    source     = ingested.get("source", f"direct (ASIN {asin})")

    logger.info(
        "asin_pipeline: ingested target=%s with %d competitor(s)",
        _asin_from_raw(target_raw, asin), len(comp_raws),
    )

    # ── Step 2: Map Zyte dicts → ListingInput ──────────────────────────────
    target_listing = map_zyte_to_listing_input(target_raw)
    comp_listings  = [map_zyte_to_listing_input(c) for c in comp_raws]

    # ── Step 2.5: Enrich target keywords via keyword_gap module ────────────
    # Competitors are passed as plain dicts so keyword_gap can build its
    # keyword union without requiring full ListingInput objects.
    comp_summaries = [
        {
            "title":       c.get("product_name") or c.get("title", ""),
            "bullets":    (c.get("key_features") or c.get("bullet_points") or [])[:3],
            "description":(c.get("product_description") or c.get("description", ""))[:300],
        }
        for c in comp_raws
    ]
    primary_kw, secondary_kws = get_keywords_for_listing(
        title=target_listing.title,
        bullets=target_listing.bullets,
        description=target_listing.description,
        competitors=comp_summaries,
    )
    if primary_kw:
        target_listing.primary_keyword = primary_kw
    if secondary_kws:
        target_listing.secondary_keywords = secondary_kws
    logger.info(
        "asin_pipeline: keyword enrichment — primary=%r secondary_count=%d",
        primary_kw, len(secondary_kws),
    )

    # ── Step 3: Score target (sequential) + competitors (parallel) ─────────
    target_asin  = _asin_from_raw(target_raw, asin)
    target_title = _title_from_raw(target_raw)

    logger.info("asin_pipeline: scoring TARGET %s", target_asin)
    target_result = _score_one("TARGET", target_asin, target_title, target_listing)

    comp_results: list[dict] = []
    if comp_listings:
        logger.info("asin_pipeline: scoring %d competitor(s) in parallel", len(comp_listings))

        futures: dict = {}
        with ThreadPoolExecutor(max_workers=min(len(comp_listings), 5)) as pool:
            for i, (listing, raw) in enumerate(zip(comp_listings, comp_raws)):
                label = f"COMP-{i + 1}"
                c_asin  = _asin_from_raw(raw)
                c_title = _title_from_raw(raw)
                fut = pool.submit(_score_competitor, label, c_asin, c_title, listing)
                futures[fut] = label

            for fut in as_completed(futures):
                label = futures[fut]
                try:
                    comp_results.append(fut.result())
                except Exception as exc:
                    logger.warning("asin_pipeline: %s scoring failed — %s", label, exc)

        # Restore original order (as_completed returns in completion order)
        label_order = [f"COMP-{i + 1}" for i in range(len(comp_listings))]
        comp_results.sort(key=lambda r: label_order.index(r["label"]) if r["label"] in label_order else 99)

    all_results = [target_result] + comp_results
    logger.info(
        "asin_pipeline: scored %d product(s) — target overall=%d",
        len(all_results), target_result["scores"]["overall"],
    )

    # ── Step 4: Insights (run on full data before slimming) ───────────────
    insights = generate_marketplace_insights(all_results)

    # ── Step 5: Slim competitor entries — scores + breakdown only ──────────
    # Target keeps the full output (flags, fix_priority, projections).
    # Competitors expose only what's needed for comparison tables.
    def _slim_competitor(r: dict) -> dict:
        return {
            "label":               r["label"],
            "asin":                r["asin"],
            "title":               r["title"],
            "scores":              r["scores"],
            "dimension_breakdown": r["dimension_breakdown"],
        }

    results_out = [
        r if r["label"] == "TARGET" else _slim_competitor(r)
        for r in all_results
    ]

    return {
        "source":      source,
        "target_asin": target_asin,
        "results":     results_out,
        **insights,
    }
