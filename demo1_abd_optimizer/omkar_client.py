"""
demo1_abd_optimizer/omkar_client.py

Omkar Cloud API wrapper for the ABD Optimizer.
Provides: ASIN extraction, own-listing fetch, competitor summary fetch.
"""

import re
import os
import requests
from dotenv import load_dotenv

load_dotenv()

OC_API_KEY = os.getenv("OMKAR_API_KEY")
BASE_URL = "https://amazon-scraper-api.omkar.cloud/amazon"
TIMEOUT = 25


def extract_asin(asin_or_url: str) -> str:
    """Return the 10-char ASIN from a URL or a bare ASIN string."""
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


def _api_headers() -> dict:
    if not OC_API_KEY:
        raise EnvironmentError(
            "OMKAR_API_KEY not set. Run: export OMKAR_API_KEY=your-key"
        )
    return {"API-Key": OC_API_KEY}


def _get_product_details(asin: str, country_code: str = "IN") -> dict:
    resp = requests.get(
        f"{BASE_URL}/product-details",
        params={"asin": asin, "country_code": country_code},
        headers=_api_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _get_category_page(category_id: str, page: int = 1, country_code: str = "IN") -> dict:
    resp = requests.get(
        f"{BASE_URL}/products/category",
        params={"category_id": category_id, "country_code": country_code, "page": page},
        headers=_api_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_own_listing(asin_or_url: str, country_code: str = "IN") -> dict:
    """
    Fetch and extract the seller's own product listing from an ASIN or URL.

    Returns:
        {
            "asin": str,
            "title": str,
            "bullets": list[str],          # up to 5 key_features
            "description": str,            # full_description or ""
            "leaf_category_id": str,       # id of last node in category_hierarchy
            "leaf_category_name": str,     # name of that leaf node
        }
    Raises:
        ValueError  — bad ASIN format or no category hierarchy returned
        requests.HTTPError — API responded with 4xx/5xx
        EnvironmentError  — OMKAR_API_KEY not set
    """
    asin = extract_asin(asin_or_url)
    data = _get_product_details(asin, country_code)

    title = data.get("product_name") or ""
    bullets = (data.get("key_features") or [])[:5]
    description = data.get("full_description") or ""

    category_hierarchy = data.get("category_hierarchy") or []
    if not category_hierarchy:
        raise ValueError(
            f"No category hierarchy returned for ASIN {asin}. "
            "Cannot identify competitors without a category."
        )
    leaf = category_hierarchy[-1]

    return {
        "asin": asin,
        "title": title,
        "bullets": bullets,
        "description": description,
        "leaf_category_id": leaf["id"],
        "leaf_category_name": leaf.get("name", ""),
    }


def fetch_competitor_summaries(
    leaf_category_id: str,
    own_asin: str,
    n: int = 5,
    max_pages: int = 5,
    country_code: str = "IN",
) -> list[dict]:
    """
    Fetch the top N competitors from the leaf category (by relevance rank),
    excluding own_asin, scanning up to max_pages pages of category results.

    For each competitor ASIN a product-details call is made to get
    title, bullets, and description.

    Returns list of dicts:
        [{"asin": str, "title": str, "bullets": list[str], "description": str}, ...]
    Failed individual competitor fetches are skipped silently.
    """
    collected_asins: list[str] = []

    for page in range(1, max_pages + 1):
        try:
            page_data = _get_category_page(leaf_category_id, page=page, country_code=country_code)
        except Exception:
            break

        results = page_data.get("results") or []
        for item in results:
            item_asin = (item.get("asin") or "").strip().upper()
            if item_asin and item_asin != own_asin.upper() and item_asin not in collected_asins:
                collected_asins.append(item_asin)
            if len(collected_asins) >= n:
                break

        if len(collected_asins) >= n or not page_data.get("next"):
            break

    competitors: list[dict] = []
    for asin in collected_asins[:n]:
        try:
            detail = _get_product_details(asin, country_code)
            competitors.append({
                "asin": asin,
                "title": detail.get("product_name") or "",
                # Keep first 3 bullets to control prompt token budget
                "bullets": (detail.get("key_features") or [])[:3],
                # Cap description at 300 chars to keep context lean
                "description": (detail.get("full_description") or "")[:300],
            })
        except Exception:
            continue

    return competitors


def build_competitor_block(competitors: list[dict], purpose: str = "keyword") -> str:
    """
    Build a compact competitor context string for injection into prompts.

    purpose: "keyword"    → wording for PASS1 (A9 / discovery)
             "conversion" → wording for PASS2 (Rufus / persona)
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
        bullets_str = " | ".join(c["bullets"]) if c["bullets"] else "—"
        lines.append(f'{i}. Title: "{c["title"]}"')
        lines.append(f'   Bullets: {bullets_str}')
        if c.get("description"):
            lines.append(f'   Description (excerpt): {c["description"][:200]}')

    return "\n".join(lines)
