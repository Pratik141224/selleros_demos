"""
keyword_gap/agents.py

Two-step pipeline for the Keyword Gap Analyzer.

Step 1 — Deterministic (no LLM)
  → keyword extraction from seller listing text
  → backend string parsing: byte count, duplicate detection, compliance check
  → competitor keyword union + per-keyword competitor coverage count

Step 2 — Claude gap + backend generation (TaskType.STRUCTURED)
  → identifies missing_critical and missing_secondary gaps
  → each gap item carries: keyword, competitor_coverage, gap_type,
    suggested_placement, intent_type — NO fake monthly_volume or opportunity_score
  → generates optimised ≤249-byte backend string across all 8 keyword categories
"""

import re
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.llm_router import call, TaskType

STOP_WORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','with',
    'by','from','is','are','was','were','be','been','being','have','has',
    'had','do','does','did','will','would','could','should','may','might',
    'shall','can','our','your','their','its','this','that','these','those',
    'i','you','he','she','we','they','it','my','his','her','us','them',
    'as','if','so','no','not','all','any','each','more','some','such',
    'into','up','out','also','just','very','then','than','too','most',
}

CATEGORY_LABELS = {
    "electronics": "Electronics / Audio & Headphones",
    "fashion":     "Fashion / Men's Casual T-shirts",
    "kitchen":     "Kitchen & Home / Cookware & Pans",
    "fitness":     "Sports & Fitness / Yoga Mats",
    "skincare":    "Beauty / Face Moisturisers",
    "custom":      "General consumer product",
}


# ─────────────────────────────────────────────
# STEP 1 — DETERMINISTIC FUNCTIONS (no LLM)
# ─────────────────────────────────────────────

def extract_keywords(text: str) -> dict:
    """
    Extract unigrams, bigrams, trigrams, and numeric patterns from listing text.
    Deterministic — no LLM.
    """
    all_words = re.findall(r'\b[a-z0-9]+\b', text.lower())
    clean = [w for w in all_words if w not in STOP_WORDS and len(w) > 1]

    unigrams = list(dict.fromkeys(clean))

    bigrams = []
    for i in range(len(all_words) - 1):
        bg = all_words[i] + ' ' + all_words[i + 1]
        if bg not in bigrams:
            bigrams.append(bg)

    trigrams = []
    for i in range(len(all_words) - 2):
        tg = ' '.join(all_words[i:i + 3])
        if tg not in trigrams:
            trigrams.append(tg)

    numerics = list(dict.fromkeys(
        re.findall(r'\b\d+(?:\.\d+)?\s*(?:mm|cm|m|ml|l|kg|gm|g|mah|w|v|hz|db|inch|ft)?\b', text.lower())
    ))

    return {
        "unigrams":  unigrams[:60],
        "bigrams":   bigrams[:35],
        "trigrams":  trigrams[:20],
        "numerics":  numerics[:15],
    }


def parse_backend_string(backend: str, title: str = "", bullets: list | None = None) -> dict:
    """
    Parse and audit an existing backend keyword string.
    Returns byte count, duplicate detection, and compliance flags.
    """
    bullets = bullets or []

    if not backend or not backend.strip():
        return {
            "words": [], "bytes": 0, "word_count": 0,
            "unique_words": 0, "has_content": False,
            "frontend_duplicates": [], "internal_duplicates": [],
            "has_punctuation": False, "compliance_pass": True,
        }

    frontend_words = set(re.findall(
        r'\b[a-z0-9]+\b',
        (title + " " + " ".join(bullets)).lower()
    ))

    backend_words = backend.lower().split()
    word_freq: dict[str, int] = {}
    for w in backend_words:
        word_freq[w] = word_freq.get(w, 0) + 1

    frontend_dupes = sorted(set(w for w in backend_words if w in frontend_words))
    internal_dupes = sorted(w for w, c in word_freq.items() if c > 1)
    byte_count = len(backend.encode("utf-8"))
    has_punctuation = bool(re.search(r'[,;|]', backend))

    return {
        "words": backend_words,
        "bytes": byte_count,
        "word_count": len(backend_words),
        "unique_words": len(set(backend_words)),
        "has_content": True,
        "frontend_duplicates": frontend_dupes,
        "internal_duplicates": internal_dupes,
        "has_punctuation": has_punctuation,
        "compliance_pass": (
            byte_count <= 249
            and not frontend_dupes
            and not internal_dupes
            and not has_punctuation
        ),
    }


