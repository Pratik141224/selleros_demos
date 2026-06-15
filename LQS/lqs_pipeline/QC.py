"""
Step 3 -  QC
========================
Validates extracted products. Flags issues but does not stop the pipeline.
Output: same dict + a 'qc_flags' list per product.
"""
from loguru import logger


def validate_product(p: dict) -> list[str]:
    """Return a list of issue codes for a single product. Empty = clean."""
    flags = []

    if not p.get("title"):
        flags.append("MISSING_TITLE")
    elif len(p["title"]) < 20:
        flags.append("TITLE_TOO_SHORT")

    if p.get("price", 0) <= 0:
        flags.append("INVALID_PRICE")
    elif p.get("original_price", 0) > 0 and p["original_price"] < p["price"]:
        flags.append("MRP_BELOW_PRICE")

    if not (0 <= p.get("rating", 0) <= 5):
        flags.append("RATING_OUT_OF_RANGE")

    if p.get("reviews", 0) < 0:
        flags.append("NEGATIVE_REVIEWS")

    if not p.get("asin") or len(p["asin"]) != 10:
        flags.append("INVALID_ASIN")

    return flags


def run_qc(extracted: dict) -> dict:
    """Attach qc_flags to each product."""
    extracted["target"]["qc_flags"] = validate_product(extracted["target"])
    for c in extracted["competitors"]:
        c["qc_flags"] = validate_product(c)

    bad = [p for p in [extracted["target"]] + extracted["competitors"] if p["qc_flags"]]
    if bad:
        logger.info("QC flagged %d products: %s",
                 len(bad), [f"{p['asin']}:{p['qc_flags']}" for p in bad])

    return extracted