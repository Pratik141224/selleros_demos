# Opsell — Listing Quality Scorer (LQS)

A FastAPI service that scores Amazon product listings, benchmarks them against category competitors, and generates actionable seller recommendations — all from a single ASIN, URL, or search query.

The service runs two independent scoring systems that complement each other:

| System | What it measures | LLM? |
|---|---|---|
| **Pipeline LQS** (`/analyze`) | Market performance — ratings, reviews, BSR, price, images | No |
| **Amazon Marketplace LQS — text** (`/listing-score`) | Content quality — A9 + Rufus, from listing text you provide | Yes (Rufus pass) |
| **Amazon Marketplace LQS — ASIN** (`/analyze-listing`) | Same as above, but fetches the listing + competitors live from Zyte | Yes (Rufus pass) |

---

## How the Pipeline LQS works (`/analyze`)

Every request runs a 6-step pipeline:

```
ASIN / URL / Query
      │
      ▼
[1] INGESTION      → Fetches target product-details + top-N competitors from same leaf category
      │
      ▼
[2] EXTRACTION     → Normalizes raw API fields into a consistent internal schema
      │
      ▼
[3] QC             → Flags data issues (missing title, invalid price, bad ASIN, etc.)
      │
      ▼
[4] FEATURES       → Builds the 23-feature vector the model expects
      │
      ▼
[5] SCORING        → XGBoost model + heuristic blend → LQS, Grade, CTR, CVR, RPI
      │
      ▼
[6] INSIGHTS       → Gap report, RPI simulation scenarios, seller feedback & action plan
```

---

## How the Amazon Marketplace LQS works (`/listing-score`)

A two-pass content scorer that evaluates the text of a listing directly — no ASIN lookup needed.

```
Listing text (title, bullets, description, …)
      │
      ▼
[Pass 1] A9 COMPLIANCE SCORER   ← deterministic, instant, no LLM
      │   8 dimensions, 100 pts total:
      │     Title Keyword Placement   25 pts
      │     Title Structure           15 pts
      │     Mobile Optimisation       15 pts
      │     Bullet Compliance         20 pts
      │     Backend Keywords          10 pts
      │     Browse Node + Category    10 pts
      │     Attribute Completeness     3 pts
      │     Content Richness           2 pts
      │
      ▼
[Pass 2] RUFUS READINESS SCORER  ← LLM evaluated (Claude)
      │   8 dimensions, weighted to 100:
      │     Intent Coverage           20%
      │     Use Case Specificity      15%
      │     Objection Handling        15%
      │     FAQ Readiness             15%
      │     Persona Clarity           10%
      │     Semantic Depth            10%
      │     Conversational Naturalness 10%
      │     Review Alignment           5%
      │
      ▼
[Output]
      overall = a9 × 0.40 + rufus × 0.35 + lqs × 0.25
      + flags, fix_priority, projected CTR range, GMV impact (INR)
```

`lqs` in the overall formula is either:
- The score from `pipeline.predict_lqs()` if you pass `lqs_score_override` in the request, or
- A content-quality heuristic (title length, bullet count, description, A+, images, attributes) when used standalone.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11 or 3.14 |
| Homebrew (macOS) | any |
| Zyte scraping service | EC2 endpoint (`ZYTE_BASE_URL`) |
| Anthropic API key | Required for `/listing-score` (Rufus pass) |

---

## Setup

### 1. Clone and enter the project

```bash
git clone <your-repo-url>
cd Listing_Quality_Scorer
```

### 2. Create and activate a virtual environment

```bash
python -m venv lqs
source lqs/bin/activate        # macOS / Linux
# lqs\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install OpenMP (macOS only — required by XGBoost)

```bash
brew install libomp
```

> Skip this step on Linux or Windows. Without it, the model will fail to load on macOS.

### 5. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
ZYTE_BASE_URL=http://<your-ec2-ip>:4001
OPSELL_COUNTRY_CODE=IN
ALLOW_ORIGINS=*
MODEL_PATH=DataStore/models/lqs_model.pkl
ANTHROPIC_API_KEY=sk-ant-...          # required for /listing-score
```

`ANTHROPIC_API_KEY` is only needed by the `/listing-score` endpoint (Rufus pass). All other endpoints work without it.

---

## Running locally

```bash
uvicorn api:app --reload --port 8000
```

You should see:

```
INFO  | Model loaded — API ready
INFO  | Application startup complete.
INFO  | Uvicorn running on http://127.0.0.1:8000
```

### Dashboard UI

```
http://localhost:8000/
```

### API docs (auto-generated)

```
http://localhost:8000/docs
```

---

## API reference

### `GET /healthz`
Liveness probe — confirms the process is running.

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

### `GET /readyz`
Readiness probe — confirms the ML model is loaded.