def build_competitor_keyword_freq(competitors: list) -> dict[str, int]:
    """
    For each keyword that appears in at least one competitor's text, count how many
    distinct competitors use it. Returns {keyword: count} sorted by count desc.
    Deterministic — no LLM.
    """
    freq: dict[str, int] = {}
    for comp in competitors:
        comp_text = (
            comp.get("title", "") + " "
            + " ".join(comp.get("bullets", [])) + " "
            + comp.get("description", "")
        )
        # Use a set per competitor so each keyword counts once per competitor
        kws = set(
            extract_keywords(comp_text)["unigrams"]
            + extract_keywords(comp_text)["bigrams"]
        )
        for kw in kws:
            freq[kw] = freq.get(kw, 0) + 1
    return dict(sorted(freq.items(), key=lambda x: x[1], reverse=True))


def calculate_indexation_gap(
    seller_keywords: list,
    competitor_keyword_freq: dict[str, int],
    backend_audit: dict,
) -> int:
    """
    Score 0–100: how complete is keyword coverage vs competitors.
    100 = indexed for everything top competitors are indexed for.
    Formula: frontend coverage 55% + backend fill 25% + backend cleanliness 20%.
    """
    seller_set = {k.lower() for k in seller_keywords}
    comp_set   = set(competitor_keyword_freq.keys())

    overlap = len(seller_set & comp_set)
    frontend_coverage = overlap / max(len(comp_set), 1)

    backend_fill = min(1.0, backend_audit.get("bytes", 0) / 249)

    dupe_count = len(backend_audit.get("frontend_duplicates", []))
    word_count = max(backend_audit.get("word_count", 1), 1)
    backend_clean = 1.0 - (dupe_count / word_count)

    score = int(
        (frontend_coverage * 0.55 +
         backend_fill      * 0.25 +
         backend_clean     * 0.20) * 100
    )
    return max(0, min(100, score))


# ─────────────────────────────────────────────
# STEP 2 — CLAUDE GAP + BACKEND GENERATION
# ─────────────────────────────────────────────

