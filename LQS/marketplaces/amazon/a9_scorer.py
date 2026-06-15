"""
marketplaces/amazon/a9_scorer.py

Amazon A9 Compliance Scorer — Pass 1 (deterministic, zero LLM).

8 dimensions, max 100 pts total:
  D1 Title Keyword Placement   25 pts
  D2 Title Structure           15 pts
  D3 Mobile Optimisation       15 pts
  D4 Bullet Compliance         20 pts
  D5 Backend Keywords          10 pts
  D6 Browse Node + Category    10 pts
  D7 Attribute Completeness     3 pts
  D8 Content Richness           2 pts

Each dimension scorer returns (score, flags).
The public entry-point is score_a9().
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── constants ──────────────────────────────────────────────────────────────────

_SUPERLATIVES = {"best", "#1", "amazing", "premium quality", "world-class", "top-rated", "unbeatable"}
_BANNED_OPENERS = {"introducing", "experience", "transform", "elevate", "discover"}
_FUNCTION_WORDS = {
    "the", "a", "an", "and", "or", "for", "with", "in", "of", "by",
    "to", "on", "at", "from", "as", "is", "are", "was", "be", "been",
    "it", "this", "that", "its", "has", "have",
}
_SPEC_UNITS = re.compile(
    r"\b\d+(\.\d+)?\s*(ml|l|kg|g|mm|cm|m|inch|inches|gb|tb|mah|w|watts|hz|mp|ft|oz|lb|lbs|rpm|v|volt)\b",
    re.IGNORECASE,
)
_FEATURE_LABEL = re.compile(r"^[A-Za-z][A-Za-z &/]+:")  # "Material:", "Feature:", etc.
_SPECIAL_CHARS = re.compile(r"[™®©]|[\U0001F300-\U0001FFFF]")


# ── text helpers ───────────────────────────────────────────────────────────────

def _tokens(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _contains(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return phrase.lower() in text.lower()


def _kw_word_pos(title: str, keyword: str) -> int:
    """1-based word position of the first occurrence of `keyword` in `title`, or -1."""
    title_toks = _tokens(title)
    kw_toks = _tokens(keyword)
    if not kw_toks:
        return -1
    n = len(kw_toks)
    for i in range(len(title_toks) - n + 1):
        if title_toks[i : i + n] == kw_toks:
            return i + 1
    return -1


def _extract_fallback_keyword(title: str, backend_kw: str) -> str:
    """Pick a sensible primary keyword when the caller didn't provide one."""
    if backend_kw:
        candidates = backend_kw.split()
        meaningful = [w for w in candidates if len(w) > 3 and w.isalpha()]
        if meaningful:
            return meaningful[0]
    title_toks = _tokens(title)
    stopwords = _FUNCTION_WORDS | {"new", "buy", "shop", "get", "best"}
    filtered = [w for w in title_toks if w not in stopwords and len(w) > 3]
    return filtered[0] if filtered else (title_toks[0] if title_toks else "")


# ── dimension scorers ──────────────────────────────────────────────────────────

def _d1_title_keyword(
    title: str, primary_kw: str, secondary_kws: list[str]
) -> tuple[int, list[str]]:
    """Dimension 1 — Title Keyword Placement (max 25 pts)."""
    flags: list[str] = []

    if not primary_kw or not _contains(title, primary_kw):
        flags.append("CRITICAL_KW_MISS")
        return 0, flags

    pts = 10  # PRIMARY_KW_IN_TITLE

    pos = _kw_word_pos(title, primary_kw)
    if 1 <= pos <= 5:
        pts += 8  # PRIMARY_KW_IN_FIRST_5_WORDS
    elif pos > 10:
        pts -= 8
        flags.append("KEYWORD_AFTER_WORD_10")

    kw_lower = primary_kw.lower()
    if kw_lower in title[:80].lower():
        pts += 4  # PRIMARY_KW_IN_FIRST_80_CHARS
    elif kw_lower not in title[:100].lower():
        pts -= 4  # KEYWORD_BURIED_IN_BACK_HALF
        flags.append("KEYWORD_BURIED_IN_BACK_HALF")

    if any(_contains(title, kw) for kw in secondary_kws if kw):
        pts += 3  # SECONDARY_KW_IN_TITLE

    return max(0, min(25, pts)), flags


