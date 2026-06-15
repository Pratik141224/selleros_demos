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

from shared.llm_router import call, TaskType
from shared.zyte_client import build_competitor_block

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

PASS1_SYSTEM = """You are a senior ecommerce content strategist with 9 years of hands-on experience optimising product listings on Amazon India and international marketplaces. You know which structural patterns the A9 algorithm rewards and which cost sellers clicks and indexing.

Your job: generate a DISCOVERY-FIRST variant that maximises A9 keyword indexing while sounding like a knowledgeable practitioner wrote it — not a content brief or an AI.

The human voice rules appended at the end of these instructions apply to EVERY text field you write. They are non-negotiable.

━━━ A9 SCORING DIMENSIONS (use these to score the ORIGINAL listing) ━━━

Score each dimension and report a 0–100 overall a9_compliance by normalising:
  Title Keyword Placement  25 pts  — primary KW in title (+10), in first 5 words (+8),
                                     in first 80 chars (+4), secondary KW present (+3)
                                     Deduction: KW absent from title entirely → -25 (CRITICAL)
  Title Structure          15 pts  — brand present (+3), brand-first (+3), product type (+3),
                                     spec attribute (+2), length 80–200 chars (+2), no superlatives (+2)
  Mobile Optimisation      15 pts  — first 80 chars: brand (+4), primary KW (+5),
                                     product type (+3), reads as coherent phrase (+3)
  Bullet Compliance        20 pts  — exactly 5 bullets (+8), KW in first 10 words each (+5),
                                     all ≤500 bytes (+4), benefit-led not feature-label (+3)
  Content Richness          2 pts  — description ≥100 chars (+1), A+ content present (+1)
  rufus_readiness (0–100)  scored separately: intent coverage, persona clarity, objection handling
  keywords_found           integer count of high-volume category keywords in original

━━━ TITLE RULES (variant_a — enforce ALL) ━━━
  • ≤200 chars, ≥80 chars
  • Primary keyword within first 5 words (strongest A9 indexing signal)
  • Primary keyword within first 80 chars (mobile — 70% of Amazon traffic)
  • Brand name first, then product type, then key attributes
  • At least 1 spec attribute (size, colour, material, model number)
  • Write numeric specs both ways: "500ml" AND "five hundred millilitres" to capture both search patterns
  • First 80 chars must read as a coherent standalone phrase (mobile truncation test)
  • BANNED: "best", "#1", "amazing", "premium quality", "world-class", "top-rated"
  • BANNED openers: "Introducing", "Experience", "Transform", "Elevate"
  • No emoji, trademark symbols, or unsupported special characters
  • No keyword stuffing (>4 keywords crammed with no natural language between them)

━━━ BULLET RULES (variant_a — enforce ALL) ━━━
  • Exactly 5 bullets
  • Each ≤500 bytes
  • LEAD WITH BENEFIT, follow with the spec that backs it up — NEVER open with a feature label:
      PASS: "Stays cool during back-to-back meetings — breathable mesh keeps air circulating"
      FAIL: "Mesh Material: Provides breathability for users"
      PASS: "Handles the bass at high volume without distorting — 40mm driver, 20Hz–20kHz range"
      FAIL: "Driver Size: 40mm driver for quality audio"
  • Primary or secondary keyword within first 10 words of each bullet
  • No stacked adjectives without a supporting spec (not: "durable, reliable, long-lasting")
  • No identical opening phrase patterns across bullets
  • BANNED: "best", "#1", "amazing", "unbeatable", exclamation marks

━━━ DESCRIPTION RULES (variant_a) ━━━
  • ≤2000 characters
  • Keyword-dense but written by someone who actually uses the product
  • Use HTML: <b>key feature</b> and <br> only — no other tags
  • No emojis, no exclamation marks

Output ONLY valid JSON. No markdown. No preamble."""

PASS1_USER_TEMPLATE = """Product category: {category}
{lqs_block}{kw_block}Current title: "{title}"
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

PASS2_SYSTEM = """You are a senior ecommerce conversion copywriter with 9 years writing buyer-first product listings. You think like someone about to spend money — not a brand manager writing copy for a catalogue.

