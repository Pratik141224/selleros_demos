"""
demo1_abd_optimizer/agents.py

Three-pass Claude pipeline for the Title, Bullet & Description ABD Optimizer.

Pass 1 — A9 Discovery Variant  (keyword-dense, algorithm-first)
Pass 2 — Rufus Conversion Variant  (intent-aligned, buyer-first)
Pass 3 — Scoring + Hybrid Merge  (compare + recommend)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.claude_client import call_claude
from omkar_client import build_competitor_block

CATEGORY_LABELS = {
    "electronics": "Electronics / Audio & Headphones",
    "fashion":     "Fashion / Men's Casual T-shirts",
    "kitchen":     "Kitchen & Home / Cookware & Pans",
    "fitness":     "Sports & Fitness / Yoga Mats",
    "skincare":    "Beauty / Face Moisturisers",
    "custom":      "General consumer product",
}


# ─────────────────────────────────────────────
# PASS 1 — A9 DISCOVERY VARIANT
# ─────────────────────────────────────────────

PASS1_SYSTEM = """You are an Amazon A9 SEO compliance specialist for Indian e-commerce sellers.

Generate a DISCOVERY-FIRST variant of the provided product listing.
Optimise for Amazon's A9 search algorithm — maximum keyword indexing.

HARD RULES (never violate):
  Title:
    - ≤200 characters total
    - Primary keyword MUST appear within the first 5 words
    - Brand name first, then product type, then key attributes
    - First 80 characters must contain the primary keyword (mobile CTR)
    - No Special Characters that aren't supported by Amazon's backend (e.g. emojis, trademark symbols)
  Bullets:
    - Exactly 5 bullets
    - Each bullet ≤500 bytes
    - Primary or secondary keyword in the first 10 words of each bullet
    - Benefit-first language, spec-detail second
    - NO superlatives: no "best", "#1", "amazing", "unbeatable"
    - No Special Characters that aren't supported by Amazon's backend (e.g. emojis, trademark symbols)
  Description:
    - ≤2000 characters
    - Can be more keyword-dense than bullets, but still natural language
    - Include any relevant keywords not in title/bullets, but avoid keyword stuffing
    - Use HTML formatting for readability (line breaks, bold for key features), but no keyword stuffing
    - No Special Characters that aren't supported by Amazon's backend (e.g. emojis, trademark symbols)
  Style: keyword-dense, spec-forward — algorithm-optimised, not human-first

Also score the ORIGINAL listing on:
  - a9_compliance: 0–100 (keyword placement, byte limits, browse node logic)
  - rufus_readiness: 0–100 (intent alignment, persona specificity, FAQ-readiness)
  - keywords_found: count of high-volume category keywords present in original

Output ONLY valid JSON. No markdown. No preamble."""

PASS1_USER_TEMPLATE = """Product category: {category}
Current title: "{title}"
Current bullets:
{bullets}
Current description:
{description}

{competitor_block}
Return exactly this JSON:
{{
  "original_scores": {{
    "a9_compliance": 0,
    "rufus_readiness": 0,
    "keywords_found": 0
  }},
  "variant_a": {{
    "title": "",
    "bullets": ["","","","",""],
    "description": "",
    "scores": {{
      "keyword_density": 0,
      "intent_alignment": 0,
      "conversion_signals": 0
    }},
    "keywords_added": ["","","",""],
    "char_count": 0
  }}
}}"""


# ─────────────────────────────────────────────
# PASS 2 — RUFUS CONVERSION VARIANT
# ─────────────────────────────────────────────

PASS2_SYSTEM = """You are an Amazon Rufus conversion specialist for Indian e-commerce sellers.

Generate a CONVERSION-FIRST variant of the product listing.
Optimise for Amazon's Rufus AI assistant and COSMO intent graph — buyer psychology first.

Rufus reads listings to answer shopper questions. Each bullet must answer one implicit question:
for e.g
  Bullet 1: "Is this right for my situation / use case?"
  Bullet 2: "Will it last — is it worth the price?"
  Bullet 3: "What are the known problems with products like this?" (objection pre-empt)
  Bullet 4: "How does it compare to alternatives?"
  Bullet 5: "Who else buys this, and for what situation?"
These Questions will vary by category and product, so use your judgement to identify the most relevant ones for the product's category and type.
RULES:
  Title:
    - ≤200 characters
    - First 80 chars: A9-minimum compliant (Brand + Type + main keyword)
    - Remaining chars: written for a human, not an algorithm
  Bullets:
    - Exactly 5
    - Each ≤500 bytes
    - Keyword in first 10 words (A9 minimum)
    - Body: natural language, persona-aware, specific use cases
  Description:
    - ≤2000 characters
    - Natural language, storytelling style
    - Address any relevant keywords not in title/bullets, but avoid keyword stuffing
    - Use HTML formatting for readability (line breaks, bold for key features)
    - No Special Characters that aren't supported by Amazon's backend (e.g. emojis, trademark symbols)
  Style: conversational, trust-building, intent-aligned — NO keyword stuffing

Output ONLY valid JSON. No markdown. No preamble."""

PASS2_USER_TEMPLATE = """Product category: {category}
Original title: "{title}"
Original bullets:
{bullets}
Original description (for context):
{description}

{competitor_block}
Variant A title (use as A9-compliance reference): "{variant_a_title}"

