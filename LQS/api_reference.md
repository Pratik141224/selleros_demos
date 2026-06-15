# Opsell LQS — API Reference

Base URL (local): `http://localhost:8000`

All `POST` endpoints accept and return `application/json`.  
All responses include `"ok": true` on success and `"detail": "<message>"` on error.  
All responses include `"cached": true | false` indicating whether the result came from the in-memory cache.

---

## Table of contents

- [GET /healthz](#get-healthz)
- [GET /readyz](#get-readyz)
- [POST /analyze](#post-analyze)
- [POST /analyze-listing](#post-analyze-listing)
- [POST /listing-score](#post-listing-score)

---

## GET /healthz

Liveness probe. Returns `200` as long as the process is alive.

**Response**

```json
{ "status": "ok" }
```

---

## GET /readyz

Readiness probe. Returns `200` once the XGBoost model is loaded; `503` if startup failed.

**Response — ready**

```json
{ "status": "ready" }
```

**Response — not ready** `503`

```json
{ "detail": "Model not loaded" }
```

---

## POST /analyze

Runs the full 6-step pipeline (Ingest → Extract → QC → Features → Score → Insights) on a live Amazon product.

Results are **cached for 10 minutes** keyed by `mode + identifier`. Pass `"force": true` to bypass the cache and re-scrape from source.

### Request body

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `mode` | `"asin"` \| `"url"` \| `"query"` | **Yes** | — | How to identify the target product |
| `asin` | string | If `mode=asin` | — | 10-character Amazon ASIN |
| `url` | string | If `mode=url` | — | Full Amazon product page URL |
| `query` | string | If `mode=query` | — | Search phrase (e.g. `"laptop under 50000"`) |
| `force` | boolean | No | `false` | `true` → bypass cache, re-run full pipeline |

**Example**

```json
{
  "mode": "asin",
  "asin": "B0G2MM7VH9",
  "force": false
}
```

**Force rerun**

```json
{
  "mode": "asin",
  "asin": "B0G2MM7VH9",
  "force": true
}
```

### Response body

```json
{
  "ok": true,
  "cached": false,
  "source": "asin",
  "scores": [ ... ],
  "gap_report": { ... },
  "rpi_simulation": { ... },
  "feedback": { ... }
}
```

#### `scores` — array of product objects

One entry per product: `TARGET` (your listing) + up to 5 `COMP-N` competitors.

| Field | Type | Description |
|---|---|---|
| `label` | string | `"TARGET"` or `"COMP-1"` … `"COMP-5"` |
| `title` | string | Product title |
| `asin` | string | Amazon ASIN |
| `price` | number | Current selling price (INR) |
| `discount` | number | Discount % from MRP |
| `rating` | number | Star rating (0–5) |
| `reviews` | number | Total review count |
| `lqs` | number | **Listing Quality Score** — 65–95, XGBoost + heuristic blend |
| `grade` | `"A"` \| `"B"` \| `"C"` | **A** ≥ 88 · **B** ≥ 75 · **C** below 75 |
| `ctr` | number | Estimated click-through rate (0–1) |
| `cvr` | number | Estimated conversion rate (0–1) |
| `rpi` | number | **Revenue Potential Index** = `price × ctr × cvr` |
| `qc_flags` | string[] | Data quality issues — empty array means clean |

**Example entry**

```json
{
  "label":    "TARGET",
  "title":    "boAt Rockerz 450 Bluetooth Headphone",
  "asin":     "B0G2MM7VH9",
  "price":    1299.0,
  "discount": 35.0,
  "rating":   4.1,
  "reviews":  18420,
  "lqs":      78.4,
  "grade":    "B",
  "ctr":      0.612,
  "cvr":      0.481,
  "rpi":      383.18,
  "qc_flags": []
}
```

#### `gap_report`

```json
{
  "target_summary": {
    "title": "...",
    "lqs":   78.4,
    "grade": "B",
    "rpi":   383.18
  },
  "best_competitor": {
    "title": "...",
    "lqs":   88.1,
    "grade": "A",
    "rpi":   521.44
  },
  "gaps": [
    { "metric": "lqs",     "target": 78.4,   "best": 88.1,   "gap": 9.7  },
    { "metric": "ctr",     "target": 0.612,  "best": 0.743,  "gap": 0.13 },
    { "metric": "cvr",     "target": 0.481,  "best": 0.610,  "gap": 0.13 },
    { "metric": "rpi",     "target": 383.18, "best": 521.44, "gap": 138.26 },
    { "metric": "rating",  "target": 4.1,    "best": 4.4,    "gap": 0.3  },
    { "metric": "reviews", "target": 18420,  "best": 32100,  "gap": 13680 }
  ]
}
```

A positive `gap` means the competitor leads on that metric.

#### `rpi_simulation`

Shows what-if RPI projections for your TARGET listing.

```json
[
  { "scenario": "Current",   "rpi": 383.18, "vs_best_pct": -26.5 },
  { "scenario": "CTR +10%",  "rpi": 421.50, "vs_best_pct": -19.2 },
  { "scenario": "CVR +10%",  "rpi": 421.50, "vs_best_pct": -19.2 },
  { "scenario": "Both +10%", "rpi": 463.65, "vs_best_pct": -11.1 },
  { "scenario": "Both +25%", "rpi": 598.72, "vs_best_pct":  +14.8 }
]
```

`vs_best_pct`: % ahead (+) or behind (−) the category leader in that scenario.

#### `feedback`

```json
{
  "health": {
    "status":   "WARNING",
    "critical": ["MISSING_APLUS", "LOW_REVIEW_COUNT"],
    "warnings": ["NO_VIDEO"]
  },
  "strengths":    ["Strong discount (35%)", "High review count"],
  "quick_wins":   ["Add a coupon", "Upload a lifestyle image as the second image"],
  "medium_term":  ["Rewrite bullets with benefit-first language", "Enrol in FBA"],
  "long_term":    ["Commission A+ content", "Launch a review acquisition campaign"],
  "priority_actions": [
    { "action": "Add A+ content", "rpi_lift": 48.2, "effort": "medium" },
    { "action": "Add product video", "rpi_lift": 21.4, "effort": "medium" }
  ],
  "executive_summary": {
    "gap_to_leader":    138.26,
    "top3_combined":    94.7
  }
}
```

### Error responses

| Status | When |
|---|---|
| `400` | Missing required field, invalid ASIN/URL, scrape returned no data |
| `503` | ML model not yet loaded (check `/readyz`) |
| `500` | Unexpected server error |

---

## POST /analyze-listing

Amazon marketplace LQS for a **live ASIN + its category competitors**.

Fetches the target product and its category competitors from Zyte, maps all fields through `field_map.yaml` (no hardcoded field names), scores each with the A9 + Rufus two-pass engine, and returns a full competitor gap report alongside scored results.

- **Pass 1 (A9)** — deterministic, instant, zero LLM calls per product
- **Pass 2 (Rufus)** — LLM-evaluated via Anthropic API (~2–4 s per product)
- **Competitors scored in parallel** via `ThreadPoolExecutor` (max 5 workers)

Results are **cached for 10 minutes** keyed by `ASIN:MARKETPLACE`. Pass `"force": true` to bypass the cache and re-scrape.

**Requires `ANTHROPIC_API_KEY` in the environment.**

### Request body

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `asin` | string | **Yes** | — | 10-character Amazon ASIN |
| `marketplace` | string | No | `"IN"` | Amazon marketplace country code |
| `force` | boolean | No | `false` | `true` → bypass cache, re-scrape Zyte and re-score |

**Example**

```json
{
  "asin": "B0G2MM7VH9",
  "marketplace": "IN",
  "force": false
}
```

### Response body

```json
{
  "ok": true,
  "cached": false,
  "source": "direct (ASIN B0G2MM7VH9)",
  "target_asin": "B0G2MM7VH9",
  "results": [ ... ],
  "gap_report": { ... },
  "score_comparison": [ ... ],
  "dimension_gaps": [ ... ],
  "feedback": { ... }
}
```

#### `results` — array of scored products

One entry per product: `TARGET` (your listing) + up to 5 `COMP-N` competitors.

| Field | Type | Description |
|---|---|---|
| `label` | string | `"TARGET"` or `"COMP-1"` … `"COMP-5"` |
| `asin` | string | Amazon ASIN |
| `title` | string | Product title (truncated to 120 chars) |
| `scores` | object | `{ a9_compliance, rufus_readiness, lqs_score, overall }` |
| `dimension_breakdown` | object | `{ a9: { … }, rufus: { … } }` — per-dimension scores |
| `flags` | string[] | All A9 + Rufus flags ordered by severity |
| `fix_priority` | object[] | Top 5 fixes sorted by `impact_score` descending |
| `projected_ctr_range` | string | e.g. `"2.5–4.0%"` |
| `gmv_impact_inr` | string | e.g. `"₹22,750–₹26,880/month"` |

**Example result entry**

```json
{
  "label": "TARGET",
  "asin":  "B0G2MM7VH9",
  "title": "boAt Rockerz 450 Bluetooth Headphone with 15 Hours Battery",
  "scores": {
    "a9_compliance":   74,
    "rufus_readiness": 68,
    "lqs_score":       61,
    "overall":         69
  },
  "dimension_breakdown": {
    "a9":    { "title_keyword": 22, "title_structure": 13, "mobile_optimisation": 15, "bullet_compliance": 12, "backend_keywords": 3, "browse_node": 10, "attribute_completeness": 0, "content_richness": 0 },
    "rufus": { "intent_coverage": 72, "use_case_specificity": 80, "objection_handling": 65, "persona_clarity": 55, "faq_readiness": 40, "semantic_depth": 60, "review_alignment": 50, "conversational_naturalness": 70 }
  },
  "flags": ["NO_FAQ_COVERAGE", "NO_ATTRIBUTES"],
  "fix_priority": [
    { "issue": "NO_FAQ_COVERAGE", "dimension": "rufus.faq_readiness", "impact_score": 70, "fix_suggestion": "Add Q&A pairs covering use-case, compatibility, and durability questions." }
  ],
  "projected_ctr_range": "1.5–2.8%",
  "gmv_impact_inr": "₹13,875–₹16,374/month"
}
```

#### `gap_report`

Compares your TARGET against the single best competitor (highest overall score).

```json
{
  "target_summary": {
    "title":   "boAt Rockerz 450 ...",
    "asin":    "B0G2MM7VH9",
    "overall": 69,
    "a9":      74,
    "rufus":   68,
    "flags":   ["NO_FAQ_COVERAGE"]
  },
  "best_competitor": {
    "title":   "Sony WH-CH520 ...",
    "asin":    "B0BVMFD3LW",
    "overall": 81,
    "a9":      83,
    "rufus":   77
  },
  "gaps": [
    { "metric": "overall",        "target": 69, "best": 81, "gap": 12 },
    { "metric": "a9_compliance",  "target": 74, "best": 83, "gap": 9  },
    { "metric": "rufus_readiness","target": 68, "best": 77, "gap": 9  },
    { "metric": "lqs_score",      "target": 61, "best": 72, "gap": 11 }
  ]
}
```

A positive `gap` means the competitor leads on that metric.

#### `score_comparison`

Flat table — one row per product (TARGET + competitors). Useful for rendering a comparison grid.

```json
[
  {
    "label":           "TARGET",
    "asin":            "B0G2MM7VH9",
    "title":           "boAt Rockerz 450 ...",
    "overall":         69,
    "a9_compliance":   74,
    "rufus_readiness": 68,
    "lqs_score":       61,
    "projected_ctr":   "1.5–2.8%",
    "gmv_estimate":    "₹13,875–₹16,374/month",
    "critical_flags":  []
  }
]
```

#### `dimension_gaps`

Per-dimension comparison: TARGET score vs. average across all competitors. Sorted by gap (worst first).

```json
[
  { "scorer": "rufus", "dimension": "faq_readiness",    "target_score": 40, "comp_avg": 64.2, "gap": 24.2 },
  { "scorer": "a9",    "dimension": "backend_keywords",  "target_score": 3,  "comp_avg": 7.8,  "gap": 4.8  }
]
```

#### `feedback`

Seller-facing action plan for the TARGET ASIN.

```json
{
  "asin": "B0G2MM7VH9",
  "health": [
    { "level": "WARNING", "msg": "2 high-priority issue(s) need fixing before publish: NO_FAQ_COVERAGE, NO_ATTRIBUTES" }
  ],
  "strengths":    ["Strong A9 mobile_optimisation (15/15)."],
  "quick_wins":   ["Add Q&A pairs covering use-case, compatibility, and durability questions."],
  "medium_term":  ["Rewrite bullets to answer the 5 canonical Rufus buyer questions."],
  "long_term":    ["Build A+ content — adds up to +1 pt on Content Richness and boosts Rufus context."],
  "priority_fixes": [ ... ],
  "executive_summary": {
    "overall_gap_to_leader": 12,
    "a9_gap_to_leader":      9,
    "rufus_gap_to_leader":   9,
    "top_fix":               "Add Q&A pairs covering use-case, compatibility, and durability questions.",
    "critical_flag_count":   0,
    "high_flag_count":       2
  }
}
```

### Error responses

| Status | When |
|---|---|
| `400` | Invalid ASIN format, Zyte returned no data, no category found for ASIN |
| `503` | `ANTHROPIC_API_KEY` not set in environment |
| `500` | Unexpected server error |

---

## POST /listing-score

Amazon marketplace LQS — scores listing **text content** directly with a two-pass engine.

- **Pass 1 (A9)** — deterministic, instant, zero LLM calls
- **Pass 2 (Rufus)** — LLM-evaluated via Anthropic API (~2–4 s)

Results are **cached for 30 minutes** keyed by a SHA-256 hash of the listing content fields. Pass `"force": true` to bypass the cache and re-run the Rufus LLM.

**Requires `ANTHROPIC_API_KEY` in the environment.**

### Request body

#### Core content

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `title` | string | **Yes** | — | Product title (min 2 chars) |
| `description` | string | No | `""` | Product description |
| `bullets` | string[] | No | `[]` | Up to 5 bullet points |
| `backend_keywords` | string | No | `""` | Backend search terms — Amazon indexes these, ≤ 249 bytes |
| `browse_node` | string | No | `""` | Category hierarchy e.g. `"Electronics/Headphones/Over-Ear"` |
| `brand` | string | No | `""` | Brand name — used for brand-first title checks |
| `category` | string | No | `""` | Category hint for browse node consistency check |
| `aplus_content` | string | No | `""` | A+ content body text |
| `images` | object[] | No | `[]` | Image metadata — `[{ "url": "", "alt_text": "", "role": "" }]` |
| `attributes` | object | No | `{}` | Structured product attributes e.g. `{ "colour": "black", "size": "M" }` |
| `qa_pairs` | object[] | No | `[]` | Q&A pairs — `[{ "question": "", "answer": "" }]` |
| `review_summary` | object | No | `{}` | `{ "avg_rating": 4.2, "review_count": 1840, "top_negatives": ["broke quickly", "poor packaging"] }` |

#### Keyword signals

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `primary_keyword` | string | No | auto-extracted | The single most important search term. Auto-extracted from `backend_keywords` → `title` when absent |
| `secondary_keywords` | string[] | No | `[]` | Supporting keywords checked in title, bullets, and backend terms |

#### Integration and control

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `lqs_score_override` | integer | No | `null` | Pass the score from `pipeline.predict_lqs()` to use it in the overall formula. When `null`, the scorer falls back to a content-quality heuristic |
| `force` | boolean | No | `false` | `true` → bypass cache, re-run Rufus LLM |

**Minimal example**

```json
{
  "title": "boAt Rockerz 450 Bluetooth Headphone with 15 Hours Battery, 40mm Drivers",
  "brand": "boAt",
  "primary_keyword": "bluetooth headphone"
}
```

**Full example**

```json
{
  "title": "boAt Rockerz 450 Bluetooth Headphone with 15 Hours Battery, 40mm Drivers",
  "description": "The Rockerz 450 delivers 40mm dynamic drivers with deep bass and crisp highs. Built for all-day wear with plush padded earcups and an adjustable headband.",
  "bullets": [
    "Stays tangle-free on a crowded metro commute — flat cable resists knots after 1,000+ bends",
    "15-hour battery outlasts your longest travel day on a single 2-hour charge",
    "40mm drivers deliver clear highs without the bass distortion common in sub-₹2,000 headphones",
    "Folds flat to fit in a laptop bag side pocket — tested to 500 open/close cycles",
    "Works with iPhone and Android out of the box; does not support aptX HD"
  ],
  "backend_keywords": "wireless headphone neckband earphone over ear music calls",
  "browse_node": "Electronics/Headphones/Over-Ear",
  "brand": "boAt",
  "category": "Electronics",
  "attributes": { "colour": "black", "connectivity": "bluetooth", "driver_size": "40mm" },
  "qa_pairs": [
    { "question": "Can I use this for video calls?", "answer": "Yes, the built-in mic works on Zoom, Teams, and Google Meet." }
  ],
  "review_summary": {
    "avg_rating": 4.1,
    "review_count": 18420,
    "top_negatives": ["ear cups feel tight after 2 hours", "cable feels flimsy"]
  },
  "primary_keyword": "bluetooth headphone",
  "secondary_keywords": ["over ear headphone", "wireless headphone"],
  "lqs_score_override": 78,
  "force": false
}
```

### Response body

```json
{
  "ok": true,
  "cached": false,
  "scores": {
    "a9_compliance":   74,
    "rufus_readiness": 68,
    "lqs_score":       78,
    "overall":         73
  },
  "dimension_breakdown": {
    "a9": { ... },
    "rufus": { ... }
  },
  "flags": [ ... ],
  "fix_priority": [ ... ],
  "projected_ctr_range": "1.5–2.8%",
  "gmv_impact_inr": "₹13,875–₹16,374/month"
}
```

#### `scores`

| Field | Type | Range | Formula |
|---|---|---|---|
| `a9_compliance` | integer | 0–100 | Sum of 8 A9 dimension scores (deterministic) |
| `rufus_readiness` | integer | 0–100 | Weighted sum of 8 Rufus dimensions (LLM) |
| `lqs_score` | integer | 0–100 | `lqs_score_override` if provided, else content heuristic |
| `overall` | integer | 0–100 | `a9×0.40 + rufus×0.35 + lqs×0.25` |

#### `dimension_breakdown.a9`

| Dimension | Max pts | What is measured |
|---|---|---|
| `title_keyword` | 25 | Primary keyword in title, position within first 5 words, first 80 chars; secondary keyword present |
| `title_structure` | 15 | Brand-first, product type, spec attribute, length 80–200 chars, no superlatives/banned openers |
| `mobile_optimisation` | 15 | First 80 chars: brand, keyword, product type, readable — no mid-word truncation |
| `bullet_compliance` | 20 | Exactly 5 bullets, keyword in first 10 words each, all ≤ 500 bytes, benefit-led openers |
| `backend_keywords` | 10 | ≥ 200 bytes used, no front-end duplicates, no internal repeats, no punctuation |
| `browse_node` | 10 | Node present, ≥ 2 hierarchy levels, consistent with `category` |
| `attribute_completeness` | 3 | ≥ 3 structured attributes; variant field (colour/size/pack) present |
| `content_richness` | 2 | Description ≥ 100 chars; A+ content present |

#### `dimension_breakdown.rufus`

Each score is 0–100 (normalised within the dimension).

| Dimension | Weight | What is measured |
|---|---|---|
| `intent_coverage` | 20% | How many of the 5 canonical buyer questions are answered with specific evidence |
| `use_case_specificity` | 15% | Bullets name concrete situations, not demographic labels |
| `objection_handling` | 15% | Durability, compatibility, sizing, return-risk pre-empted with supporting specs |
| `faq_readiness` | 15% | Q&A pairs (or proxy bullets) answer use-case, compatibility, and durability questions |
| `persona_clarity` | 10% | ≥ 1 situational buyer archetype identifiable from content |
| `semantic_depth` | 10% | COSMO-style activity/occasion relationships; related concepts; numeric + text spec variants |
| `conversational_naturalness` | 10% | No banned openers, no stacked adjectives, ≥ 2 contractions, no exclamation marks |
| `review_alignment` | 5% | Listing claims align with positive reviews; top negatives pre-empted (requires `review_summary`) |

#### `flags`

Ordered by severity: CRITICAL → HIGH → MEDIUM → LOW.

| Flag | Severity | Dimension | Meaning |
|---|---|---|---|
| `CRITICAL_KW_MISS` | CRITICAL | a9.title_keyword | Primary keyword absent from title — listing won't index for this query |
| `BROWSE_NODE_MISSING` | CRITICAL | a9.browse_node | No browse node provided — category indexation blocked |
| `BACKEND_OVER_BYTE_LIMIT` | CRITICAL | a9.backend_keywords | Backend terms exceed 249 bytes — Amazon ignores entire field |
| `TITLE_TOO_LONG` | HIGH | a9.title_structure | Title > 200 characters |
| `TOO_FEW_BULLETS` | HIGH | a9.bullet_compliance | Fewer than 3 bullets |
| `MOBILE_KEYWORD_MISSING` | HIGH | a9.mobile_optimisation | Primary keyword not in first 80 chars |
| `ONLY_FEATURE_LISTING` | HIGH | rufus.intent_coverage | All bullets are feature labels — no use-case context |
| `NO_FAQ_COVERAGE` | HIGH | rufus.faq_readiness | No Q&A pairs and no proxy coverage in bullets |
| `TITLE_UNDER_OPTIMISED` | MEDIUM | a9.title_structure | Title < 40 characters |
| `BACKEND_UNDERUTILISED` | MEDIUM | a9.backend_keywords | Backend terms < 80 bytes |
| `KEYWORD_STUFFED_TITLE` | MEDIUM | a9.title_structure | > 4 keywords crammed with no natural language flow |
| `KEYWORD_AFTER_WORD_10` | MEDIUM | a9.title_keyword | Primary keyword at word position > 10 |
| `NO_OBJECTION_HANDLING` | MEDIUM | rufus.objection_handling | No known failure mode or objection addressed |
| `VAGUE_BULLET_N` | MEDIUM | rufus.use_case_specificity | Bullet N has no grounding detail |
| `BROWSE_NODE_TOO_BROAD` | LOW | a9.browse_node | Only top-level category, no sub-category depth |
| `NO_ATTRIBUTES` | LOW | a9.attribute_completeness | No structured product attributes provided |
| `SUPERLATIVE_FOUND:<word>` | LOW | a9.title_structure | Banned superlative detected in title |
| `NO_PERSONA_SIGNAL` | LOW | rufus.persona_clarity | No buyer archetype identifiable from listing |
| `BACKEND_HAS_DUPLICATES` | LOW | a9.backend_keywords | Internal word repetition in backend search terms |
| `BULLET_N_OVER_LIMIT` | LOW | a9.bullet_compliance | Bullet N exceeds 500 bytes |

#### `fix_priority`

Top 5 issues sorted by `impact_score` descending. Merge of A9 deterministic fixes and Rufus LLM fixes.

```json
[
  {
    "issue":          "MOBILE_KEYWORD_MISSING",
    "dimension":      "a9.mobile_optimisation",
    "impact_score":   60,
    "fix_suggestion": "Move the primary keyword to the first 80 characters of the title — 70% of Amazon traffic is mobile and truncates there."
  }
]
```

| Field | Type | Description |
|---|---|---|
| `issue` | string | Flag identifier |
| `dimension` | string | `"a9.<dim>"` or `"rufus.<dim>"` |
| `impact_score` | integer | 0–100 — priority rank; higher = fix first |
| `fix_suggestion` | string | One actionable sentence |

#### `projected_ctr_range` and `gmv_impact_inr`

Score-band estimates using default assumptions: 500 daily visits · ₹1,850 AOV · 2.5% baseline CTR · 2.0% baseline CVR.

| Overall score | `projected_ctr_range` | `gmv_impact_inr` (baseline–projected) |
|---|---|---|
| 85–100 | `3.5–5.5%` | higher uplift range |
| 70–84 | `2.5–4.0%` | moderate uplift range |
| 55–69 | `1.5–2.8%` | low uplift range |
| 0–54 | `0.8–1.8%` | minimal uplift range |

These are projections, not guarantees.

### Error responses

| Status | When |
|---|---|
| `400` | `title` missing or too short; LLM returned invalid output |
| `503` | `ANTHROPIC_API_KEY` not set in environment |
| `500` | Unexpected server error |

---

## Caching behaviour

| Endpoint | TTL | Cache key |
|---|---|---|
| `POST /analyze` | 10 minutes | `mode:identifier` (e.g. `asin:B0G2MM7VH9`) |
| `POST /analyze-listing` | 10 minutes | `ASIN:MARKETPLACE` (e.g. `B0G2MM7VH9:IN`) |
| `POST /listing-score` | 30 minutes | SHA-256 of `title + bullets + description + keywords + qa_pairs + review_summary` |

- Cache is **in-memory** and resets on server restart.
- Cached responses include `"cached": true`.
- Fresh responses include `"cached": false` and update the cache.
- Pass `"force": true` in any request to bypass the cache read and force a fresh run. The result is still written to cache afterward.