```bash
curl http://localhost:8000/readyz
# {"status":"ready"}
```

### `POST /analyze`
Runs the full 6-step pipeline on a live ASIN/URL/query. Returns market-performance scores, gap analysis, RPI scenarios, and seller feedback.

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `mode` | `"asin"` \| `"url"` \| `"query"` | Yes | How to identify the target product |
| `asin` | string | If `mode=asin` | 10-character Amazon ASIN |
| `url` | string | If `mode=url` | Amazon product page URL |
| `query` | string | If `mode=query` | Search phrase |

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"mode":"asin","asin":"B0G2MM7VH9"}'
```

---

### `POST /analyze-listing`
Amazon marketplace LQS from a **live ASIN**. Fetches the target listing and its category competitors from Zyte, maps fields via `field_map.yaml`, scores with A9 + Rufus, and returns a full competitor gap report.

**Requires `ANTHROPIC_API_KEY` in environment.**

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `asin` | string | **Yes** | 10-character Amazon ASIN |
| `marketplace` | string | No | Country code — default `"IN"` |
| `force` | bool | No | `true` bypasses cache and re-scrapes |

```bash
curl -X POST http://localhost:8000/analyze-listing \
  -H "Content-Type: application/json" \
  -d '{"asin":"B0G2MM7VH9","marketplace":"IN"}'
```

---

### `POST /listing-score`
Amazon marketplace LQS — scores listing **text content** directly, no ASIN needed. Runs the two-pass A9 + Rufus pipeline.

**Requires `ANTHROPIC_API_KEY` in environment.**

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `title` | string | **Yes** | Product title |
| `bullets` | `string[]` | No | Up to 5 bullet points |
| `description` | string | No | Product description |
| `backend_keywords` | string | No | Search terms (≤249 bytes) |
| `browse_node` | string | No | Category path e.g. `"Electronics/Headphones/In-Ear"` |
| `brand` | string | No | Brand name — used for brand-first title checks |
| `category` | string | No | Category hint for browse node matching |
| `aplus_content` | string | No | A+ content body text |
| `images` | `object[]` | No | `[{url, alt_text, role}]` |
| `attributes` | object | No | Structured product attributes |
| `qa_pairs` | `object[]` | No | `[{question, answer}]` |
| `review_summary` | object | No | `{avg_rating, review_count, top_negatives}` |
| `primary_keyword` | string | No | Auto-extracted from `backend_keywords`/title if absent |
| `secondary_keywords` | `string[]` | No | Additional keywords to check |
| `lqs_score_override` | integer | No | Pass the score from `pipeline.predict_lqs()` to use it in the overall calculation |

**Example:**

```bash
curl -X POST http://localhost:8000/listing-score \
  -H "Content-Type: application/json" \
  -d '{
    "title": "boAt Rockerz 450 Bluetooth Headphone with 15 Hours Battery, 40mm Drivers",
    "bullets": [
      "Stays tangle-free on a crowded metro commute — flat cable resists knots after 1,000+ bends",
      "15-hour battery outlasts your longest travel day on a single 2-hour charge",
      "40mm drivers deliver clear highs without the bass distortion common in sub-₹2,000 headphones",
      "Folds flat to fit in a laptop bag side pocket — tested to 500 open/close cycles",
      "Works with iPhone and Android out of the box; does not support aptX HD"
    ],
    "brand": "boAt",
    "browse_node": "Electronics/Headphones/Over-Ear",
    "backend_keywords": "wireless headphone neckband earphone over ear music calls",
    "primary_keyword": "bluetooth headphone"
  }'