def _d2_title_structure(title: str, brand: str) -> tuple[int, list[str]]:
    """Dimension 2 — Title Structure (max 15 pts)."""
    pts = 0
    flags: list[str] = []
    tl = title.lower()
    toks = _tokens(title)

    # Brand checks
    if brand and brand.lower() in tl:
        pts += 3  # BRAND_NAME_PRESENT
        if tl.startswith(brand.lower()):
            pts += 3  # BRAND_FIRST

    # Product type: at least 2 meaningful non-brand, non-spec words present
    brand_toks = set(_tokens(brand)) if brand else set()
    meaningful = [w for w in toks if w not in brand_toks and w not in _FUNCTION_WORDS and len(w) > 3]
    if len(meaningful) >= 2:
        pts += 3  # PRODUCT_TYPE_PRESENT

    # Spec attribute: numeric unit pattern
    if _SPEC_UNITS.search(title):
        pts += 2  # TITLE_HAS_KEY_ATTRIBUTE

    # Length
    tlen = len(title)
    if 80 <= tlen <= 200:
        pts += 2  # TITLE_LENGTH_OPTIMAL
    elif tlen > 200:
        pts -= 15
        flags.append("TITLE_TOO_LONG")
    elif tlen < 40:
        pts -= 8
        flags.append("TITLE_UNDER_OPTIMISED")

    # Superlatives — deduct per occurrence, cap at -10
    sup_count = 0
    for sup in _SUPERLATIVES:
        if sup in tl:
            pts -= 5
            sup_count += 1
            flags.append(f"SUPERLATIVE_FOUND:{sup}")
            if sup_count >= 2:
                break
    if sup_count == 0:
        pts += 2  # NO_SUPERLATIVES

    # Banned opener
    first_word = toks[0] if toks else ""
    two_words = " ".join(toks[:2]) if len(toks) >= 2 else first_word
    if first_word in _BANNED_OPENERS or two_words in _BANNED_OPENERS:
        pts -= 5
        flags.append("BANNED_OPENER")

    # Special characters / emoji
    if _SPECIAL_CHARS.search(title):
        pts -= 3
        flags.append("SPECIAL_CHARS_ABUSE")

    # Keyword stuffing: < 8% function-word ratio in titles with >= 8 words
    if len(toks) >= 8:
        fn_ratio = sum(1 for w in toks if w in _FUNCTION_WORDS) / len(toks)
        if fn_ratio < 0.08:
            pts -= 8
            flags.append("KEYWORD_STUFFED_TITLE")

    return max(0, min(15, pts)), flags


def _d3_mobile_optimisation(title: str, primary_kw: str, brand: str) -> tuple[int, list[str]]:
    """Dimension 3 — Mobile Optimisation (max 15 pts)."""
    pts = 0
    flags: list[str] = []
    mobile = title[:80]
    m_lower = mobile.lower()

    if brand and brand.lower() in m_lower:
        pts += 4  # MOBILE_HAS_BRAND

    kw_in_mobile = primary_kw and primary_kw.lower() in m_lower
    if kw_in_mobile:
        pts += 5  # MOBILE_HAS_PRIMARY_KW
    else:
        pts -= 10
        flags.append("MOBILE_KEYWORD_MISSING")

    # Product type in mobile: meaningful word beyond brand
    brand_toks = set(_tokens(brand)) if brand else set()
    non_brand = [w for w in _tokens(mobile) if w not in brand_toks and w not in _FUNCTION_WORDS and len(w) > 3]
    if len(non_brand) >= 2:
        pts += 3  # MOBILE_HAS_PRODUCT_TYPE

    # Readable: enough words to be coherent
    if len(_tokens(mobile)) >= 5:
        pts += 3  # MOBILE_READABLE

    # Truncated mid-word: char 80 cuts inside a word
    if len(title) > 80 and title[79] not in " ,-/|\\":
        pts -= 5
        flags.append("MOBILE_TRUNCATED_MID_WORD")

    # Brand + filler only (brand present but keyword absent)
    if brand and brand.lower() in m_lower and not kw_in_mobile:
        pts -= 5
        flags.append("MOBILE_ONLY_BRAND")

    return max(0, min(15, pts)), flags