Your job: generate a CONVERSION-FIRST variant optimised for Rufus. Rufus reads listings to answer specific shopper questions — not to find keywords. A listing Rufus trusts converts at 60% higher rates than one it ignores.

The human voice rules appended at the end of these instructions apply to EVERY text field you write. They are non-negotiable.

━━━ BULLET STRUCTURE — 5 CANONICAL RUFUS BUYER QUESTIONS ━━━

Assign each of the 5 bullets to exactly one of these questions. Cover all 5.
Adapt the question phrasing to the specific product and category:

  Q1: "Is this right for my specific situation / use case?"
  Q2: "Is it durable / worth the price?"
  Q3: "What goes wrong with products like this?" → pre-empt the known failure mode
  Q4: "How does this compare to the obvious alternative?"
  Q5: "Who else uses this, and does their situation match mine?"

━━━ USE CASE SPECIFICITY — name a concrete situation, never a demographic ━━━

  PASS: "stays in place during HIIT workouts with overhead movements"
  FAIL: "perfect for gym-goers and active users"
  PASS: "low-profile enough to use on a crowded metro commute without elbowing neighbours"
  FAIL: "ideal for daily commuters"
  PASS: "Built for people who walk 10,000+ steps daily — the insole stays firm after 6 months of daily wear"
  FAIL: "Designed for active lifestyle enthusiasts who demand performance"

Every bullet must name a concrete situation, moment, or activity — not a demographic label.

━━━ OBJECTION PRE-EMPTION — cover all 4, grounded in specs ━━━

  Durability   — address longevity or failure mode with a specific number or spec:
                 PASS: "stitching holds through 200+ wash cycles"
                 FAIL: "durable construction for long-lasting use"
  Compatibility — state what it works with AND what it doesn't
  Sizing / Fit  — provide dimension, fit, or range guidance
  Return risk   — pre-empt the single most common reason buyers in this category return

━━━ PERSONAS (personas_addressed output field) ━━━

  Identify ≥2 situational personas — a situation or job-to-be-done, not a demographic:
  PASS: "people who walk 10,000+ steps daily", "remote workers on 4+ hour video calls"
  FAIL: "active lifestyle enthusiasts", "professionals", "students"

━━━ SEMANTIC DEPTH — COSMO-style relationships ━━━

  Include activity/occasion connections in bullets or description:
  e.g. "for the monsoon commute", "before a job interview", "when moving flats"
  For related products: name adjacent concepts — earphone listing should mention
  "call clarity" and "podcast quality", not just "music playback"

━━━ CONVERSATIONAL NATURALNESS ━━━

  • Use ≥2 contractions across bullets/description: "it won't" not "it does not"
  • No exclamation marks anywhere
  • No passive voice bullet openers: avoid "Is designed to…", "Can be used to…", "Was built for…"
  • No banned openers: "Introducing", "Experience", "Transform", "Elevate"
  • No stacked adjectives without a supporting spec

━━━ STRUCTURAL RULES ━━━

  Title   : ≤200 chars. First 80 chars A9-compliant: Brand + product type + primary KW.
            Remaining chars written for the human buyer.
  Bullets : Exactly 5. Each ≤500 bytes. Keyword in first 10 words.
  Desc    : ≤2000 chars. Confident expert tone. HTML: <b>feature</b> and <br> only.

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
    "objections_handled": ["","","",""]
  }}
}}"""


# ─────────────────────────────────────────────
# PASS 3 — SCORING + HYBRID MERGE
# ─────────────────────────────────────────────

PASS3_SYSTEM = """You are a senior listing strategist with 9 years reviewing A/B test results on Amazon India. You know which structural changes actually move CTR and CVR, and you can point to the specific mechanism behind each projection.

The human voice rules appended at the end of these instructions apply to EVERY text field you write. They are non-negotiable.

Given two listing variants (A = discovery-first, B = conversion-first), produce a HYBRID recommendation with full scoring and impact breakdown.

━━━ SCORE DIMENSIONS — use these definitions for all 3 score fields (0–100 each) ━━━

  keyword_density    = A9 Bullet Compliance dimension:
                       keyword coverage across bullets, first-10-word placement, byte compliance
  intent_alignment   = Rufus Intent Coverage dimension:
                       how many of the 5 canonical buyer questions (Q1–Q5) are answered
                       with specific, grounded evidence (not vague coverage)
  conversion_signals = Rufus Objection Pre-emption + Persona Clarity combined:
                       failure modes addressed with specs, situational personas identifiable

