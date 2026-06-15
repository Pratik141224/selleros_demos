"""
STEP 2 — DATA EXTRACTION
========================
Normalizes the raw product-details API response into a consistent product schema.

product-details field names differ from the old search API:
  product_name  → title
  mrp           → original_price
  average_rating / rating → rating
  total_reviews / ratings_total / reviews → reviews
  main_image    → image_url
  product_url / url → url
"""
from loguru import logger


def _float(raw: dict, *keys) -> float:
    for k in keys:
        v = raw.get(k)
        if v not in (None, "", 0, "0"):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def _int(raw: dict, *keys) -> int:
    for k in keys:
        v = raw.get(k)
        if v not in (None, "", 0, "0"):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                pass
    return 0


def _str(raw: dict, *keys) -> str:
    for k in keys:
        v = raw.get(k)
        if v:
            return str(v)
    return ""


def extract_product(raw: dict) -> dict:
    """Standardize a raw product-details API response into our internal schema."""
    asin = _str(raw, "asin") or "N/A"
    # Zyte uses `main_image_url`; legacy omkar used `main_image` / `image_url`
    images = raw.get("image_urls") or raw.get("images") or []
    image_url = _str(raw, "main_image_url", "main_image", "image_url") or (images[0] if images else "")

    product = {
        "asin"            : asin,
        "title"           : _str(raw, "product_name", "title"),
        "price"           : _float(raw, "price", "deal_price", "final_price", "current_price"),
        "original_price"  : _float(raw, "mrp", "original_price", "market_price", "was_price"),
        "rating"          : _float(raw, "average_rating", "rating", "stars"),
        "reviews"         : _int(raw,   "total_reviews", "ratings_total", "review_count", "reviews"),
        "image_url"       : image_url,
        "is_prime"        : bool(raw.get("is_prime", False)),
        "url"             : _str(raw, "product_url", "url"),
        # Content fields — needed for A9 + Rufus scoring downstream
        "bullets"         : raw.get("key_features") or raw.get("bullet_points") or raw.get("bullets") or [],
        "description"     : _str(raw, "product_description", "description"),
        "brand"           : _str(raw, "brand"),
        "aplus_content"   : _str(raw, "aplus_content", "a_plus_content"),
        "backend_keywords": _str(raw, "search_terms", "backend_keywords"),
    }

    if not product["title"]:
        logger.warning("extract_product: ASIN={} has no title", asin)
    if product["price"] <= 0:
        logger.warning("extract_product: ASIN={} has invalid price={}", asin, product["price"])
    logger.debug("extract_product: ASIN={} title={!r:.40} price={} rating={} reviews={}",
                 asin, product["title"], product["price"], product["rating"], product["reviews"])
    return product


def extract_all(ingested: dict) -> dict:
    """Extract target + all competitors into the standard schema."""
    logger.debug("extract_all: extracting target + {} competitor(s)", len(ingested["competitors"]))
    result = {
        "target"     : extract_product(ingested["target"]),
        "competitors": [extract_product(c) for c in ingested["competitors"]],
        "source"     : ingested["source"],
        "kws"        : ingested["kws"],
    }
    logger.debug("extract_all: done — target ASIN={}", result["target"]["asin"])
    return result