def _d4_bullet_compliance(
    bullets: list[str], primary_kw: str, secondary_kws: list[str]
) -> tuple[int, list[str]]:
    """Dimension 4 — Bullet Compliance (max 20 pts)."""
    pts = 0
    flags: list[str] = []

    non_empty = [b for b in bullets if b.strip()]
    n = len(non_empty)

    # Count / empty penalties
    if n == 5:
        pts += 8
    elif n >= 3:
        pts -= 5
        flags.append("TOO_FEW_BULLETS")
    else:
        pts -= 12
        flags.append("TOO_FEW_BULLETS")

    for i, b in enumerate(bullets):
        if not b.strip():
            pts -= 6
            flags.append(f"EMPTY_BULLET_{i + 1}")

    # Keyword in first 10 words of each bullet
    kw_hit = 0
    all_kws = [primary_kw] + [k for k in secondary_kws if k]
    for i, b in enumerate(non_empty):
        first_10 = " ".join(_tokens(b)[:10])
        if any(_contains(first_10, kw) for kw in all_kws if kw):
            kw_hit += 1
        else:
            pts -= 3
            flags.append(f"NO_KEYWORD_IN_BULLET_{i + 1}")
    if kw_hit >= 3:
        pts += 5  # KW_IN_FIRST_10_WORDS_EACH

    # Byte limit
    all_within = all(len(b.encode("utf-8")) <= 500 for b in non_empty)
    if all_within and non_empty:
        pts += 4  # ALL_BULLETS_WITHIN_LIMIT
    else:
        for i, b in enumerate(non_empty):
            if len(b.encode("utf-8")) > 500:
                pts -= 4
                flags.append(f"BULLET_{i + 1}_OVER_LIMIT")

    # Benefit-led (not feature-label opener)
    benefit_count = sum(1 for b in non_empty if not _FEATURE_LABEL.match(b.strip()))
    if benefit_count == n and n > 0:
        pts += 3  # BENEFIT_LED_BULLETS

    # Superlatives in bullets
    for i, b in enumerate(non_empty):
        b_lower = b.lower()
        if any(sup in b_lower for sup in ("best", "#1", "amazing", "unbeatable")):
            pts -= 3
            flags.append(f"SUPERLATIVE_IN_BULLET_{i + 1}")

    # Identical opening phrases (first 3 tokens)
    if n >= 3:
        openers = [" ".join(_tokens(b)[:3]) for b in non_empty]
        if len(set(openers)) == 1:
            pts -= 4
            flags.append("BULLETS_IDENTICAL_OPENING")

    return max(0, min(20, pts)), flags


def _d5_backend_keywords(
    backend_kw: str, title: str, bullets: list[str]
) -> tuple[int, list[str]]:
    """Dimension 5 — Backend Keywords (max 10 pts)."""
    if not backend_kw:
        return 0, []

    pts = 0
    flags: list[str] = []
    byte_len = len(backend_kw.encode("utf-8"))

    if byte_len > 249:
        flags.append("BACKEND_OVER_BYTE_LIMIT")
        return 0, flags  # entire score wiped, flagged critical

    if byte_len >= 200:
        pts += 5  # BACKEND_FILLS_LIMIT
    elif byte_len < 80:
        pts -= 5
        flags.append("BACKEND_UNDERUTILISED")

    # No front-end duplicates
    frontend_words = set(_tokens(title))
    for b in bullets:
        frontend_words.update(_tokens(b))
    backend_words = set(_tokens(backend_kw))
    if not (backend_words & frontend_words):
        pts += 3  # NO_FRONTEND_DUPLICATES
    else:
        pts -= 3
        flags.append("BACKEND_DUPLICATES_FRONTEND")

    # No internal duplicates
    word_list = _tokens(backend_kw)
    if len(word_list) == len(set(word_list)):
        pts += 2  # NO_INTERNAL_DUPLICATES
    else:
        pts -= 4
        flags.append("BACKEND_HAS_DUPLICATES")

    # No punctuation
    if re.search(r"[,;]", backend_kw):
        pts -= 2
        flags.append("BACKEND_HAS_PUNCTUATION")

    return max(0, min(10, pts)), flags