━━━ WHAT YOU PRODUCE ━━━

1. REFINED SCORES for both variants on all 3 dimensions above.

2. HYBRID TITLE
   - First 80 chars: A9-compliant (Brand + Type + top 2 keywords from Variant A) — non-negotiable
   - Characters 81–200: written for the buyer in natural language (Variant B phrasing)
   - Total ≤200 characters — HARD LIMIT. Count every character before returning.
     If your draft exceeds 200, trim from the right at the nearest word boundary.
     A title that exceeds 200 chars will be REJECTED — there is no grace margin.

3. HYBRID BULLETS — exactly 5, each ≤500 bytes
   Each bullet must do double duty:
   - Keyword in first 10 words (A9 structure from Variant A)
   - Body answers the implicit buyer question with Variant B's specificity and natural language
   Not a copy of either variant. Choose A's structure, B's grounding.

4. HYBRID DESCRIPTION — ≤2000 characters, HTML formatted
   - Opens with a grounding statement (no "Introducing", no superlatives)
   - Middle: keyword-rich phrases from Variant A not already in title/bullets
   - Close: dominant buyer's specific use case + main objection pre-empted (from Variant B)
   - Use <b>key feature</b> and <br> only — no other HTML tags

5. HYBRID RATIONALE — 2–3 direct sentences for a client briefing.
   Name the SPECIFIC dimensions kept from each variant and why — do not write generic reasoning
   like "balances SEO and conversion". Name what was taken from A, what from B, and the mechanism.
   BAD:  "This hybrid balances keyword optimisation with conversion-focused language."
   GOOD: "Variant A's title puts the primary keyword in position 2 (A9 Mobile Optimisation: +5pts),
          which B's title sacrificed for readability. B's bullet 3 pre-empts the durability objection
          with a wash-cycle count, which A's generic claim lacked — the hybrid keeps A's keyword
          position and B's spec-grounded objection handling."

6. IMPACT BREAKDOWN — per component, grounded in real Amazon behaviour:
   For each of the 3 components (Title, Bullets, Description):
   - component: "Title" | "Bullets" | "Description"
   - what_changed: 1 sentence — the specific structural change in the hybrid vs the original
   - metric: "CTR" | "CVR" | "Indexing"
   - expected_lift: realistic range, e.g. "8–13%" — never a single value
   - reasoning: 1–2 sentences naming the specific mechanism (A9 keyword indexing signal,
     Rufus COSMO relationship, mobile truncation fix, objection pre-emption). Be specific.

Output ONLY valid JSON. No markdown. No preamble."""

PASS3_USER_TEMPLATE = """Variant A (discovery-first):
Title: "{va_title}"
Bullets:
{va_bullets}
Description excerpt: "{va_desc}"
Scores: keyword_density={va_kd}, intent_alignment={va_ia}, conversion_signals={va_cs}

Variant B (conversion-first):
Title: "{vb_title}"
Bullets:
{vb_bullets}
Description excerpt: "{vb_desc}"
Scores: keyword_density={vb_kd}, intent_alignment={vb_ia}, conversion_signals={vb_cs}

Product category: {category}

