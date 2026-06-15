"""
STEP 4 — FEATURE CREATION
=========================
Converts a normalized product into the 23-feature vector the model needs.
Missing PDP-only features (bullets, A+, video) are inferred.
"""
import numpy as np
from loguru import logger

from config import BRAND_VOCAB


def _infer_brand(title_lower: str) -> int:
    return int(any(b in title_lower.split() for b in BRAND_VOCAB))


def build_features(p: dict) -> dict[str, float]:
    """Build the 23-feature vector for a single product."""
    asin   = p.get("asin", "?")
    title  = p.get("title", "")
    price  = p.get("price", 0)
    mrp    = p.get("original_price", 0)
    rating = p.get("rating", 0)
    rev    = p.get("reviews", 0)
    disc   = round((mrp - price) / mrp * 100, 2) if mrp > 0 else 0.0

    title_lower    = title.lower()
    brand_present  = _infer_brand(title_lower)
    sentence_case  = int(bool(title) and title[0].isupper())
    is_established = (rating >= 4.0 and rev >= 100)

    bullet_count = 5   if is_established else 2
    desc_words   = 200 if is_established else 40
    image_count  = 7   if is_established else 3
    has_aplus    = int(brand_present and rev >= 100)
    has_video    = int(brand_present and rev >= 500)
    bsr_proxy    = max(1, int(50_000 / (rev + 10)))

    features = {
        "title_length": len(title), "title_word_count": len(title.split()),
        "title_brand_present": brand_present, "title_sentence_case": sentence_case,
        "title_spellcheck_pass": 1, "bullet_count": bullet_count,
        "bullets_spell_pass": 1, "bullets_caps_pass": 1,
        "final_bullet_flag": int(bullet_count >= 4),
        "description_word_count": desc_words,
        "final_desc_flag": int(desc_words >= 100),
        "price": float(price), "mrp": float(mrp), "discount_pct": disc,
        "star_rating": float(rating), "review_count": float(rev),
        "log_review_count": float(np.log1p(rev)),
        "best_seller_rank": bsr_proxy, "image_count": image_count,
        "video_count": has_video, "has_video": has_video,
        "has_aplus": has_aplus, "aplus_check_pass": has_aplus,
    }

    logger.debug("build_features: ASIN={} brand={} is_established={} discount={:.1f}% bsr_proxy={}",
                 asin, bool(brand_present), is_established, disc, bsr_proxy)
    return features


def build_all_features(qc_data: dict) -> dict:
    """Attach a feature vector to every product."""
    logger.debug("build_all_features: building features for target + {} competitor(s)",
                 len(qc_data["competitors"]))
    qc_data["target"]["features"] = build_features(qc_data["target"])
    for c in qc_data["competitors"]:
        c["features"] = build_features(c)
    logger.debug("build_all_features: done")
    return qc_data
