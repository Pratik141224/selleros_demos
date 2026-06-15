"""
Zyte-based product data client.
Replaces omkar_client — all Amazon data now goes through the EC2 Zyte service.

Endpoints used:
  POST /extract/product  → structured product fields (name, price, rating, etc.)
  POST /scrape/product   → raw Zyte product JSON (fallback when extraction is empty)
  POST /scrape/search    → keyword search results (ASIN discovery)
"""
from __future__ import annotations

import os
import re
import time

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

ZYTE_BASE_URL = os.getenv("ZYTE_BASE_URL", "http://54.197.215.125:4001")
TIMEOUT = 90  # Zyte cold calls can take 8–20 s; 90 s gives headroom
_RETRY_ON = {500, 502, 503}  # transient server-side errors worth retrying once


# ── Raw scrape fallback ───────────────────────────────────────────────────────

def _scrape_product_raw(asin: str, marketplace: str, force_refresh: bool = True) -> dict:
    """POST /scrape/product → raw Zyte product JSON (no extraction pipeline)."""
    resp = requests.post(
        f"{ZYTE_BASE_URL}/scrape/product",
        json={"asin": asin, "marketplace": marketplace, "force_refresh": force_refresh},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("data") or {}


def _normalize_raw_zyte(raw: dict, asin: str) -> dict:
    """
    Map /scrape/product raw Zyte schema → /extract/product schema so the rest
    of the pipeline (Extraction.py → QC → features) sees a consistent shape.
    """
    breadcrumbs = raw.get("breadcrumbs") or []
    category_hierarchy = [
        {"name": b.get("name", ""), "link": b.get("url", ""), "id": None}
        for b in breadcrumbs
    ]

    images_raw = raw.get("images") or []
    image_urls = [img["url"] for img in images_raw if img.get("url")]
    main_image_url = (raw.get("mainImage") or {}).get("url") or (image_urls[0] if image_urls else None)

    agg = raw.get("aggregateRating") or {}

    def _safe_float(val):
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    current_price = _safe_float(raw.get("price"))
    original_price = _safe_float(raw.get("regularPrice"))
    discount_pct = None
    if current_price and original_price and original_price > 0:
        discount_pct = round((original_price - current_price) / original_price * 100)

    brand = raw.get("brand")
    brand_name = brand.get("name") if isinstance(brand, dict) else brand

    return {
        "asin"                   : raw.get("sku") or asin,
        "product_name"           : raw.get("name") or "",
        "brand"                  : brand_name,
        "url"                    : raw.get("url") or "",
        "canonical_url"          : raw.get("canonicalUrl") or "",
        "current_price"          : current_price,
        "original_price"         : original_price,
        "discount_percent"       : discount_pct,
        "currency"               : raw.get("currency"),
        "currency_raw"           : raw.get("currencyRaw"),
        "availability"           : raw.get("availability") or "",
        "mpn"                    : None,
        "category_hierarchy"     : category_hierarchy,
        "main_image_url"         : main_image_url,
        "image_urls"             : image_urls,
        "rating"                 : agg.get("ratingValue"),
        "review_count"           : agg.get("reviewCount"),
        "rating_breakdown"       : {},
        "color"                  : None,
        "size"                   : None,
        "weight"                 : None,
        "technical_specifications": {},
        "top_highlights"         : {},
        "key_features"           : [],
        "product_description"    : raw.get("description") or "",
        "variants"               : [],
    }


def _is_empty_extraction(data: dict) -> bool:
    """Returns True when /extract/product silently failed to parse the listing."""
    return not data.get("product_name") and not (data.get("category_hierarchy") or [])


# ── Public API ────────────────────────────────────────────────────────────────

_CANONICAL_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE)


def _canonical_asin(raw: dict, own_asin: str) -> str | None:
    """Return the ASIN from canonicalUrl if it differs from own_asin, else None."""
    url = raw.get("canonicalUrl") or raw.get("canonical_url") or ""
    m = _CANONICAL_ASIN_RE.search(url)
    if not m:
        return None
    found = m.group(1).upper()
    return found if found != own_asin.upper() else None


