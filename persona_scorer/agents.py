"""
demo2_persona_scorer/agents.py

Two-pass Claude pipeline for Buyer Persona & Intent Match Scorer.

Pass 1 — Persona Discovery + Listing Fit Scoring
Pass 2 — COSMO Semantic Clustering + Persona-Targeted Rewrite

Each pass is a separate Claude API call so prompts stay focused
and output quality stays high.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.llm_router import call, TaskType

# ─────────────────────────────────────────────
# CATEGORY LABELS
# ─────────────────────────────────────────────
CATEGORY_LABELS = {
    "electronics_audio": "Electronics / Wireless Earbuds & Headphones",
    "fashion_men":       "Fashion / Men's Casual T-shirts",
    "kitchen_cookware":  "Kitchen & Home / Non-stick Cookware & Pans",
    "fitness_yoga":      "Sports & Fitness / Yoga Mats & Equipment",
    "skincare":          "Beauty & Personal Care / Face Moisturisers & Serums",
    "custom":            "General consumer product",
}

PLATFORM_LABELS = {
    "amazon":   "Amazon India",
    "flipkart": "Flipkart India",
    "myntra":   "Myntra",
    "meesho":   "Meesho",
}


# ─────────────────────────────────────────────
# PASS 1 — PERSONA DISCOVERY + FIT SCORING
# ─────────────────────────────────────────────

PASS1_SYSTEM = """You are a senior category manager and consumer insights specialist with 9 years studying real buyer behaviour on Amazon India and Flipkart. You've read thousands of customer reviews, return reasons, Q&A threads, and support tickets — you know how real Indian consumers think, search, and decide.

Given a product listing, identify the 3 most realistic buyer archetypes for this product in India. Ground each persona in observable, specific behaviour — not demographic labels. Avoid generic archetypes like "young urban professional" or "health-conscious consumer." Be concrete: name the actual life situation, the real frustration, and the specific moment that triggers the purchase.

PERSONA FORMAT — all fields required, all must be specific and grounded:
  id: "p1", "p2", or "p3"
  name: a memorable, specific label (e.g. "The Metro Commuter" not "The Urban Professional")
  emoji: single emoji representing this archetype
  archetype: one-line job title or life situation, specific (e.g. "28-year-old software engineer, daily Bangalore Metro commuter")
  motivation: the real underlying driver — not "wants quality" but "tired of earbuds dying mid-commute on the 45-minute ride home"
  life_situation: 1–2 sentences of specific, grounded context for this person's daily life
  job_to_be_done: the exact problem they are hiring this product to solve
  buying_trigger: the specific event, frustration, or moment that makes them search for this today
  traffic_share_pct: estimated % of purchases (all 3 MUST sum to exactly 100)
  fit_score: 0–100 — how well the CURRENT listing speaks to this persona
  fit_summary: 1 sentence — be direct about why the listing works or fails for this person

FIT DIMENSIONS for the dominant persona (0–100 each, with honest, direct reasoning):
  language_match: does the listing use words this person actually uses — or does it sound like a brand manager?
  usecase_coverage: does the listing address this person's specific situation — or just generic use cases?
  objection_handling: does the listing address this persona's real hesitations — or ignore them?
  persona_specificity: does the listing speak to someone who looks like this person — or is it written for everyone/no one?
  intent_signals: does the listing contain phrases this persona would actually type into the Amazon search bar?

IMPORTANT:
- Be specific and honest — a fit_score of 40 must say clearly why the listing is failing this persona
- Avoid comfortable vagueness; if the listing is generic, say so plainly
- traffic_share_pct values MUST sum to exactly 100
- All scores are 0–100 integers
- Output ONLY valid JSON. No markdown. No preamble. No text outside the JSON object."""

PASS1_USER_TEMPLATE = """Product category: {category}
Platform: {platform}
Current product title: "{title}"
Current description/bullets:
{description}
{price_line}