Return exactly this JSON:
{{
  "variant_b": {{
    "title": "",
    "bullets": ["","","","",""],
    "description": "",
    "scores": {{
      "keyword_density": 0,
      "intent_alignment": 0,
      "conversion_signals": 0
    }},
    "personas_addressed": ["",""],
    "objections_handled": ["",""]
  }}
}}"""


# ─────────────────────────────────────────────
# PASS 3 — SCORING + HYBRID MERGE
# ─────────────────────────────────────────────

PASS3_SYSTEM = """You are a listing optimisation judge for SellerOS.

Given two listing variants (A = discovery-first, B = conversion-first), you will:
1. Confirm / refine scores for both on 3 dimensions (0–100 each).
2. Generate a HYBRID TITLE that merges the best of both variants.
3. Write a 2–3 sentence rationale explaining the tradeoff and why the hybrid resolves it.
4. Project CTR and CVR improvement ranges for the hybrid vs the original.

HYBRID TITLE RULES:
  - First 80 chars: A9-compliant (Brand + Type + top 2 keywords) — non-negotiable
  - Characters 81–200: natural language written for the human buyer
  - Total ≤200 characters

Output ONLY valid JSON. No markdown. No preamble."""

PASS3_USER_TEMPLATE = """Variant A (discovery-first):
Title: "{va_title}"
Scores: keyword_density={va_kd}, intent_alignment={va_ia}, conversion_signals={va_cs}

Variant B (conversion-first):
Title: "{vb_title}"
Scores: keyword_density={vb_kd}, intent_alignment={vb_ia}, conversion_signals={vb_cs}

Product category: {category}

Return exactly this JSON:
{{
  "variant_a_scores": {{
    "keyword_density": 0,
    "intent_alignment": 0,
    "conversion_signals": 0
  }},
  "variant_b_scores": {{
    "keyword_density": 0,
    "intent_alignment": 0,
    "conversion_signals": 0
  }},
  "hybrid_title": "",
  "hybrid_rationale": "",
  "recommended_variant": "A or B or hybrid",
  "projected_ctr_improvement": "X–Y%",
  "projected_cvr_improvement": "X–Y%"
}}"""


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_ab_optimization(
    title: str,
    bullets: list[str],
    description: str = "",
    category: str = "electronics",
    competitor_context: list[dict] | None = None,
) -> dict:
    category_label = CATEGORY_LABELS.get(category, category)
    bullets_text = "\n".join(
        f"  {i+1}. {b}" for i, b in enumerate(bullets) if b.strip()
    )
    comp_block_kw   = build_competitor_block(competitor_context or [], purpose="keyword")
    comp_block_conv = build_competitor_block(competitor_context or [], purpose="conversion")

    # ── PASS 1 ──────────────────────────────
    print("[SellerOS] Pass 1: Generating A9 discovery variant...")

    pass1_result = call_claude(
        PASS1_SYSTEM,
        PASS1_USER_TEMPLATE.format(
            category=category_label,
            title=title,
            bullets=bullets_text,
            description=description,
            competitor_block=comp_block_kw,
        ),
        max_tokens=2500,
    )

    variant_a = pass1_result.get("variant_a", {})
    va_title  = variant_a.get("title", title)
    va_scores = variant_a.get("scores", {})

    # ── PASS 2 ──────────────────────────────
    print("[SellerOS] Pass 2: Generating Rufus conversion variant...")

    pass2_result = call_claude(
        PASS2_SYSTEM,
        PASS2_USER_TEMPLATE.format(
            category=category_label,
            title=title,
            bullets=bullets_text,
            description=description,
            competitor_block=comp_block_conv,
            variant_a_title=va_title,
        ),
        max_tokens=2500,
    )

    variant_b = pass2_result.get("variant_b", {})
    vb_title  = variant_b.get("title", title)
    vb_scores = variant_b.get("scores", {})

    # ── PASS 3 ──────────────────────────────
    print("[SellerOS] Pass 3: Scoring + generating hybrid recommendation...")

    pass3_result = call_claude(
        PASS3_SYSTEM,
        PASS3_USER_TEMPLATE.format(
            va_title=va_title,
            va_kd=va_scores.get("keyword_density", 0),
            va_ia=va_scores.get("intent_alignment", 0),
            va_cs=va_scores.get("conversion_signals", 0),
            vb_title=vb_title,
            vb_kd=vb_scores.get("keyword_density", 0),
            vb_ia=vb_scores.get("intent_alignment", 0),
            vb_cs=vb_scores.get("conversion_signals", 0),
            category=category_label,
        ),
        max_tokens=1500,
    )

    # ── MERGE ────────────────────────────────
    # Use pass 3's refined scores if available, fallback to pass 1/2 scores
    va_final = pass3_result.get("variant_a_scores", va_scores)
    vb_final = pass3_result.get("variant_b_scores", vb_scores)

    return {
        # Original scores
        "original_scores": pass1_result.get("original_scores", {}),

        # Variant A
        "variant_a": {
            **variant_a,
            "scores": va_final,
        },

        # Variant B
        "variant_b": {
            **variant_b,
            "scores": vb_final,
        },

        # Hybrid
        "hybrid": {
            "title":     pass3_result.get("hybrid_title", ""),
            "rationale": pass3_result.get("hybrid_rationale", ""),
            "recommended": pass3_result.get("recommended_variant", "hybrid"),
        },

        # Impact projections
        "impact": {
            "ctr_improvement": pass3_result.get("projected_ctr_improvement", "—"),
            "cvr_improvement": pass3_result.get("projected_cvr_improvement", "—"),
        },
    }