```

**Response:**

```json
{
  "ok": true,
  "scores": {
    "a9_compliance":   74,
    "rufus_readiness": 68,
    "lqs_score":       61,
    "overall":         69
  },
  "dimension_breakdown": {
    "a9": {
      "title_keyword": 22,
      "title_structure": 13,
      "mobile_optimisation": 15,
      "bullet_compliance": 12,
      "backend_keywords": 3,
      "browse_node": 10,
      "attribute_completeness": 0,
      "content_richness": 0
    },
    "rufus": {
      "intent_coverage": 72,
      "use_case_specificity": 80,
      "objection_handling": 65,
      "persona_clarity": 55,
      "faq_readiness": 40,
      "semantic_depth": 60,
      "review_alignment": 50,
      "conversational_naturalness": 70
    }
  },
  "flags": ["BROWSE_NODE_TOO_BROAD", "NO_ATTRIBUTES", "NO_FAQ_COVERAGE"],
  "fix_priority": [
    {
      "issue": "NO_ATTRIBUTES",
      "dimension": "a9.attribute_completeness",
      "impact_score": 20,
      "fix_suggestion": "Populate structured product attributes (colour, size, model) to improve variation indexation."
    }
  ],
  "projected_ctr_range": "1.5–2.8%",
  "gmv_impact_inr": "₹13,875–₹16,374/month"
}
```

---

## Understanding the results

### Pipeline LQS (`/analyze`)

#### `scores` — per-product metrics table

| Field | What it means |
|---|---|
| `label` | `TARGET` for your product, `COMP-1` … `COMP-5` for competitors |
| `lqs` | **Listing Quality Score** (65–95). Blends the XGBoost model (40%) with a heuristic (60%) |
| `grade` | **A** ≥ 88, **B** ≥ 75, **C** below 75 |
| `ctr` | Estimated click-through rate (0–1) |
| `cvr` | Estimated conversion rate (0–1) |
| `rpi` | **Revenue Potential Index** = `price × ctr × cvr` |
| `discount` | Discount percentage from MRP |
| `qc_flags` | Data issues detected — empty list means clean |

#### `gap_report`, `rpi_simulation`, `feedback`

See the [Understanding the results](#understanding-the-results) section below for full details on these fields — they are unchanged from the previous version.

### Amazon Marketplace LQS (`/listing-score`)

#### Flags severity

| Severity | Examples | Action |
|---|---|---|
| **CRITICAL** — block publish | `CRITICAL_KW_MISS`, `BROWSE_NODE_MISSING`, `BACKEND_OVER_BYTE_LIMIT` | Fix before going live |
| **HIGH** — fix before publish | `TITLE_TOO_LONG`, `TOO_FEW_BULLETS`, `MOBILE_KEYWORD_MISSING` | Fix this sprint |
| **MEDIUM** — scoring improvement | `TITLE_UNDER_OPTIMISED`, `NO_OBJECTION_HANDLING`, `VAGUE_BULLET_N` | Fix this month |
| **LOW** — quality polish | `BROWSE_NODE_TOO_BROAD`, `SUPERLATIVE_FOUND`, `NO_PERSONA_SIGNAL` | Nice to have |

#### `projected_ctr_range` and `gmv_impact_inr`

Estimates based on overall score band, using default assumptions: 500 daily visits, ₹1,850 AOV, 2.5% baseline CTR, 2.0% baseline CVR. Label these as projections — not guarantees.

---

## Project structure

```
Listing_Quality_Scorer/
│
├── api.py                   # FastAPI app — all endpoints
├── main.py                  # CLI runner (6-step pipeline, no server)
├── config.py                # All configuration, reads from environment
│
├── lqs_pipeline/            # Python-based LQS pipeline (XGBoost + heuristics)
│   ├── Ingestion.py         # Step 1 — fetches product-details + competitors via Zyte
│   ├── Extraction.py        # Step 2 — normalises raw API fields
│   ├── QC.py                # Step 3 — data quality validation
│   ├── features.py          # Step 4 — builds 23-feature vector
│   ├── pipeline.py          # Step 5 — XGBoost scoring + CTR/CVR/RPI
│   ├── insights.py          # Step 6 — gap report, simulation, feedback
│   └── zyte_client.py       # Zyte EC2 scraping client
│
├── marketplaces/            # Marketplace-specific LQS scorers
│   ├── base_lqs.py          # ListingInput, LQSOutput, BaseLQSScorer (ABC)
│   └── amazon/
│       ├── a9_scorer.py     # Pass 1 — deterministic A9 (8 dimensions)
│       ├── rufus_scorer.py  # Pass 2 — LLM Rufus readiness (8 dimensions)
│       ├── lqs.py           # AmazonLQSScorer — orchestrates both passes
│       ├── asin_pipeline.py # ASIN-driven pipeline (Zyte → score → insights)
│       ├── zyte_mapper.py   # Config-driven Zyte → ListingInput mapper
│       ├── lqs_insights.py  # Gap report, dimension gaps, seller feedback
│       └── field_map.yaml   # External field mapping config (edit, not code)
│
├── shared/
│   ├── llm_client.py        # Thin Anthropic SDK wrapper (call_json)
│   └── prompts/
│       └── d1_rufus_lqs_v1.txt  # Rufus scoring rubric injected at runtime
│
├── DataStore/
│   └── models/
│       └── lqs_model.pkl    # Trained XGBoost model
│
├── lqs/                     # Python virtual environment
├── dashboard.html           # Single-file browser UI (served at GET /)
├── requirements.txt
└── README.md
```

---

## Adding a new marketplace scorer

The `marketplaces/` package is designed to accept new scorers with minimal friction. Each marketplace is a self-contained sub-package that implements the `BaseLQSScorer` interface.

### Step 1 — Create the sub-package

```bash
mkdir marketplaces/flipkart
touch marketplaces/flipkart/__init__.py
```

### Step 2 — Create your deterministic scorer (Pass 1)

Create `marketplaces/flipkart/fsn_scorer.py`. Model it after `marketplaces/amazon/a9_scorer.py`.

Each dimension is an isolated function that returns `(score: int, flags: list[str])`. Add, remove, or reweight dimensions freely — the interface only cares about the final score.

```python
# marketplaces/flipkart/fsn_scorer.py