Return exactly this JSON structure:
{{
  "personas": [
    {{
      "id": "p1",
      "name": "",
      "emoji": "",
      "archetype": "",
      "motivation": "",
      "life_situation": "",
      "job_to_be_done": "",
      "buying_trigger": "",
      "traffic_share_pct": 0,
      "fit_score": 0,
      "fit_summary": ""
    }},
    {{
      "id": "p2",
      "name": "",
      "emoji": "",
      "archetype": "",
      "motivation": "",
      "life_situation": "",
      "job_to_be_done": "",
      "buying_trigger": "",
      "traffic_share_pct": 0,
      "fit_score": 0,
      "fit_summary": ""
    }},
    {{
      "id": "p3",
      "name": "",
      "emoji": "",
      "archetype": "",
      "motivation": "",
      "life_situation": "",
      "job_to_be_done": "",
      "buying_trigger": "",
      "traffic_share_pct": 0,
      "fit_score": 0,
      "fit_summary": ""
    }}
  ],
  "dominant_persona_id": "p1",
  "dominant_persona_insight": "2-sentence hook about the core mismatch this analysis reveals",
  "fit_dimensions": {{
    "language_match":      {{ "score": 0, "reasoning": "" }},
    "usecase_coverage":    {{ "score": 0, "reasoning": "" }},
    "objection_handling":  {{ "score": 0, "reasoning": "" }},
    "persona_specificity": {{ "score": 0, "reasoning": "" }},
    "intent_signals":      {{ "score": 0, "reasoning": "" }}
  }},
  "overall_fit_score": 0
}}"""


# ─────────────────────────────────────────────
# PASS 2 — COSMO CLUSTERING + REWRITE
# ─────────────────────────────────────────────

PASS2_SYSTEM = """You are a senior ecommerce content manager with 9 years writing product listings on Amazon India. You think like the specific buyer persona identified in the previous pass — and you write copy that would make that exact person stop scrolling and read.

BANNED PHRASES AND PATTERNS — never use these:
  - "Introducing the..." / "Experience the..." / "Transform your..." / "Elevate your..."
  - "Premium quality" / "High-quality" / "Best-in-class" / "Superior" / "World-class"
  - "Designed for those who value..." / "For the discerning buyer..."
  - "Whether you're a student or a professional..." (generic)
  - Stacked adjectives with no supporting spec: "durable, comfortable, reliable"
  - Vague benefit claims with no grounding detail
  - Exclamation marks

Write like a knowledgeable friend who owns this product and is texting the dominant persona directly:
  BAD:  "Experience premium sound quality with our advanced noise-cancellation technology"
  GOOD: "Blocks auto-rickshaw engine noise on the commute — tested at 27dB passive isolation without ANC on"

  BAD:  "Perfect for fitness enthusiasts and yoga practitioners looking for the best mat"
  GOOD: "6mm thick — enough cushion for your knees in long hold poses, thin enough to roll tight and fit in a gym bag"

Be specific. If the product has a real differentiator, name it plainly. Write contractions.

Given the dominant buyer persona, you will produce:

1. SEMANTIC CLUSTERS — 5 concept associations BEYOND direct keywords that Amazon's COSMO intent graph maps to this product through this persona's behaviour. Be specific about why the association exists.
   Format: product_concept → related_concept (with a grounded reason, e.g. "commuter headphones → Mumbai local train noise" not just "travel")

2. CONTEXTUAL TRIGGERS — 3 specific, real buying moments this persona experiences:
   - situation: 2–4 word label, grounded and specific (e.g. "Earphones died mid-commute")
   - embedded_copy: 1–2 natural sentences that could appear directly in the listing

3. REWRITTEN TITLE — ≤200 chars total
   - First 80 chars: A9-compliant (Brand + Product Type + primary keyword)
   - Remaining chars: written in the persona's natural language, not for the algorithm

4. REWRITTEN BULLETS — exactly 5, each ≤500 bytes
   - Keyword in first 10 words (A9 compliance)
   - Body written in the persona's vocabulary, answering one implicit question per bullet

5. REWRITE RATIONALE — 2–3 sentences, direct and specific — what changed and why it works better for this persona

6. FAQ PAIRS — exactly 5 pairs for Rufus A+ Content
   - Q: phrased exactly as this persona would type it to Amazon Rufus (conversational, not formal)
   - A: ≤3 sentences, direct, specific, no superlatives, no hedging

7. IMPACT PROJECTIONS:
   - projected_cvr_improvement: realistic range (e.g. "11–17%")
   - projected_ctr_improvement: realistic range (e.g. "7–12%")

Output ONLY valid JSON. No markdown. No preamble."""

PASS2_USER_TEMPLATE = """Dominant persona:
{dominant_persona_json}

Current product title: "{title}"
Current description: "{description}"
Category: {category}

Fit gaps to address (lowest scoring dimensions from Pass 1):
{fit_gaps}