_SYSTEM = """You are a senior Amazon keyword strategist with 9 years optimising product indexation on Amazon India. You understand the full stack: A9 frontend indexation, backend keyword architecture, and Rufus semantic intent matching.

Your job: analyse the keyword gap between a seller's listing and top competitors, then generate a ready-to-paste optimised backend keyword string.

The human voice rules appended at the end of these instructions apply to ALL descriptive text fields you generate (rewritten_title_snippet, content_gaps descriptions, any rationale strings). Non-negotiable.

━━━ HARD RULES — KEYWORD GAP ANALYSIS ━━━

1. Only report keywords present in the competitor data or clearly inferrable from the seller's listing. Do not invent keywords.
2. gap_type must be exactly one of: "frontend" | "backend" | "both"
     "frontend"  = keyword belongs in visible content (title, bullets, description)
     "backend"   = keyword only belongs in backend search terms field
     "both"      = currently absent from both and could serve in either
3. suggested_placement must be exactly one of:
     "title" | "bullet_1" | "bullet_2" | "bullet_3" | "bullet_4" | "bullet_5" | "backend" | "description"
4. intent_type must be exactly one of: "discovery" | "comparison" | "purchase" | "use_case"
5. competitor_coverage: integer — use the pre-computed coverage counts provided in the COMPETITOR KEYWORD FREQUENCIES section. Do not guess or invent counts.
6. Rank missing_critical items by competitor_coverage descending (highest coverage first). These are the gaps that matter most because real competing listings already use them.
7. missing_critical = keywords absent from seller listing that appear in ≥2 competitor listings AND belong in visible content (title/bullets/description).
   missing_secondary = keywords absent from seller listing that appear in 1 competitor OR belong only in backend search terms.

━━━ HARD RULES — BACKEND STRING GENERATION ━━━

generated_backend_string — ALL must pass:
  ✗ No competitor brand names — listing suspension risk
  ✗ No words already in seller's title — A9 already indexes them, wasted bytes
  ✗ No words already in seller's bullets — same reason
  ✗ No commas, semicolons, pipes, or punctuation — not indexed, wastes bytes
  ✗ No promotional terms: "cheap", "discount", "best price", "offer"
  ✗ No repeated words — internal duplicates are wasted bytes
  ✗ No plurals of words already in front-end content
  ✗ Total ≤249 bytes (UTF-8 encoded)
  ✓ Single space-separated string, no commas, no line breaks
  ✓ Ready to paste directly into Amazon backend search terms field

━━━ BACKEND BYTE ALLOCATION STRATEGY ━━━

Fill in this priority order, staying ≤249 bytes total:
  Priority 1 (~100 bytes): synonyms + long_tail phrases
  Priority 2 (~80 bytes):  intent_phrases + locale_variants (IN only)
  Priority 3 (~50 bytes):  numeric_text_pairs + spelling_variants
  Reserved   (~19 bytes):  space for seller's PPC harvest additions later

━━━ 8 BACKEND KEYWORD CATEGORIES — fill ALL ━━━

1. SYNONYMS — alternate product names. Every byte on a front-end duplicate is a wasted byte.
   "earphones" → also index: earbuds, ear tips, in-ear headphones
   Rule: Never duplicate exact words already in title, bullets, or description.

2. LONG-TAIL USE-CASE PHRASES — 2–5 word phrases, strong purchase intent.
   "noise cancelling earphones open office", "airtight container dal indian kitchen"
   Rule: Natural phrases, no commas. Lower competition = easier to rank.

3. SPELLING VARIANTS — realistic misspellings with actual search volume.
   "vaccum" (vacuum), "jewellery"/"jewelry", "hairdrier"/"hair dryer"/"hairdryer"
   Rule: Only high-frequency alternates — not every possible typo.

4. NUMERIC & TEXT VARIANTS — A9 treats numbers and text differently. Include both forms.
   "5 litre" AND "five litre" AND "5l" AND "5000ml"
   "40mm driver" AND "forty millimetre driver"
   Rule: Both numeric and spelled-out version of every spec mentioned in listing.

5. INTENT PHRASES — problem-solution framing optimised for Rufus intent matching.
   "gift for husband birthday under 2000", "earphones that stay in ear while jogging"
   Rule: Frame as problem or occasion, not product feature. 3–5 maximum (high byte cost).

6. LOCALE VARIANTS (IN) — India-specific terms. Primary product category noun only.
   "iyarfon" (earphone), "kadai" alongside "wok", "torch light" alongside "flashlight"
   Rule: Only terms with realistic Indian search volume. Do not transliterate every attribute.

7. SEASONAL — event-driven terms flagged for seller rotation.
   "diwali gift", "rakhi gift for brother", "monsoon sale", "back to school"
   Rule: Generated but flagged in backend_keyword_sets.seasonal. Do not fill byte limit with these.

8. PPC HARVEST — converting PPC search terms not yet in organic content.
   Rule: Only from the ppc_search_terms provided. Only terms NOT already in title/bullets.

━━━ REWRITTEN TITLE SNIPPET ━━━

Embed the top-3 missing_critical keywords (highest competitor_coverage first) into the seller's existing title structure.
Keep the original flow. Put the highest-coverage missing keyword in first 5 words.
Total ≤200 chars. No superlatives. No exclamation marks. No "Introducing" or "Experience".

Output ONLY valid JSON. No markdown. No preamble."""