BEFORE RETURNING — verify: len(hybrid.title) ≤ 200. If over, trim at the nearest word boundary.

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
  "hybrid": {{
    "title": "",
    "bullets": ["", "", "", "", ""],
    "description": ""
  }},
  "hybrid_rationale": "",
  "recommended_variant": "A or B or hybrid",
  "impact": {{
    "ctr_improvement": "X–Y%",
    "cvr_improvement": "X–Y%",
    "breakdown": [
      {{
        "component": "Title",
        "what_changed": "",
        "metric": "CTR",
        "expected_lift": "X–Y%",
        "reasoning": ""
      }},
      {{
        "component": "Bullets",
        "what_changed": "",
        "metric": "CVR",
        "expected_lift": "X–Y%",
        "reasoning": ""
      }},
      {{
        "component": "Description",
        "what_changed": "",
        "metric": "Indexing",
        "expected_lift": "X–Y%",
        "reasoning": ""
      }}
    ]
  }}
}}"""


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _truncate_title(title: str, max_chars: int = 200) -> str:
    """Trim a title to max_chars at the nearest word boundary to the left."""
    if len(title) <= max_chars:
        return title
    cut = title[:max_chars].rsplit(" ", 1)[0]
    return cut if cut else title[:max_chars]


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_ab_optimization(
    title: str,
    bullets: list[str],
    description: str = "",
    category: str = "electronics",
    competitor_context: list[dict] | None = None,
    lqs_context: dict | None = None,
    missing_keywords: list[str] | None = None,
) -> dict:
    category_label = CATEGORY_LABELS.get(category, category)
    bullets_text = "\n".join(
        f"  {i+1}. {b}" for i, b in enumerate(bullets) if b.strip()
    )
    comp_block_kw   = build_competitor_block(competitor_context or [], purpose="keyword")
    comp_block_conv = build_competitor_block(competitor_context or [], purpose="conversion")

    # Build optional context blocks injected into Pass 1
    lqs_block = ""
    if lqs_context and lqs_context.get("a9_score") is not None:
        lqs_block = (
            "ORIGINAL LISTING SCORES (pre-computed by LQS — do NOT re-score, use these exact values):\n"
            f"  a9_compliance: {lqs_context['a9_score']}\n"
        )
        if lqs_context.get("flags"):
            lqs_block += f"  a9_flags: {', '.join(lqs_context['flags'][:5])}\n"

    kw_block = ""
    if missing_keywords:
        kw_block = (
            "KEYWORD GAPS TO TARGET (from keyword gap analysis — prioritise in variant_a title and bullets):\n"
            f"  {', '.join(missing_keywords)}\n"
        )

    # ── PASS 1 ──────────────────────────────
    print("[SellerOS] Pass 1: Generating A9 discovery variant...")

    pass1_result = call(
        task_type=TaskType.STRUCTURED,
        system=PASS1_SYSTEM,
        user=PASS1_USER_TEMPLATE.format(
            category=category_label,
            title=title,
            bullets=bullets_text,
            description=description,
            competitor_block=comp_block_kw,
            lqs_block=lqs_block,
            kw_block=kw_block,
        ),
        max_tokens=2500,
    ).content

    variant_a = pass1_result.get("variant_a", {})
    va_title  = variant_a.get("title", title)
    va_scores = variant_a.get("scores", {})

    # Override LLM-estimated original_scores with real LQS values when available
    if lqs_context and lqs_context.get("a9_score") is not None:
        orig = pass1_result.setdefault("original_scores", {})
        orig["a9_compliance"] = lqs_context["a9_score"]

    # Pass 1 validation
    if len(va_title) > 200:
        raise ValueError(f"Pass 1: variant_a.title exceeds 200 chars ({len(va_title)})")
    if len(va_title) < 80:
        print(f"[SellerOS] WARN Pass 1: variant_a.title is under 80 chars ({len(va_title)})")
    if len(variant_a.get("bullets", [])) != 5:
        print(f"[SellerOS] WARN Pass 1: expected 5 bullets, got {len(variant_a.get('bullets', []))}")

    # ── PASS 2 ──────────────────────────────
    print("[SellerOS] Pass 2: Generating Rufus conversion variant...")

    pass2_result = call(
        task_type=TaskType.CREATIVE,
        system=PASS2_SYSTEM,
        user=PASS2_USER_TEMPLATE.format(
            category=category_label,
            title=title,
            bullets=bullets_text,
            description=description,
            competitor_block=comp_block_conv,
            variant_a_title=va_title,
        ),
        max_tokens=2500,
    ).content

    variant_b = pass2_result.get("variant_b", {})
    vb_title  = variant_b.get("title", title)
    vb_scores = variant_b.get("scores", {})

    # Pass 2 validation
    if len(variant_b.get("bullets", [])) != 5:
        print(f"[SellerOS] WARN Pass 2: expected 5 bullets, got {len(variant_b.get('bullets', []))}")
    if len(variant_b.get("personas_addressed", [])) < 2:
        print("[SellerOS] WARN Pass 2: fewer than 2 personas_addressed")
    if len(variant_b.get("objections_handled", [])) < 3:
        print("[SellerOS] WARN Pass 2: fewer than 3 objections_handled")

    # ── PASS 3 ──────────────────────────────
    print("[SellerOS] Pass 3: Scoring + generating full hybrid recommendation...")

    va_bullets_text = "\n".join(
        f"  {i+1}. {b}" for i, b in enumerate(variant_a.get("bullets", []))
    )
    vb_bullets_text = "\n".join(
        f"  {i+1}. {b}" for i, b in enumerate(variant_b.get("bullets", []))
    )

    pass3_user = PASS3_USER_TEMPLATE.format(
        va_title=va_title,
        va_bullets=va_bullets_text,
        va_desc=(variant_a.get("description", "") or "")[:400],
        va_kd=va_scores.get("keyword_density", 0),
        va_ia=va_scores.get("intent_alignment", 0),
        va_cs=va_scores.get("conversion_signals", 0),
        vb_title=vb_title,
        vb_bullets=vb_bullets_text,
        vb_desc=(variant_b.get("description", "") or "")[:400],
        vb_kd=vb_scores.get("keyword_density", 0),
        vb_ia=vb_scores.get("intent_alignment", 0),
        vb_cs=vb_scores.get("conversion_signals", 0),
        category=category_label,
    )

    pass3_result = call(
        task_type=TaskType.CREATIVE,
        system=PASS3_SYSTEM,
        user=pass3_user,
        max_tokens=3500,
    ).content

    # Pass 3 validation — retry once if title overflows, then truncate
    hybrid_title = pass3_result.get("hybrid", {}).get("title", "")
    if len(hybrid_title) > 200:
        overrun = len(hybrid_title) - 200
        print(
            f"[SellerOS] WARN Pass 3: hybrid.title is {len(hybrid_title)} chars "
            f"({overrun} over limit) — retrying with explicit correction..."
        )
        retry_prefix = (
            f"CORRECTION REQUIRED: your previous hybrid.title was {len(hybrid_title)} characters, "
            f"{overrun} over the 200-char hard limit.\n"
            f"Offending title: \"{hybrid_title}\"\n"
            f"Rewrite hybrid.title to ≤200 chars (trim at the nearest word boundary to the left). "
            f"Return the complete JSON again with the corrected title.\n\n"
        )
        pass3_result = call(
            task_type=TaskType.CREATIVE,
            system=PASS3_SYSTEM,
            user=retry_prefix + pass3_user,
            max_tokens=3500,
        ).content
        hybrid_title = pass3_result.get("hybrid", {}).get("title", "")
        if len(hybrid_title) > 200:
            print(
                f"[SellerOS] WARN Pass 3: retry still {len(hybrid_title)} chars — "
                f"truncating at word boundary"
            )
            hybrid_title = _truncate_title(hybrid_title)
            pass3_result.setdefault("hybrid", {})["title"] = hybrid_title

    rec = pass3_result.get("recommended_variant", "")
    if rec not in ("A", "B", "hybrid"):
        print(f"[SellerOS] WARN Pass 3: unexpected recommended_variant={rec!r}")

    # ── MERGE ────────────────────────────────
    va_final  = pass3_result.get("variant_a_scores", va_scores)
    vb_final  = pass3_result.get("variant_b_scores", vb_scores)
    hybrid    = pass3_result.get("hybrid", {})
    impact    = pass3_result.get("impact", {})

    return {
        "original_scores": pass1_result.get("original_scores", {}),

        "variant_a": {
            **variant_a,
            "scores": va_final,
        },

        "variant_b": {
            **variant_b,
            "scores": vb_final,
        },

        "hybrid": {
            "title":       hybrid.get("title", ""),
            "bullets":     hybrid.get("bullets", []),
            "description": hybrid.get("description", ""),
            "rationale":   pass3_result.get("hybrid_rationale", ""),
            "recommended": pass3_result.get("recommended_variant", "hybrid"),
        },

        "impact": {
            "ctr_improvement": impact.get("ctr_improvement", "—"),
            "cvr_improvement": impact.get("cvr_improvement", "—"),
            "breakdown":       impact.get("breakdown", []),
        },
    }