Return exactly this JSON structure:
{{
  "semantic_clusters": [
    {{ "product_concept": "", "related_concept": "", "relevance": "high" }},
    {{ "product_concept": "", "related_concept": "", "relevance": "high" }},
    {{ "product_concept": "", "related_concept": "", "relevance": "medium" }},
    {{ "product_concept": "", "related_concept": "", "relevance": "medium" }},
    {{ "product_concept": "", "related_concept": "", "relevance": "medium" }}
  ],
  "contextual_triggers": [
    {{ "situation": "", "embedded_copy": "" }},
    {{ "situation": "", "embedded_copy": "" }},
    {{ "situation": "", "embedded_copy": "" }}
  ],
  "rewritten_title": "",
  "rewritten_bullets": ["", "", "", "", ""],
  "rewrite_rationale": "",
  "faq_pairs": [
    {{ "question": "", "answer": "" }},
    {{ "question": "", "answer": "" }},
    {{ "question": "", "answer": "" }},
    {{ "question": "", "answer": "" }},
    {{ "question": "", "answer": "" }}
  ],
  "projected_cvr_improvement": "X–Y%",
  "projected_ctr_improvement": "X–Y%"
}}"""


# ─────────────────────────────────────────────
# MAIN PIPELINE FUNCTION
# ─────────────────────────────────────────────

def run_persona_analysis(
    title: str,
    description: str,
    category: str = "electronics_audio",
    platform: str = "amazon",
    price: str = "",
) -> dict:
    """
    Run the full 2-pass persona analysis pipeline.
    Returns a combined result dict with all data needed by the frontend.
    """

    category_label = CATEGORY_LABELS.get(category, category)
    platform_label = PLATFORM_LABELS.get(platform, platform)
    price_line = f"Price point: {price}" if price else ""

    # ── PASS 1 ──────────────────────────────
    print("[SellerOS] Pass 1: Identifying buyer personas + scoring listing fit...")

    pass1_user = PASS1_USER_TEMPLATE.format(
        category=category_label,
        platform=platform_label,
        title=title,
        description=description,
        price_line=price_line,
    )

    pass1_result = call(task_type=TaskType.CREATIVE, system=PASS1_SYSTEM, user=pass1_user, max_tokens=3000).content

    # ── PASS 2 ──────────────────────────────
    print("[SellerOS] Pass 2: COSMO clustering + persona-targeted rewrite...")

    # Extract dominant persona for pass 2
    dominant_id = pass1_result.get("dominant_persona_id", "p1")
    personas = pass1_result.get("personas", [])
    dominant_persona = next(
        (p for p in personas if p.get("id") == dominant_id),
        personas[0] if personas else {}
    )

    # Extract lowest-scoring fit dimensions to give pass 2 context on what to fix
    fit_dims = pass1_result.get("fit_dimensions", {})
    sorted_dims = sorted(
        fit_dims.items(),
        key=lambda x: x[1].get("score", 100)
    )
    fit_gaps = "\n".join(
        f"- {dim}: {data.get('score', 0)}/100 — {data.get('reasoning', '')}"
        for dim, data in sorted_dims[:3]  # worst 3 dimensions
    )

    import json as _json
    pass2_user = PASS2_USER_TEMPLATE.format(
        dominant_persona_json=_json.dumps(dominant_persona, indent=2),
        title=title,
        description=description,
        category=category_label,
        fit_gaps=fit_gaps,
    )

    pass2_result = call(task_type=TaskType.CREATIVE, system=PASS2_SYSTEM, user=pass2_user, max_tokens=3000).content

    # ── MERGE RESULTS ──────────────────────
    return {
        # Pass 1 output
        "personas":               pass1_result.get("personas", []),
        "dominant_persona_id":    pass1_result.get("dominant_persona_id", "p1"),
        "dominant_persona_insight": pass1_result.get("dominant_persona_insight", ""),
        "fit_dimensions":         pass1_result.get("fit_dimensions", {}),
        "overall_fit_score":      pass1_result.get("overall_fit_score", 0),

        # Pass 2 output
        "semantic_clusters":      pass2_result.get("semantic_clusters", []),
        "contextual_triggers":    pass2_result.get("contextual_triggers", []),
        "rewritten_title":        pass2_result.get("rewritten_title", ""),
        "rewritten_bullets":      pass2_result.get("rewritten_bullets", []),
        "rewrite_rationale":      pass2_result.get("rewrite_rationale", ""),
        "faq_pairs":              pass2_result.get("faq_pairs", []),

        # Impact
        "projected_cvr_improvement": pass2_result.get("projected_cvr_improvement", "—"),
        "projected_ctr_improvement": pass2_result.get("projected_ctr_improvement", "—"),
    }