def _d6_browse_node(browse_node: str, category: str) -> tuple[int, list[str]]:
    """Dimension 6 — Browse Node + Category (max 10 pts)."""
    if not browse_node:
        return 0, ["BROWSE_NODE_MISSING"]

    pts = 5  # BROWSE_NODE_PRESENT
    flags: list[str] = []

    levels = [s.strip() for s in re.split(r"[/>\|]", browse_node) if s.strip()]
    if len(levels) >= 2:
        pts += 3  # BROWSE_NODE_HAS_DEPTH
    else:
        pts -= 4
        flags.append("BROWSE_NODE_TOO_BROAD")

    if category and any(
        c.lower() in browse_node.lower() for c in _tokens(category) if len(c) > 3
    ):
        pts += 2  # BROWSE_NODE_MATCHES_CATEGORY

    return max(0, min(10, pts)), flags


def _d7_attributes(attributes: dict) -> tuple[int, list[str]]:
    """Dimension 7 — Attribute Completeness (max 3 pts)."""
    if not attributes:
        return 0, ["NO_ATTRIBUTES"]

    pts = 0
    if len(attributes) >= 3:
        pts += 2  # HAS_STRUCTURED_ATTRIBUTES

    variant_keys = {"colour", "color", "size", "pack_size", "variant", "pack", "model"}
    if any(k.lower() in variant_keys for k in attributes):
        pts += 1  # HAS_VARIANT_DATA

    return max(0, min(3, pts)), []


def _d8_content_richness(description: str, aplus_content: str) -> tuple[int, list[str]]:
    """Dimension 8 — Content Richness (max 2 pts)."""
    pts = 0
    flags: list[str] = []
    desc_len = len(description.strip())

    if desc_len >= 100:
        pts += 1  # DESCRIPTION_PRESENT
    elif 0 < desc_len < 50:
        pts -= 1
        flags.append("DESCRIPTION_VERY_SHORT")

    if aplus_content and aplus_content.strip():
        pts += 1  # APLUS_PRESENT

    return max(0, min(2, pts)), flags


# ── public result type ─────────────────────────────────────────────────────────

@dataclass
class A9Result:
    score: int
    breakdown: dict[str, int]
    flags: list[str] = field(default_factory=list)


# ── public entry-point ─────────────────────────────────────────────────────────

def score_a9(
    title: str,
    bullets: list[str],
    description: str = "",
    backend_keywords: str = "",
    browse_node: str = "",
    brand: str = "",
    category: str = "",
    aplus_content: str = "",
    attributes: dict | None = None,
    primary_keyword: str = "",
    secondary_keywords: list[str] | None = None,
) -> A9Result:
    """
    Run all 8 A9 dimensions and return an A9Result.

    primary_keyword is auto-extracted from backend_keywords / title when absent.
    """
    attributes = attributes or {}
    secondary_keywords = secondary_keywords or []

    if not primary_keyword:
        primary_keyword = _extract_fallback_keyword(title, backend_keywords)

    d1, f1 = _d1_title_keyword(title, primary_keyword, secondary_keywords)
    d2, f2 = _d2_title_structure(title, brand)
    d3, f3 = _d3_mobile_optimisation(title, primary_keyword, brand)
    d4, f4 = _d4_bullet_compliance(bullets, primary_keyword, secondary_keywords)
    d5, f5 = _d5_backend_keywords(backend_keywords, title, bullets)
    d6, f6 = _d6_browse_node(browse_node, category)
    d7, f7 = _d7_attributes(attributes)
    d8, f8 = _d8_content_richness(description, aplus_content)

    total = max(0, min(100, d1 + d2 + d3 + d4 + d5 + d6 + d7 + d8))

    # Deduplicate flags while preserving order
    seen: set[str] = set()
    all_flags: list[str] = []
    for f in f1 + f2 + f3 + f4 + f5 + f6 + f7 + f8:
        if f not in seen:
            seen.add(f)
            all_flags.append(f)

    return A9Result(
        score=total,
        breakdown={
            "title_keyword":        d1,
            "title_structure":      d2,
            "mobile_optimisation":  d3,
            "bullet_compliance":    d4,
            "backend_keywords":     d5,
            "browse_node":          d6,
            "attribute_completeness": d7,
            "content_richness":     d8,
        },
        flags=all_flags,
    )
