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

PASS1_SYSTEM = """You are SellerOS, a consumer psychology and e-commerce intelligence engine.

Given a product listing, you will:
1. Identify the 3 most realistic buyer archetypes who purchase this product in India.
2. Score how well the CURRENT listing speaks to each persona (fit_score 0–100).
3. Identify the dominant persona (highest traffic_share_pct).
4. Score the listing on 5 fit dimensions for the dominant persona.

PERSONA FORMAT — each persona needs ALL these fields:
  id: "p1", "p2", or "p3"
  name: short memorable label (e.g. "The Daily Commuter")
  emoji: single emoji representing the archetype
  archetype: one-line job title / life situation
  motivation: primary reason they buy this product category
  life_situation: 1–2 sentences of real life context
  job_to_be_done: the problem they are hiring this product to solve
  buying_trigger: the specific event/moment that makes them buy NOW
  traffic_share_pct: estimated % of purchases (all 3 must sum to exactly 100)
  fit_score: 0–100 — how well the CURRENT listing speaks to this persona
  fit_summary: 1-sentence plain explanation of this fit score

FIT DIMENSIONS for the dominant persona (0–100 each with reasoning):
  language_match: does listing vocabulary match how this persona naturally talks?
  usecase_coverage: are this persona's specific use cases mentioned explicitly?
  objection_handling: are this persona's top purchase hesitations addressed?
  persona_specificity: are there "ideal for [this type of person]" statements?
  intent_signals: does listing contain semantic phrases this persona uses when searching?

IMPORTANT:
- Base personas on real Indian e-commerce buyer behaviour patterns
- Be specific — avoid generic descriptors like "young professional"
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

PASS2_SYSTEM = """You are SellerOS's COSMO intent graph specialist and listing copywriter.

Given the dominant buyer persona from a previous analysis pass, you will:

1. SEMANTIC CLUSTERS — 5 concept associations BEYOND direct keywords that Amazon's
   COSMO intent graph maps to this product via this persona's behaviour patterns.
   Format: product_concept → related_concept

2. CONTEXTUAL TRIGGERS — 3 specific when/where/why buying moments the dominant persona
   experiences. Each needs:
   - situation: 2–4 word label (e.g. "Monsoon commute frustration")
   - embedded_copy: how this trigger would read naturally in listing copy (1–2 sentences)

3. REWRITTEN TITLE — ≤200 chars total
   - First 80 chars: A9-compliant (Brand + Product Type + primary keyword)
   - Remaining chars: written for the persona's natural language, not the algorithm

4. REWRITTEN BULLETS — exactly 5 bullets, each ≤500 bytes
   - Keyword in first 10 words (A9 compliance)
   - Body written in the persona's natural vocabulary and life context
   - Each bullet answers ONE implicit question this persona has

5. REWRITE RATIONALE — 2–3 sentences explaining what changed and why it works better

6. FAQ PAIRS — exactly 5 question-answer pairs for Rufus A+ Content
   - Q: phrased exactly as this persona would type it to Amazon's Rufus assistant
   - A: ≤3 sentences, specific, no superlatives, citable by Rufus

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
