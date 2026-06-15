"""
shared/zyte_client.py

Unified data-fetch layer for all SellerOS demos.

- Own product data  →  Zyte ingestion service (POST /extract/product)
- Competitor data   →  CompetitorAnalysis.src.services.competitor_service.find_competitors()

Field name mappings between API responses and our internal model are loaded from
shared/config/zyte_product_fields.yaml and shared/config/competitor_fields.yaml.
To adapt to an API rename, edit only those YAML files.
"""

import json
import os
import re
import sys

import requests
import yaml

# ---------------------------------------------------------------------------
# Config load
# ---------------------------------------------------------------------------

_CFG_DIR = os.path.join(os.path.dirname(__file__), "config")


def _load_yaml(name: str) -> dict:
    with open(os.path.join(_CFG_DIR, name)) as f:
        return yaml.safe_load(f)


_PRODUCT = _load_yaml("zyte_product_fields.yaml")
_COMP = _load_yaml("competitor_fields.yaml")

# ---------------------------------------------------------------------------
# Client settings
# ---------------------------------------------------------------------------

ZYTE_BASE_URL = os.getenv("ZYTE_BASE_URL", "http://54.197.215.125:4001")
TIMEOUT = 90  # Zyte cold calls can take up to ~20s; 90s is the safe ceiling


# ---------------------------------------------------------------------------
# ASIN utilities
# ---------------------------------------------------------------------------

def extract_asin(asin_or_url: str) -> str:
    """Return the 10-char ASIN from an Amazon URL or a bare ASIN string."""
    asin_or_url = asin_or_url.strip()
    m = re.search(r"/dp/([A-Z0-9]{10})", asin_or_url, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    candidate = asin_or_url.upper()
    if re.fullmatch(r"[A-Z0-9]{10}", candidate):
        return candidate
    raise ValueError(
        f"Could not extract a valid ASIN from: {asin_or_url!r}. "
        "Provide a 10-character ASIN or an Amazon product URL containing /dp/<ASIN>."
    )


# ---------------------------------------------------------------------------
# Own product listing
# ---------------------------------------------------------------------------

def fetch_own_listing(asin_or_url: str, marketplace: str = "IN") -> dict:
    """
    Fetch the seller's own product listing via the Zyte ingestion service.

    Returns:
        {
            "asin":               str,
            "title":              str,
            "bullets":            list[str],   # up to 5
            "description":        str,
            "leaf_category_id":   str,         # Amazon node ID or slugified name
            "leaf_category_name": str,
        }

    Raises:
        ValueError       — bad ASIN format or empty category hierarchy
        requests.HTTPError — 4xx/5xx from the Zyte service
    """
    asin = extract_asin(asin_or_url)

    resp = requests.post(
        f"{ZYTE_BASE_URL}/extract/product",
        json={"asin": asin, "marketplace": marketplace},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()["data"]

    hierarchy = data.get(_PRODUCT["category_hierarchy_key"]) or []
    if not hierarchy:
        raise ValueError(
            f"No category hierarchy returned for ASIN {asin}. "
            "Cannot identify competitors without a category."
        )
    leaf = hierarchy[-1]

    link = leaf.get(_PRODUCT["category_link_key"], "") or ""
    node_match = re.search(r"node=(\d+)", link)
    if node_match:
        leaf_id = node_match.group(1)
    else:
        leaf_id = re.sub(r"[^a-z0-9]+", "-",
                         leaf.get(_PRODUCT["category_name_key"], "").lower()).strip("-")

    return {
        "asin":               asin,
        "title":              data.get(_PRODUCT["title"]) or "",
        "bullets":            (data.get(_PRODUCT["bullets_source"]) or [])[:5],
        "description":        data.get(_PRODUCT["description"]) or "",
        "leaf_category_name": leaf.get(_PRODUCT["category_name_key"], ""),
        "leaf_category_id":   leaf_id,
    }


# ---------------------------------------------------------------------------
# Competitor data
# ---------------------------------------------------------------------------

def fetch_competitor_summaries(
    seed_asin: str,
    own_asin: str = None,
    n: int = 5,
) -> list:
    """
    Return up to n competitor summaries using CompetitorAnalysis.find_competitors().

    CompetitorAnalysis already filters out the seed product and same-brand results,
    and returns results sorted by semantic similarity (deep_score desc).

    Returns:
        [{"asin": str, "title": str, "bullets": list[str], "description": str}, ...]
    On any exception: returns [] silently so the main flow is never blocked.
    """
    try:
        # Late import — CompetitorAnalysis has heavy deps (sentence-transformers, s3fs)
        # that should only load when this function is actually called.
        _project_root = os.path.join(os.path.dirname(__file__), "..")
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)

        from CompetitorAnalysis.src.services.competitor_service import find_competitors

        result = find_competitors(seed_asin)
        raw_competitors = (result.get("competitors") or [])[:n]

        def _parse_bullets(raw) -> list[str]:
            # CompetitorAnalysis stores bullet_points as a JSON string in parquet.
            # Parse it back to a list before slicing.
            if isinstance(raw, list):
                return raw
            if isinstance(raw, str) and raw.strip().startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass
            return []

        return [
            {
                "asin":        c.get(_COMP["asin"], ""),
                "title":       c.get(_COMP["title"], ""),
                "bullets":     _parse_bullets(c.get(_COMP["bullets_source"]))[:3],
                "description": (c.get(_COMP["description"]) or "")[:300],
            }
            for c in raw_competitors
        ]
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "fetch_competitor_summaries(%s) failed — %s: %s",
            seed_asin, type(exc).__name__, exc,
        )
        return []


# ---------------------------------------------------------------------------
# Competitor prompt block builder
# ---------------------------------------------------------------------------

def build_competitor_block(competitors: list, purpose: str = "keyword") -> str:
    """
    Build a compact competitor context string for injection into LLM prompts.

    purpose: "keyword"    → wording for A9 / discovery pass
             "conversion" → wording for Rufus / persona pass
    """
    if not competitors:
        return ""

    if purpose == "keyword":
        header = (
            "Top-ranked competitors in this category "
            "(use for keyword and content gap analysis):"
        )
    else:
        header = (
            "Top-ranked competitors in this category "
            "(use to identify persona gaps and unhandled objections):"
        )

    lines = [header]
    for i, c in enumerate(competitors, 1):
        bullets_str = " | ".join(c["bullets"]) if c.get("bullets") else "—"
        lines.append(f'{i}. Title: "{c["title"]}"')
        lines.append(f"   Bullets: {bullets_str}")
        if c.get("description"):
            lines.append(f'   Description (excerpt): {c["description"][:200]}')

    return "\n".join(lines)
