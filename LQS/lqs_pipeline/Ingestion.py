"""
Step 1 - INGESTION
==================
Uses zyte_client for all Amazon API calls.

Target      → zyte_client.get_product(asin)
                → category_hierarchy[-1]["name"]  → leaf_category_name (used as search query)
Competitors → zyte_client.search_products(leaf_category_name)
                → extract ASINs from result URLs → zyte_client.get_product per ASIN
Query mode  → search_products(query) to find initial ASIN, then falls into ASIN flow

Note: Zyte returns null IDs in category_hierarchy, so competitor discovery
uses keyword search on the leaf category name instead of a category-page endpoint.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import yaml as _yaml
from loguru import logger

from config import CFG, CATEGORY_KEYWORDS
from .zyte_client import get_product, search_products

# ── CompetitorAnalysis field-map (config-driven) ──────────────────────────────

_COMP_MAP_PATH = os.path.join(
    os.path.dirname(__file__), "../shared/config/comp_to_zyte_fields.yaml"
)


def _load_comp_field_map() -> dict:
    with open(_COMP_MAP_PATH) as _f:
        return _yaml.safe_load(_f)


def _normalize_comp_to_zyte(comp: dict, field_map: dict) -> dict:
    """Re-key a CompetitorAnalysis competitor dict to Zyte /extract/product schema."""
    result = {zyte_field: comp.get(comp_field)
              for comp_field, zyte_field in field_map.items()}
    result.setdefault("category_hierarchy", [])
    result.setdefault("image_urls", [])
    result.setdefault("technical_specifications", {})
    return result


def _fetch_competitors_from_analysis(seed_asin: str, own_asin: str, n: int) -> list[dict]:
    """
    Fetch ranked competitors via CompetitorAnalysis module and normalise
    each result to the Zyte /extract/product schema expected by zyte_mapper.py.
    Returns [] silently on any failure.
    """
    try:
        from CompetitorAnalysis.src.services.competitor_service import find_competitors  # noqa: PLC0415
        field_map = _load_comp_field_map()
        raw = find_competitors(seed_asin).get("competitors") or []
        filtered = [c for c in raw if c.get("asin", "").upper() != own_asin.upper()]
        normalised = [_normalize_comp_to_zyte(c, field_map) for c in filtered[:n]]
        logger.info(
            "_fetch_competitors_from_analysis: seed={} → {} competitors returned, {} after filter",
            seed_asin, len(raw), len(normalised),
        )
        return normalised
    except Exception as exc:
        logger.warning(
            "_fetch_competitors_from_analysis: CompetitorAnalysis failed for ASIN={} — {}",
            seed_asin, exc,
        )
        return []

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.IGNORECASE)


def asin_from_url(url: str) -> Optional[str]:
    m = ASIN_RE.search(url or "")
    asin = m.group(1).upper() if m else None
    logger.debug("asin_from_url: url={!r} → asin={}", url, asin)
    return asin


def infer_category(text: str) -> tuple[Optional[str], list[str]]:
    q = (text or "").lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in kws):
            logger.debug("infer_category: matched category={!r} from text={!r}", cat, text[:60])
            return cat, kws
    logger.debug("infer_category: no match for text={!r}", text[:60])
    return None, []


# ── Search (used in query mode and competitor discovery) ──────────────────────

def _search(query: str) -> list[dict]:
    """
    Returns a list of dicts with at least `asin` and `title` keys,
    extracted from Zyte search results.
    """
    logger.debug("_search: querying Zyte for {!r}", query)
    results = search_products(query, marketplace=CFG.country_code)
    mapped: list[dict] = []
    for item in results:
        url = item.get("url") or ""
        asin = asin_from_url(url)
        if asin:
            mapped.append({"asin": asin, "title": item.get("name", "")})
    logger.debug("_search: {!r} → {} raw results, {} with valid ASINs", query, len(results), len(mapped))
    return mapped


# ── Competitor discovery ──────────────────────────────────────────────────────

def _fetch_category_competitors(category_name: str, own_asin: str, n: int = 5) -> list[dict]:
    """
    Discovers competitors by searching the leaf category name, then fetches
    full product details for each unique ASIN in parallel (excluding own_asin).
    """
    logger.debug("_fetch_category_competitors: category={!r} own_asin={} n={}", category_name, own_asin, n)
    search_results = _search(category_name)

    collected: list[str] = []
    for item in search_results:
        asin = (item.get("asin") or "").strip().upper()
        if asin and asin != own_asin.upper() and asin not in collected:
            collected.append(asin)
        if len(collected) >= n:
            break

    logger.debug("_fetch_category_competitors: {} candidate ASINs to fetch: {}", len(collected), collected)

    def _fetch_one(asin: str) -> tuple[str, dict | None]:
        logger.debug("_fetch_one: fetching product data for ASIN={}", asin)
        try:
            data = get_product(asin, marketplace=CFG.country_code)
            logger.debug("_fetch_one: ASIN={} fetched OK", asin)
            return asin, data
        except Exception as e:
            logger.warning("Skipping competitor {} — product fetch failed: {}", asin, e)
            return asin, None

    fetched: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=n) as pool:
        for asin, data in pool.map(_fetch_one, collected[:n]):
            if data:
                fetched[asin] = data

    result = [fetched[asin] for asin in collected[:n] if asin in fetched]
    logger.info("_fetch_category_competitors: {}/{} competitors fetched successfully for category={!r}",
                len(result), len(collected), category_name)
    # preserve the original discovery order
    return result


def _resolve_asin(asin: str) -> tuple[dict, str]:
    """
    Calls zyte_client.get_product and extracts the leaf category name
    (used as the search query for competitor discovery).
    Returns (full_raw_data, leaf_category_name).
    """
    logger.debug("_resolve_asin: fetching product for ASIN={}", asin)
    data = get_product(asin, marketplace=CFG.country_code)
    hierarchy = data.get("category_hierarchy") or []
    if not hierarchy:
        logger.error("_resolve_asin: no category_hierarchy for ASIN={}", asin)
        raise RuntimeError(
            f"No category hierarchy returned for ASIN {asin}. "
            "Cannot discover competitors without a category."
        )
    # Zyte returns null IDs — use the leaf category name as the search query
    leaf_name = hierarchy[-1].get("name") or hierarchy[0].get("name") or ""
    logger.debug("_resolve_asin: ASIN={} → leaf_category={!r} (hierarchy depth={})",
                 asin, leaf_name, len(hierarchy))
    return data, leaf_name


# ── Public entrypoint ─────────────────────────────────────────────────────────

def ingest(mode: str, **kwargs) -> dict:
    """
    Returns:
        {"target": dict, "competitors": list[dict], "source": str, "kws": list[str]}
    """
    logger.info("ingest: mode={} kwargs={}", mode, {k: v for k, v in kwargs.items()})

    if mode == "url":
        asin = asin_from_url(kwargs["url"])
        if not asin:
            logger.error("ingest: cannot parse ASIN from URL={!r}", kwargs["url"])
            raise ValueError(f"Cannot parse ASIN from: {kwargs['url']}")
        logger.debug("ingest: url mode resolved to ASIN={}", asin)
        return ingest("asin", asin=asin)

    if mode == "asin":
        asin = kwargs["asin"].strip().upper()
        logger.debug("ingest: resolving ASIN={}", asin)
        target_raw, leaf_cat_name = _resolve_asin(asin)
        comps = _fetch_competitors_from_analysis(asin, asin, CFG.top_n_competitors)
        _, kws = infer_category(leaf_cat_name)
        logger.info("ingest: ASIN={} done — leaf_cat={!r} kws={} competitors={}",
                    asin, leaf_cat_name, kws, len(comps))
        return {
            "target"     : target_raw,
            "competitors": comps,
            "source"     : f"direct (ASIN {asin})",
            "kws"        : kws,
        }

    if mode == "query":
        q = kwargs["query"]
        logger.debug("ingest: query mode q={!r}", q)
        _, kws = infer_category(q)

        target_raw: Optional[dict] = None
        leaf_cat_name = ""

        results = _search(q)
        valid = [
            r for r in results
            if not kws or any(kw in str(r.get("title", "")).lower() for kw in kws)
        ]
        logger.debug("ingest: query={!r} → {} search hits, {} keyword-matched", q, len(results), len(valid))

        for hit in valid:
            asin = str(hit.get("asin", "")).strip().upper()
            if not asin:
                continue
            logger.debug("ingest: trying ASIN={} from search hit title={!r}", asin, hit.get("title", "")[:50])
            try:
                target_raw, leaf_cat_name = _resolve_asin(asin)
                logger.debug("ingest: selected target ASIN={} leaf_cat={!r}", asin, leaf_cat_name)
                break
            except Exception as e:
                logger.warning("Skipping ASIN {}: {}", asin, e)

        if target_raw is None:
            logger.error("ingest: no category-matched product found for query={!r}", q)
            raise RuntimeError(f"No category-matched product found for query '{q}'.")

        own_asin = str(target_raw.get("asin", "")).upper()
        comps = _fetch_competitors_from_analysis(own_asin, own_asin, CFG.top_n_competitors)
        logger.info("ingest: query={!r} done — target={} leaf_cat={!r} competitors={}", q, own_asin, leaf_cat_name, len(comps))
        return {
            "target"     : target_raw,
            "competitors": comps,
            "source"     : f"search result",
            "kws"        : kws,
        }

    raise ValueError(f"Unknown mode: {mode!r}")