def get_product(
    asin: str,
    marketplace: str = "IN",
    force_refresh: bool = False,
    _redirect_followed: bool = False,
) -> dict:
    """
    Returns structured product data in /extract/product schema.

    Flow:
      1. POST /extract/product (attempt 1, normal)
      2. If 5xx → retry with force_refresh=True
         If 200 but empty (Zyte parse failure) → retry with force_refresh=True
      3. If still empty after retry → POST /scrape/product and normalize
      4. If scrape is a sparse redirect-only response → follow canonicalUrl
         to the parent ASIN and retry once (_redirect_followed guard)

    Raises:
        requests.HTTPError  — 4xx / persistent 5xx
        RuntimeError        — all attempts returned no usable data
    """
    base_payload = {
        "asin": asin,
        "marketplace": marketplace,
        "platform": "amazon",
        "config_name": "v1",
    }
    logger.debug("get_product: ASIN={} marketplace={} force_refresh={}", asin, marketplace, force_refresh)

    data = None
    for attempt in range(2):  # attempt 0 = normal, attempt 1 = force_refresh
        payload = {**base_payload, "force_refresh": True if attempt > 0 else force_refresh}
        resp = requests.post(f"{ZYTE_BASE_URL}/extract/product", json=payload, timeout=TIMEOUT)

        if resp.ok:
            result = resp.json()
            data = result.get("data")
            if not data:
                raise RuntimeError(f"Zyte returned no data for ASIN {asin} ({marketplace})")
            logger.info("get_product: ASIN={} cache={} attempt={}", asin, result.get("status", "?"), attempt + 1)

            # /extract/product sometimes returns 200 with all-null fields when Zyte's
            # extraction pipeline fails to parse the cached page. Retry with
            # force_refresh=True to force a fresh scrape before falling back to /scrape/product.
            if _is_empty_extraction(data) and attempt == 0:
                logger.warning(
                    "get_product: ASIN={} — /extract/product returned empty on attempt 1, "
                    "retrying with force_refresh=True",
                    asin,
                )
                continue
            break

        if resp.status_code in _RETRY_ON and attempt == 0:
            logger.warning(
                "get_product: ASIN={} HTTP {} on attempt 1, retrying with force_refresh=True — body: {:.300}",
                asin, resp.status_code, resp.text,
            )
            time.sleep(2)
            continue

        logger.error("get_product: ASIN={} HTTP {} — body: {:.500}", asin, resp.status_code, resp.text)
        resp.raise_for_status()

    if data is None:
        raise RuntimeError("Unreachable")

    # /extract/product sometimes returns 200 with all-null fields when the
    # extraction pipeline fails to parse the page. Fall back to the raw scrape.
    if _is_empty_extraction(data):
        logger.warning(
            "get_product: ASIN={} — /extract/product returned empty fields, "
            "falling back to /scrape/product",
            asin,
        )
        raw = _scrape_product_raw(asin, marketplace)
        if not raw:
            raise RuntimeError(
                f"Both /extract/product and /scrape/product returned no data for ASIN {asin}"
            )
        data = _normalize_raw_zyte(raw, asin)
        logger.info(
            "get_product: ASIN={} — fallback succeeded, product_name={!r} category_depth={}",
            asin, data.get("product_name", "")[:60], len(data.get("category_hierarchy") or []),
        )

        # Scrape can return a sparse redirect-only response (just sku/url/canonicalUrl)
        # when the requested ASIN is a variant that redirects to a parent listing.
        # Follow the canonicalUrl once to fetch the parent product.
        if _is_empty_extraction(data) and not _redirect_followed:
            parent_asin = _canonical_asin(raw, asin)
            if parent_asin:
                logger.info(
                    "get_product: ASIN={} is a variant (probability≈0) — "
                    "following canonical redirect to parent ASIN={}",
                    asin, parent_asin,
                )
                return get_product(
                    parent_asin,
                    marketplace=marketplace,
                    force_refresh=force_refresh,
                    _redirect_followed=True,
                )
            raise RuntimeError(
                f"ASIN {asin} appears to be an unresolvable variant — "
                "both endpoints returned empty data and no canonical ASIN found"
            )

    return data


def search_products(
    query: str,
    marketplace: str = "IN",
    force_refresh: bool = False,
) -> list[dict]:
    """
    POST /scrape/search → returns list of product dicts from `data.products`.

    Returns [] on any error so callers can degrade gracefully.
    """
    logger.debug("search_products: query={!r} marketplace={} force_refresh={}", query, marketplace, force_refresh)

    for attempt in range(2):
        payload = {
            "query": query,
            "marketplace": marketplace,
            "force_refresh": True if attempt > 0 else force_refresh,
        }
        try:
            resp = requests.post(f"{ZYTE_BASE_URL}/scrape/search", json=payload, timeout=TIMEOUT)
        except requests.Timeout:
            if attempt == 0:
                logger.warning("search_products: {!r} timed out, retrying with force_refresh=True", query)
                continue
            logger.warning("search_products: {!r} timed out on attempt 2, returning []", query)
            return []
        except requests.RequestException as exc:
            logger.warning("search_products: {!r} failed — {}", query, exc)
            return []

        if resp.ok:
            products = (resp.json().get("data") or {}).get("products") or []
            logger.debug("search_products: {!r} attempt={} → {} product(s)", query, attempt + 1, len(products))
            return products

        if resp.status_code in _RETRY_ON and attempt == 0:
            logger.warning(
                "search_products: {!r} HTTP {} on attempt 1, retrying — body: {:.200}",
                query, resp.status_code, resp.text,
            )
            continue

        logger.warning("search_products: {!r} HTTP {} (attempt {}), returning []",
                       query, resp.status_code, attempt + 1)
        return []

    return []