_USER_TEMPLATE = """Product category: {category}
Target locale: {locale}

━━━ SELLER LISTING ━━━
Title: "{title}"
Bullets:
{bullets}
Description:
{description}

━━━ BACKEND KEYWORD AUDIT (pre-computed, deterministic) ━━━
Current backend string: "{backend_raw}"
Bytes used: {backend_bytes} / 249
Bytes available: {bytes_available}
Frontend duplicates in backend (wasted bytes): {frontend_dupes_str}
Internal duplicates in backend (wasted bytes): {internal_dupes_str}
Compliance issues: {compliance_issues}

━━━ SELLER EXTRACTED KEYWORDS ━━━
Unigrams (top 25): {seller_unigrams}
Bigrams (top 15): {seller_bigrams}

━━━ COMPETITOR DATA ━━━
{competitor_block}

━━━ COMPETITOR KEYWORD FREQUENCIES (pre-computed, deterministic) ━━━
Format: keyword(count_of_competitors_using_it)
Top keywords by competitor coverage:
{comp_freq_block}

Use these counts directly as competitor_coverage values in your gap items.

━━━ PPC SEARCH TERMS ━━━
{ppc_block}

Return exactly this JSON:
{{
  "seller_keywords": [],
  "competitor_keywords": [],
  "missing_critical": [
    {{
      "keyword": "",
      "competitor_coverage": 0,
      "gap_type": "both",
      "suggested_placement": "title",
      "intent_type": "discovery"
    }}
  ],
  "missing_secondary": [
    {{
      "keyword": "",
      "competitor_coverage": 0,
      "gap_type": "backend",
      "suggested_placement": "backend",
      "intent_type": "discovery"
    }}
  ],
  "content_gaps": [],
  "rewritten_title_snippet": "",
  "backend_audit": {{
    "current_bytes_used": {backend_bytes},
    "bytes_available": {bytes_available},
    "current_duplicates": {frontend_dupes_json},
    "current_internal_dupes": {internal_dupes_json},
    "compliance_issues": []
  }},
  "generated_backend_string": "",
  "backend_keyword_sets": {{
    "synonyms": [],
    "long_tail": [],
    "spelling_variants": [],
    "numeric_text_pairs": [],
    "intent_phrases": [],
    "locale_variants": [],
    "seasonal": [],
    "ppc_harvest": []
  }},
  "backend_byte_plan": {{
    "total_available": 249,
    "allocated": 0,
    "remaining": 0,
    "slot_breakdown": [
      {{"keyword_group": "synonyms + long_tail", "bytes_used": 0, "priority": 1}},
      {{"keyword_group": "intent_phrases + locale_variants", "bytes_used": 0, "priority": 2}},
      {{"keyword_group": "numeric_text_pairs + spelling_variants", "bytes_used": 0, "priority": 3}},
      {{"keyword_group": "ppc_harvest (reserved)", "bytes_used": 0, "priority": 4}}
    ]
  }},
  "indexation_gap_score": 0
}}"""


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_keyword_gap_analysis(
    title: str,
    bullets: list,
    description: str = "",
    backend_keywords: str = "",
    competitors: list | None = None,
    category: str = "electronics",
    ppc_search_terms: list | None = None,
    target_locale: str = "IN",
    asin: str = "",
) -> dict:
    category_label   = CATEGORY_LABELS.get(category, category)
    competitors      = competitors or []
    ppc_search_terms = ppc_search_terms or []

    # ── AUTO-FETCH COMPETITORS ─────────────────
    # When an ASIN is provided but no competitor listings were passed in,
    # fetch them directly from CompetitorAnalysis so the gap analysis has
    # real competitor keyword data rather than running blind.
    if asin and not competitors:
        try:
            from shared.zyte_client import fetch_competitor_summaries
            print(f"[SellerOS] No competitors provided — auto-fetching for ASIN {asin}...")
            competitors = fetch_competitor_summaries(seed_asin=asin, n=5)
            if competitors:
                print(f"[SellerOS] Found {len(competitors)} competitor(s) for ASIN {asin}")
            else:
                print(f"[SellerOS] WARN: CompetitorAnalysis returned 0 competitors for ASIN {asin} — gap analysis will use category knowledge only")
        except Exception as exc:
            print(f"[SellerOS] WARN: competitor auto-fetch failed — {exc}")
            competitors = []

    # ── STEP 1: DETERMINISTIC ─────────────────
    print("[SellerOS] Step 1: Deterministic keyword extraction and backend audit...")

    listing_text = title + " " + " ".join(bullets) + " " + description
    seller_extracted = extract_keywords(listing_text)
    seller_keywords  = seller_extracted["unigrams"] + seller_extracted["bigrams"]

    backend_audit = parse_backend_string(backend_keywords, title, bullets)

    # Build per-keyword competitor coverage count (deterministic, grounded in real data)
    comp_keyword_freq = build_competitor_keyword_freq(competitors)

    indexation_gap = calculate_indexation_gap(seller_keywords, comp_keyword_freq, backend_audit)

    # Build compliance issues list
    compliance_issues: list = []
    if backend_audit["bytes"] > 249:
        compliance_issues.append("BACKEND_OVER_BYTE_LIMIT")
    if backend_audit["has_punctuation"]:
        compliance_issues.append("PUNCTUATION_IN_BACKEND")
    if backend_audit["internal_duplicates"]:
        compliance_issues.append("INTERNAL_DUPLICATES_FOUND")
    if backend_audit["frontend_duplicates"]:
        compliance_issues.append("FRONTEND_DUPLICATES_IN_BACKEND")

    # ── STEP 2: CLAUDE ────────────────────────
    print("[SellerOS] Step 2: Claude keyword gap analysis and backend generation...")

    bullets_text = "\n".join(
        f"  {i+1}. {b}" for i, b in enumerate(bullets) if b.strip()
    )

    # Competitor listing block (titles + bullets for context)
    comp_lines: list = []
    if competitors:
        comp_lines.append("Top competitors (for keyword gap analysis):")
        for i, c in enumerate(competitors, 1):
            bl = " | ".join(c.get("bullets", [])[:3]) or "—"
            comp_lines.append(f'{i}. Title: "{c.get("title", "")}"')
            comp_lines.append(f'   Bullets: {bl}')
            if c.get("description"):
                comp_lines.append(f'   Desc (excerpt): {c["description"][:200]}')
    competitor_block = "\n".join(comp_lines) if comp_lines else "No competitor data provided."

    # Pre-computed frequency block: top 50 competitor keywords with real coverage counts
    # Claude uses these exact integers as competitor_coverage in gap items — no guessing.
    top_freq = list(comp_keyword_freq.items())[:50]
    comp_freq_block = (
        "  " + ", ".join(f"{kw}({cnt})" for kw, cnt in top_freq)
        if top_freq else "No competitor keyword data available."
    )

    ppc_block = (
        "Converting PPC terms not yet in organic: " + ", ".join(ppc_search_terms)
        if ppc_search_terms else "None provided."
    )

    result = call(
        task_type=TaskType.STRUCTURED,
        system=_SYSTEM,
        user=_USER_TEMPLATE.format(
            category=category_label,
            locale=target_locale,
            title=title,
            bullets=bullets_text,
            description=(description or "")[:600],
            backend_raw=backend_keywords or "(none provided)",
            backend_bytes=backend_audit["bytes"],
            bytes_available=max(0, 249 - backend_audit["bytes"]),
            frontend_dupes_str=", ".join(backend_audit["frontend_duplicates"]) or "none",
            internal_dupes_str=", ".join(backend_audit["internal_duplicates"]) or "none",
            compliance_issues=", ".join(compliance_issues) if compliance_issues else "none",
            seller_unigrams=", ".join(seller_extracted["unigrams"][:25]),
            seller_bigrams=", ".join(seller_extracted["bigrams"][:15]),
            competitor_block=competitor_block,
            comp_freq_block=comp_freq_block,
            ppc_block=ppc_block,
            frontend_dupes_json=json.dumps(backend_audit["frontend_duplicates"]),
            internal_dupes_json=json.dumps(backend_audit["internal_duplicates"]),
        ),
        max_tokens=3500,
    ).content

    # Patch backend_audit with deterministic values (authoritative over LLM)
    if "backend_audit" in result:
        result["backend_audit"]["current_bytes_used"] = backend_audit["bytes"]
        result["backend_audit"]["bytes_available"]    = max(0, 249 - backend_audit["bytes"])
        result["backend_audit"]["current_duplicates"]      = backend_audit["frontend_duplicates"]
        result["backend_audit"]["current_internal_dupes"]  = backend_audit["internal_duplicates"]

    # Enforce ≤249 byte limit on generated_backend_string
    gen_backend = result.get("generated_backend_string", "")
    if gen_backend and len(gen_backend.encode("utf-8")) > 249:
        trimmed = gen_backend.encode("utf-8")[:249].decode("utf-8", errors="ignore")
        gen_backend = trimmed.rsplit(" ", 1)[0]
        result["generated_backend_string"] = gen_backend

    # Patch backend_byte_plan.allocated with actual byte count
    if result.get("backend_byte_plan") and gen_backend:
        actual_bytes = len(gen_backend.encode("utf-8"))
        result["backend_byte_plan"]["allocated"]  = actual_bytes
        result["backend_byte_plan"]["remaining"]  = max(0, 249 - actual_bytes)

    # Deterministic gap score (authoritative — overwrites any LLM value)
    result["indexation_gap_score"] = indexation_gap

    return result