from dataclasses import dataclass, field

@dataclass
class FSNResult:
    score: int
    breakdown: dict[str, int]
    flags: list[str] = field(default_factory=list)

def score_fsn(title, bullets, description="", ...) -> FSNResult:
    # Flipkart-specific dimension checks
    # e.g. title ≤ 100 chars, FSN category compliance, LQI score dimensions
    ...
```

### Step 3 — Create your LLM scorer (Pass 2)

Create `marketplaces/flipkart/discovery_scorer.py`. Model it after `marketplaces/amazon/rufus_scorer.py`.

Write a new prompt file at `shared/prompts/<marketplace>_lqs_v1.txt` describing the platform's discovery algorithm dimensions. The `shared/llm_client.call_json()` wrapper handles the Anthropic API call.

```python
# marketplaces/flipkart/discovery_scorer.py

from shared.llm_client import call_json

_PROMPT_PATH = Path(__file__).parent.parent.parent / "shared" / "prompts" / "flipkart_lqs_v1.txt"

def score_discovery(title, bullets, ...) -> DiscoveryResult:
    system = _PROMPT_PATH.read_text()
    user   = _build_user_message(title, bullets, ...)
    raw    = call_json(system=system, user=user)
    return _parse_response(raw)
```

### Step 4 — Implement `BaseLQSScorer`

Create `marketplaces/flipkart/lqs.py`:

```python
# marketplaces/flipkart/lqs.py

from marketplaces.base_lqs import BaseLQSScorer, ListingInput, LQSOutput
from marketplaces.flipkart.fsn_scorer import score_fsn
from marketplaces.flipkart.discovery_scorer import score_discovery

class FlipkartLQSScorer(BaseLQSScorer):
    platform = "flipkart"

    def score(self, listing: ListingInput) -> LQSOutput:
        listing.validate()

        fsn       = score_fsn(listing.title, listing.bullets, ...)
        discovery = score_discovery(listing.title, listing.bullets, ...)
        lqs_score = listing.lqs_score_override or _content_lqs(listing)

        overall = int(fsn.score * 0.45 + discovery.score * 0.30 + lqs_score * 0.25)

        return LQSOutput(
            scores={
                "fsn_compliance":      fsn.score,
                "discovery_readiness": discovery.score,
                "lqs_score":           lqs_score,
                "overall":             overall,
            },
            dimension_breakdown={"fsn": fsn.breakdown, "discovery": discovery.breakdown},
            flags=fsn.flags + discovery.flags,
            fix_priority=[...],
            projected_ctr_range="...",
            gmv_impact_inr="...",
        )
```

### Step 5 — Export and wire up

Update `marketplaces/flipkart/__init__.py`:

```python
from .lqs import FlipkartLQSScorer
__all__ = ["FlipkartLQSScorer"]
```

Add an endpoint to `api.py`:

```python
from marketplaces.flipkart import FlipkartLQSScorer

_flipkart_scorer = FlipkartLQSScorer()

@app.post("/listing-score/flipkart", tags=["scoring"])
def flipkart_listing_score(req: ListingScoreRequest):
    listing = ListingInput(**req.model_dump())
    result  = _flipkart_scorer.score(listing)
    return {"ok": True, **result.to_dict()}
```

### What you never need to change

| File | Why it's stable |
|---|---|
| `marketplaces/base_lqs.py` | The contract — `ListingInput` and `LQSOutput` are the shared schema |
| `shared/llm_client.py` | One place to swap the LLM model or add caching |
| `api.py` (existing endpoints) | New marketplaces add endpoints — they don't modify existing ones |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `503 Model not loaded` on `/readyz` | XGBoost failed to load. Run `brew install libomp` (macOS) then restart |
| `Address already in use` on startup | Run `lsof -ti :8000 \| xargs kill -9` then restart |
| `Could not reach the API` in dashboard | Open `http://localhost:8000/` — do **not** open `dashboard.html` directly as a file |
| Competitor list is empty | The leaf category returned no results. Try a different ASIN or query |
| `ANTHROPIC_API_KEY is not set` on `/listing-score` | Add `ANTHROPIC_API_KEY=sk-ant-...` to your `.env` and restart |
| Rufus scorer returns `502` or malformed JSON | The LLM occasionally produces non-JSON output. Retry the request — it self-corrects |
