# SellerOS Demo Suite

Standalone AI-powered demo modules that prove SellerOS optimization claims for Amazon sellers. Each module is a self-contained service that runs independently or as part of the unified Enrichment API pipeline.

**Stack:** Python 3.11 · Flask / FastAPI · Anthropic / OpenRouter / OpenAI / Groq · XGBoost · AWS S3 · Zyte

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Modules at a Glance](#modules-at-a-glance)
- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Running the Services](#running-the-services)
- [Shared Infrastructure](#shared-infrastructure)
- [Module Details](#module-details)
  - [LQS — Listing Quality Scorer](#lqs--listing-quality-scorer)
  - [CompetitorAnalysis](#competitoranalysis)
  - [Keyword Gap Analyzer (D2)](#keyword-gap-analyzer-d2)
  - [ABD Optimizer (D4)](#abd-optimizer-d4)
  - [Buyer Persona Scorer (D3)](#buyer-persona-scorer-d3)
  - [Enrichment API (Unified Pipeline)](#enrichment-api-unified-pipeline)
- [Inter-Service Communication](#inter-service-communication)
- [S3 Caching Strategy](#s3-caching-strategy)
- [LLM Routing](#llm-routing)
- [Prompt Management](#prompt-management)
- [Repository File Map](#repository-file-map)
- [Design Decisions](#design-decisions)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Enrichment API  :5010                       │
│              (FastAPI — orchestrates all modules)               │
│                                                                 │
│  POST /api/enrich   →  Phase 1: fetch listing + competitors     │
│                     →  Phase 2: keyword_gap + lqs  (parallel)  │
│                     →  Phase 3: abd_enhance  (sequential)       │
└───────┬───────────────────────┬──────────────────┬─────────────┘
        │                       │                  │
        ▼                       ▼                  ▼
┌───────────────┐  ┌────────────────────┐  ┌──────────────────┐
│  LQS Service  │  │  keyword_gap       │  │  abd_optimizer   │
│  :8001        │  │  (module import)   │  │  (module import) │
│  FastAPI       │  │                    │  │                  │
│  6-step ML    │  │  1 LLM call        │  │  3 LLM calls     │
│  pipeline     │  │  + deterministic   │  │  A9 + Rufus +    │
└───────┬───────┘  └────────────────────┘  │  Hybrid merge    │
        │                                  └──────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│                    CompetitorAnalysis                         │
│              (Python module — no separate port)              │
│  Zyte API → bestseller fetch → semantic similarity → top-10  │
└──────────────────────────────────────────────────────────────┘

         All LLM calls flow through:
         shared/llm_router.py  →  DEMO_LLM_PROVIDER env var
         Provider options: openrouter | anthropic | openai | groq
```

### Request flow (all demo modules)

```
Browser POST /api/<endpoint>
  → Flask / FastAPI route validates input
  → agents.py pipeline function
      → shared/llm_router.py call(TaskType, system, user)
          → Provider SDK (OpenRouter / Anthropic / OpenAI / Groq)
          → Strip JSON fences → json.loads()
      → return typed dict
  → jsonify() → browser
```

---

## Modules at a Glance

| ID | Module | Port | LLM Calls | Purpose |
|----|--------|------|-----------|---------|
| — | LQS (FastAPI) | 8001 | 1 (Rufus pass) | ML pipeline scoring + A9 + Rufus text scorer |
| — | CompetitorAnalysis | (imported) | 0 | Semantic competitor discovery via Zyte |
| D2 | Keyword Gap Analyzer | 5002 | 1 | Frontend + backend keyword gap vs competitors |
| D3 | Buyer Persona Scorer | 5003 | 2 | Persona discovery + COSMO rewrite |
| D4 | ABD Optimizer | 5004 | 3 | Title + bullets + description A/B variants |
| — | Enrichment API | 5010 | up to 4 | Unified orchestration of all the above |

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11 | 3.14 also works for LQS |
| Homebrew (macOS) | For `libomp` — required by XGBoost on macOS |
| Zyte ingestion service | Internal EC2 endpoint for own product data |
| Zyte API key | Required by CompetitorAnalysis scraping |
| AWS credentials | For S3 result caching (can use IAM role on EC2) |
| LLM API key | At least one of: OpenRouter, Anthropic, OpenAI, Groq |

**macOS only — install OpenMP before anything else:**
```bash
brew install libomp
```

---

## Environment Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd selleros_demos

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate      # macOS / Linux
# venv\Scripts\activate       # Windows

# 3. Install all dependencies
pip install -r requirements.txt

# 4. Copy the example env file and fill in your values
cp .env.example .env
```

### Key environment variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DEMO_LLM_PROVIDER` | No (default: `openrouter`) | Active LLM backend: `openrouter` \| `anthropic` \| `openai` \| `groq` |
| `OPENROUTER_API_KEY` | If provider = openrouter | Free tier, ~200 req/day |
| `ANTHROPIC_API_KEY` | If provider = anthropic | Also required by LQS Rufus scorer directly |
| `OPENAI_API_KEY` | If provider = openai | — |
| `GROQ_API_KEY` | If provider = groq | — |
| `ZYTE_BASE_URL` | Yes | Own product data endpoint, e.g. `http://<ec2-ip>:4001` |
| `ZYTE_API_KEY` | Yes (CompetitorAnalysis) | For scraping competitor pages |
| `S3_BUCKET` | Yes | AWS S3 bucket name, e.g. `opsell` |
| `S3_RAW_PREFIX_KG` | No (default: `KeywordGap`) | S3 prefix for keyword gap cache |
| `S3_RAW_PREFIX_TE` | No (default: `TextEnhancement`) | S3 prefix for ABD optimizer cache |
| `S3_RAW_PREFIX_LQS` | No (default: `LQS`) | S3 prefix for LQS cache |
| `S3_RAW_PREFIX_ENRICH` | No (default: `Enrichment`) | S3 prefix for enrichment pipeline cache |
| `LQS_API_URL` | No (default: `http://localhost:8001`) | LQS FastAPI base URL (enrichment_api uses this) |
| `AWS_ACCESS_KEY_ID` | No (if using IAM role) | AWS credential |
| `AWS_SECRET_ACCESS_KEY` | No (if using IAM role) | AWS credential |
| `AWS_DEFAULT_REGION` | No (default: `ap-south-1`) | AWS region |
| `OPSELL_COUNTRY_CODE` | No (default: `IN`) | Amazon marketplace country code |
| `MODEL_PATH` | No (default: `DataStore/models/lqs_model.pkl`) | XGBoost model path |
| `ALLOW_ORIGINS` | No (default: `*`) | CORS origins for LQS FastAPI |

---

## Running the Services

Each service runs independently. Start only what you need.

### Option A — Individual services

```bash
# LQS FastAPI (port 8001) — run from LQS/ subdirectory
cd LQS
uvicorn api:app --port 8001 --reload
# Dashboard: http://localhost:8001/
# API docs:  http://localhost:8001/docs

# Keyword Gap Analyzer Flask app (port 5002) — from repo root
python keyword_gap/app.py
# Open: http://localhost:5002

# ABD Optimizer Flask app (port 5004) — from repo root
python abd_optimizer/app.py
# Open: http://localhost:5004

# Enrichment API FastAPI (port 5010) — from repo root
uvicorn enrichment_api.main:app --port 5010 --reload
# API docs: http://localhost:5010/docs
```

### Option B — All services at once (Procfile)

```bash
# Install honcho or foreman
pip install honcho
honcho start
```

The `Procfile` defines:

```
enrichment: uvicorn enrichment_api.main:app --port 5010 --reload
lqs:        bash -c "cd LQS && uvicorn api:app --port 8001 --reload"
kw_gap:     python keyword_gap/app.py
abd:        python abd_optimizer/app.py
```

### Verify everything is up

```bash
# Dependency check (no HTTP calls — imports and env only)
python check_dependencies.py

# LQS health
curl http://localhost:8001/healthz

# Enrichment API health
curl http://localhost:5010/healthz
```

---

## Shared Infrastructure

All modules pull from `shared/` for cross-cutting concerns. Nothing in this directory should be modified without reading its doc first.

### `shared/llm_router.py` — The only LLM entry point

Every LLM call in every demo module goes through here. Agents never call Anthropic / OpenAI SDKs directly.

```python
from shared.llm_router import call, TaskType

resp = call(
    task_type=TaskType.CREATIVE,   # or STRUCTURED, SCORING
    system="...",
    user="...",
    max_tokens=2048,
)
data = resp.content    # parsed dict (JSON fences already stripped)
cost = resp.cost_usd   # 0.0 on free OpenRouter tier
```

**TaskType → Model mapping (default provider: openrouter)**

| TaskType | Model | Use case |
|----------|-------|----------|
| `CREATIVE` | `qwen/qwen3-235b-a22b:free` | Persona copy, COSMO rewrites, editorial |
| `STRUCTURED` | `meta-llama/llama-3.3-70b-instruct:free` | A9 compliance, keyword gap JSON |
| `SCORING` | `meta-llama/llama-3.3-70b-instruct:free` | Rufus readiness evaluation |
| `FALLBACK` | `mistralai/mistral-small-3.1-24b-instruct:free` | Auto-used on HTTP 429 |

**On rate limit (HTTP 429):** router sleeps 3s and retries once with `FALLBACK` model. On second failure raises `ValueError("quota exhausted")`.

**Human voice rules** are auto-appended to every system prompt via `_HUMAN_VOICE_SUFFIX`. This bans filler transitions, hedge language, AI markers ("Certainly!", "Absolutely!"), stacked adjectives, and passive-voice bullets across all modules automatically.

### `shared/s3_cache.py` — Result caching

All expensive pipeline results are cached in S3 with a 14-day TTL.

```
s3://{S3_BUCKET}/{prefix}/{namespace}/latest.json      ← TTL check
s3://{S3_BUCKET}/{prefix}/{namespace}/history/{ts}.json ← append-only audit trail
```

```python
from shared.s3_cache import get, put

cached = get("KeywordGap", "B0XXXXXXXX")   # returns dict or None
put("KeywordGap", "B0XXXXXXXX", result)    # writes latest + history
```

S3 errors are swallowed silently — callers are never broken by a cache failure.

### `shared/zyte_client.py` — Product data layer

Fetches own listing data from the Zyte ingestion EC2 service and builds competitor context for LLM prompts.

```python
from shared.zyte_client import fetch_own_listing, build_competitor_block

listing = fetch_own_listing("B0XXXXXXXX", marketplace="IN")
# Returns: {asin, title, bullets, description, leaf_category_id, leaf_category_name}

block = build_competitor_block(competitors, purpose="keyword")  # or "conversion"
# Returns: plain-text block for injection into LLM prompt
```

Field name mappings between the Zyte API response and the internal schema live in:
- `shared/config/zyte_product_fields.yaml` — own product fields
- `shared/config/competitor_fields.yaml` — competitor fields

Edit these YAML files (not the Python) when the API renames a field.

### `shared/prompts/` — All prompt files

Every prompt is a versioned `.txt` file. Prompts are never inlined in agent code.

**Naming convention:** `<demo>_<pass>_v<N>.txt`

To update a prompt: create `v2`, update the import in `agents.py`. Never overwrite `v1` — rollback is a one-line revert.

Current prompt files:
- `d1_rufus_lqs_v1.txt` — Rufus readiness rubric for LQS Rufus pass
- `d2_keyword_gap_v1.txt` — Keyword gap + backend string generation
- `d3_persona_discovery_v1.txt` — Persona archetype discovery + fit scoring
- `d3_cosmo_rewrite_v1.txt` — COSMO cluster generation + listing rewrite

---

## Module Details

### LQS — Listing Quality Scorer

**Location:** `LQS/`
**Port:** 8001 (FastAPI)
**What it does:** Scores an Amazon product listing using two parallel systems — a market-performance ML pipeline (XGBoost) and a content-quality scorer (A9 + Rufus).

#### The 6-step ML pipeline (`POST /analyze`)

Accepts an ASIN, URL, or search query. Fetches live data from Zyte, scores with XGBoost, and returns competitor benchmarks.

```
[1] Ingestion   → Zyte API: product-details + top-N competitors
[2] Extraction  → Normalize raw API fields to internal schema
[3] QC          → Flag data issues (missing title, bad price, etc.)
[4] Features    → Build 23-feature vector the model expects
[5] Scoring     → XGBoost + heuristic blend → LQS, Grade, CTR, CVR, RPI
[6] Insights    → Gap report, RPI simulation scenarios, seller feedback
```

#### Text content scorer (`POST /listing-score` and `POST /analyze-listing`)

Two-pass scoring from raw listing text (no ASIN required for `/listing-score`):

- **Pass 1 — A9 compliance** (deterministic, no LLM): 8 dimensions, 100 pts total
  - Title Keyword Placement (25 pts), Title Structure (15 pts), Mobile Optimisation (15 pts), Bullet Compliance (20 pts), Backend Keywords (10 pts), Browse Node (10 pts), Attribute Completeness (3 pts), Content Richness (2 pts)
- **Pass 2 — Rufus readiness** (LLM via `shared/llm_client.py` → Anthropic): 8 dimensions
  - Intent Coverage, Use Case Specificity, Objection Handling, Persona Clarity, FAQ Readiness, Semantic Depth, Review Alignment, Conversational Naturalness
- **Overall score:** `a9 × 0.40 + rufus × 0.35 + lqs × 0.25`

> Note: `LQS/shared/` is a separate package from `selleros_demos/shared/`. When running as a standalone service (`cd LQS && uvicorn api:app`), LQS uses its own `shared/llm_client.py` which calls Anthropic directly. The Enrichment API uses shims at `selleros_demos/shared/llm_client.py` and `selleros_demos/shared/keyword_bridge.py` to bridge this difference.

**Key files:**
```
LQS/
├── api.py                      # FastAPI — all endpoints
├── main.py                     # CLI runner (no server)
├── config.py                   # Configuration (reads .env)
├── lqs_pipeline/
│   ├── Ingestion.py            # Step 1: Zyte fetch
│   ├── Extraction.py           # Step 2: field normalization
│   ├── QC.py                   # Step 3: data validation
│   ├── features.py             # Step 4: feature engineering
│   ├── pipeline.py             # Step 5: XGBoost scoring
│   ├── insights.py             # Step 6: gap report + feedback
│   └── zyte_client.py          # Internal Zyte wrapper
├── marketplaces/
│   ├── base_lqs.py             # ListingInput, LQSOutput, BaseLQSScorer (ABC)
│   └── amazon/
│       ├── a9_scorer.py        # Deterministic A9 (8 dimensions)
│       ├── rufus_scorer.py     # LLM Rufus (8 dimensions)
│       ├── lqs.py              # AmazonLQSScorer — orchestrates both passes
│       ├── asin_pipeline.py    # ASIN-driven: Zyte → score → insights
│       ├── zyte_mapper.py      # Config-driven field mapping
│       ├── lqs_insights.py     # Gap report, dimension gaps, feedback
│       └── field_map.yaml      # External field mapping (edit this, not code)
├── shared/
│   ├── llm_client.py           # Anthropic SDK wrapper (call_json)
│   └── prompts/
│       └── d1_rufus_lqs_v1.txt
└── DataStore/models/
    └── lqs_model.pkl           # Trained XGBoost model
```

**ASIN pipeline API (used by Enrichment API):**
```python
from marketplaces.amazon.asin_pipeline import run as lqs_run
result = lqs_run("B0XXXXXXXX", "IN")
```

---

### CompetitorAnalysis

**Location:** `CompetitorAnalysis/`
**Port:** None (imported as a module by Enrichment API and Keyword Gap)
**What it does:** Finds semantically similar competitor products given a seed ASIN.

Two-stage matching:
1. **Stage 1 (TitleMatcher):** Cosine similarity on titles using `BAAI/bge-small-en-v1.5` sentence transformer — keeps top 20
2. **Stage 2 (DeepMatcher):** Cosine similarity on full text (title + description + features) — re-ranks to top 10

Results are cached as Parquet files with a 14-day TTL.

**Usage:**
```python
from src.services.competitor_service import find_competitors

result = find_competitors("B0XXXXXXXX")
competitors = result["competitors"]  # list of dicts with asin, title, brand, price, deep_score, etc.
```

**Caching layers:**
| Level | Storage | Key | TTL |
|-------|---------|-----|-----|
| Product detail | JSON file | `data/cache/products/{asin}.json` | None |
| Product HTML | HTML file | `data/raw/html/products/{asin}.html` | None |
| Results | Parquet | `data/output/{seed_asin}/*.parquet` | 14 days |
| Run audit | JSON + HTML | `data/runs/{seed_asin}_{brand}/` | None |

**Key files:**
```
CompetitorAnalysis/
├── api.py                              # FastAPI REST API (standalone)
├── app.py                              # Streamlit web UI (standalone)
├── main.py                             # CLI entry point
├── config/settings.py                  # Loads ZYTE_API_KEY from .env
└── src/
    ├── clients/zyte_client.py          # Zyte API wrapper
    ├── pipelines/
    │   ├── product_pipeline.py         # Normalize single product
    │   └── bestseller_pipeline.py      # Fetch bestseller pages in parallel
    ├── matching/
    │   ├── title_matcher.py            # Stage 1: title cosine similarity
    │   └── deep_matcher.py             # Stage 2: full-text cosine similarity
    ├── services/competitor_service.py  # Core orchestration (find_competitors)
    └── utils/
        ├── product_fetcher.py          # Unified get_product() with JSON cache
        ├── cache.py                    # JSON product cache read/write
        ├── result_cache.py             # Parquet result cache with 14-day TTL
        └── parquet_writer.py           # Write timestamped Parquet results
```

---

### Keyword Gap Analyzer (D2)

**Location:** `keyword_gap/`
**Port:** 5002 (Flask)
**What it does:** Identifies front-end and back-end keyword gaps between a seller listing and top competitors. Generates a ready-to-paste optimised backend keyword string.

**Pipeline:**
```
Step 1a: Deterministic keyword extraction (no LLM)
         shared/keywords.py → unigrams, bigrams, trigrams, numerics, brands
         Byte count, duplicate detection, compliance check

Step 1b: Competitor data (CompetitorAnalysis module import or cache)
         Top-5 competitor title + bullets + description (compressed)

Step 2:  LLM call (TaskType.STRUCTURED)
         prompt: shared/prompts/d2_keyword_gap_v1.txt
         input:  seller listing + backend audit + compressed competitor data (~1,400 tokens)
         output: missing_critical, missing_secondary, generated_backend_string, backend_keyword_sets
```

**Endpoints:**
- `GET /` — web UI
- `POST /api/fetch-listing` — fetch listing + competitors by ASIN (uses Zyte + CompetitorAnalysis)
- `POST /api/analyze` — run keyword gap analysis (accepts manual text or data from fetch-listing)

**Output includes 8 backend keyword categories:** synonyms, long-tail, spelling variants, numeric/text pairs, intent phrases, locale variants (Hindi), seasonal terms, PPC harvest keywords.

**Key files:**
```
keyword_gap/
├── app.py          # Flask routes + S3 cache integration
├── agents.py       # LLM pipeline (run_keyword_gap_analysis)
├── omkar_client.py # Competitor fetch (wraps shared/zyte_client)
└── templates/
    └── index.html  # Web UI
```

---

### ABD Optimizer (D4)

**Location:** `abd_optimizer/`
**Port:** 5004 (Flask)
**What it does:** Generates two optimised variants of title + bullets + description (A9-first vs Rufus-first), then synthesises a hybrid recommendation.

**3-pass pipeline:**
```
Pass 1 — A9 Discovery Variant (TaskType.STRUCTURED):
  Rules: primary KW in first 5 words, benefit-led bullets, no superlatives, ≤200 chars title
  Scores: a9_compliance, rufus_readiness, keywords_found on ORIGINAL listing
  Output: variant_a {title, bullets, description, keywords_added}

Pass 2 — Rufus Conversion Variant (TaskType.CREATIVE):
  Rules: each bullet answers one of 5 Rufus buyer questions, ≥2 contractions,
         pre-empt durability + compatibility + sizing + return-risk objections
  Input includes: variant_a.title as A9 baseline reference
  Output: variant_b {title, bullets, description, personas_addressed, objections_handled}

Pass 3 — Scoring + Hybrid Merge (TaskType.STRUCTURED):
  Input: variant_a + variant_b
  Output: refined scores for both, hybrid.title (A9-compliant first 80 chars, human-readable rest),
          hybrid.rationale (cites specific dimensions), impact projections
```

**Endpoints:**
- `GET /` — web UI
- `POST /api/fetch-listing` — pull listing + competitors from Zyte by ASIN
- `POST /api/optimize` — run 3-pass optimization (manual fields or from fetch-listing)

**Validation after each pass** (title length, bullet count, persona count, no exclamation marks, etc.) — fails fast with specific error if constraints are violated.

**Key files:**
```
abd_optimizer/
├── app.py                  # Flask routes + S3 cache integration
├── agents.py               # 3-pass LLM pipeline (run_ab_optimization)
├── integration_bridge.py   # get_lqs_scores() — deterministic A9 scorer for Enrichment API
├── omkar_client.py         # Competitor fetch (wraps shared/zyte_client)
├── product_data.py         # Category label mappings
└── templates/
    └── index.html          # Web UI
```

---

### Buyer Persona Scorer (D3)

**Location:** `persona_scorer/`
**Port:** 5003 (Flask)
**What it does:** Discovers 3 buyer personas for a product and rewrites listing copy tuned to the dominant persona.

**2-pass pipeline:**
```
Pass 1 — Persona Discovery (TaskType.CREATIVE):
  prompt: shared/prompts/d3_persona_discovery_v1.txt
  input:  title + description + category + platform + price (~800 tokens)
  output: 3 personas (traffic_share_pct summing to 100), dominant_persona_id,
          fit_dimensions (5 scored dimensions), overall_fit_score

Pass 2 — COSMO Rewrite (TaskType.CREATIVE):
  prompt: shared/prompts/d3_cosmo_rewrite_v1.txt
  input:  dominant persona JSON + 3 lowest-scoring fit dimensions + listing (~1,200 tokens)
  output: semantic_clusters[], contextual_triggers[], rewritten_title, rewritten_bullets (5),
          faq_pairs (5), projected_cvr_improvement, projected_ctr_improvement
```

**Constraints enforced in code:**
- `traffic_share_pct` values must sum to 100 (validated before returning)
- `fit_score` and dimension scores clamped to 0–100
- `rewritten_title` trimmed to ≤200 chars
- FAQ questions phrased conversationally (as buyer would type to Rufus)
- Pass 2 only receives the 3 lowest-scoring dimensions (token efficiency)

**Key files:**
```
persona_scorer/
├── app.py       # Flask routes
├── agents.py    # 2-pass LLM pipeline
└── templates/
    └── index.html
```

---

### Enrichment API (Unified Pipeline)

**Location:** `enrichment_api/`
**Port:** 5010 (FastAPI)
**What it does:** Orchestrates all modules in parallel phases for a single ASIN input. The primary integration point when all capabilities are needed together.

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness check |
| `POST` | `/api/competitors` | Ranked competitors for an ASIN |
| `POST` | `/api/keyword-gap` | Fetch listing + run keyword gap analysis |
| `POST` | `/api/lqs` | Full LQS pipeline (A9 + Rufus + ML insights) |
| `POST` | `/api/enhance` | 3-pass ABD text optimization (requires LQS cache or `force_refresh=true`) |
| `POST` | `/api/enrich` | Full orchestrated pipeline (all 4 steps) |

**Request body (`/api/enrich`):**
```json
{
  "asin": "B0XXXXXXXX",
  "country": "IN",
  "force_refresh": false,
  "steps": ["competitors", "keywords", "lqs", "enhance"]
}
```

**Execution phases (`/api/enrich`):**
```
Phase 1 (parallel):   fetch_listing  +  run_competitors
Phase 2 (parallel):   run_keyword_gap  +  run_lqs
Phase 3 (sequential): run_enhance  (uses Phase 2 outputs as context)
```

Response includes: `listing`, `competitors`, `keyword_gap`, `lqs`, `enhancement`, `meta` (elapsed_ms, keywords_injected, steps_run).

**Key dependency note:** `/api/enhance` requires LQS scores to exist in S3 cache. Run `/api/lqs` first, or pass `force_refresh=true` to compute inline.

**Key files:**
```
enrichment_api/
├── main.py         # FastAPI app + all endpoints
├── models.py       # Pydantic request models (ASINRequest, EnrichRequest)
└── orchestrator.py # Step functions + parallel orchestration logic
```

---

## Inter-Service Communication

```
enrichment_api/orchestrator.py
  ├── fetch_listing()       → shared/zyte_client.fetch_own_listing()
  │                           → Zyte EC2 service (HTTP POST /extract/product)
  │
  ├── run_competitors()     → CompetitorAnalysis/src/services/competitor_service.find_competitors()
  │                           → Zyte API (scraping) + sentence transformers (local)
  │                           → Parquet cache (local disk, 14-day TTL)
  │
  ├── run_keyword_gap()     → keyword_gap/agents.run_keyword_gap_analysis()
  │                           → shared/llm_router.call()  →  LLM provider
  │                           → shared/s3_cache.put("KeywordGap", asin, result)
  │
  ├── run_lqs()             → LQS/marketplaces/amazon/asin_pipeline.run()
  │                           → shared/zyte_client (via LQS internal path)
  │                           → LQS/shared/llm_client.py  →  Anthropic (Rufus pass)
  │                           → shared/s3_cache.put("LQS", asin, result)
  │
  └── run_enhance()         → abd_optimizer/agents.run_ab_optimization()
                              → shared/llm_router.call()  →  LLM provider  (×3)
                              → shared/s3_cache.put("TextEnhancement", asin, result)
```

**sys.path ordering:** `selleros_demos/` is inserted at position 0 so `shared.*` imports resolve to `selleros_demos/shared/` (llm_router, zyte_client, s3_cache). `LQS/` is appended (lower priority) so `marketplaces.*` and `lqs_pipeline.*` resolve there. `CompetitorAnalysis/` is also appended for `src.services.*`.

---

## S3 Caching Strategy

All results are cached in AWS S3 under the `opsell` bucket (configurable via `S3_BUCKET`).

| Module | Prefix env var | Default prefix | Cache key |
|--------|---------------|----------------|-----------|
| Keyword Gap | `S3_RAW_PREFIX_KG` | `KeywordGap` | ASIN |
| ABD Optimizer | `S3_RAW_PREFIX_TE` | `TextEnhancement` | ASIN |
| LQS | `S3_RAW_PREFIX_LQS` | `LQS` | ASIN |
| Enrichment | `S3_RAW_PREFIX_ENRICH` | `Enrichment` | ASIN |

**S3 layout per cache entry:**
```
s3://opsell/{prefix}/{asin}/latest.json          ← TTL check (overwritten each run)
s3://opsell/{prefix}/{asin}/history/{ts}.json    ← append-only audit trail
```

**TTL:** 14 days. After expiry, `get()` returns `None` and the pipeline runs fresh.

**Force refresh:** Pass `force_refresh: true` in any request body to skip the cache read and write a fresh result.

---

## LLM Routing

The router (`shared/llm_router.py`) reads `DEMO_LLM_PROVIDER` from the environment and selects models accordingly. Switching providers requires only changing one env var — no code changes.

**Provider model tables:**

| Provider | CREATIVE | STRUCTURED | SCORING | FALLBACK |
|----------|----------|------------|---------|---------|
| `openrouter` (default) | qwen3-235b-a22b:free | llama-3.3-70b:free | llama-3.3-70b:free | mistral-small:free |
| `anthropic` | claude-sonnet-4-6 | claude-sonnet-4-6 | claude-sonnet-4-6 | claude-sonnet-4-6 |
| `openai` | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini |
| `groq` | llama-3.3-70b-versatile | llama-3.3-70b-versatile | llama-3.3-70b-versatile | llama-3.3-70b-versatile |

**Cost estimate per demo run (when using Anthropic):**

| Demo | LLM Calls | Approx. cost |
|------|-----------|-------------|
| LQS text scorer | 1 | ~$0.01 |
| Keyword Gap (D2) | 1 | ~$0.03 |
| Buyer Persona (D3) | 2 | ~$0.04–0.06 |
| ABD Optimizer (D4) | 3 | ~$0.05–0.07 |

OpenRouter free tier: $0.00 (quota ~200 req/day).

---

## Prompt Management

Prompts live in `shared/prompts/` as versioned `.txt` files and are loaded at import time by each agent. They are never inlined in Python.

| File | Used by | Purpose |
|------|---------|---------|
| `d1_rufus_lqs_v1.txt` | LQS/shared/llm_client | Rufus readiness rubric (8 dimensions) |
| `d2_keyword_gap_v1.txt` | keyword_gap/agents | Keyword gap + backend string generation |
| `d3_persona_discovery_v1.txt` | persona_scorer/agents (Pass 1) | Persona archetype discovery + fit scoring |
| `d3_cosmo_rewrite_v1.txt` | persona_scorer/agents (Pass 2) | COSMO cluster + listing rewrite |

**To update a prompt:**
1. Create `d2_keyword_gap_v2.txt` (never overwrite v1)
2. Update the prompt path constant in `agents.py`
3. Rollback = one-line change back to v1 path

---

## Repository File Map

```
selleros_demos/
│
├── CLAUDE.md                    # Claude Code project instructions
├── Procfile                     # Service definitions for honcho/foreman
├── requirements.txt             # All Python dependencies
├── .env.example                 # Template — copy to .env and fill in
├── check_dependencies.py        # Import + env validation (no HTTP calls)
│
├── shared/                      # Shared by all modules — do not bypass
│   ├── llm_router.py            # THE ONLY place that calls LLM SDKs
│   ├── s3_cache.py              # S3 result cache (get/put, 14-day TTL)
│   ├── zyte_client.py           # Own listing fetch + competitor block builder
│   ├── keyword_bridge.py        # Shim: bridges LQS keyword extraction for Enrichment API
│   ├── llm_client.py            # Shim: bridges LQS Anthropic client for Enrichment API
│   └── config/
│       ├── zyte_product_fields.yaml   # Field mappings for own product API responses
│       └── competitor_fields.yaml     # Field mappings for competitor API responses
│
├── LQS/                         # Listing Quality Scorer — FastAPI service
│   ├── api.py                   # FastAPI endpoints (/analyze, /listing-score, /analyze-listing)
│   ├── config.py                # Configuration (reads env)
│   ├── lqs_pipeline/            # 6-step ML pipeline (XGBoost)
│   ├── marketplaces/amazon/     # A9 scorer + Rufus scorer + ASIN pipeline
│   ├── shared/                  # LQS-internal: llm_client.py + prompts/
│   └── DataStore/models/        # lqs_model.pkl (XGBoost)
│
├── CompetitorAnalysis/          # Semantic competitor discovery
│   ├── src/services/competitor_service.py   # find_competitors() — main entry point
│   ├── src/matching/            # TitleMatcher + DeepMatcher
│   ├── src/clients/zyte_client.py           # Zyte scraping client
│   └── data/                    # Local Parquet + JSON caches
│
├── keyword_gap/                 # D2 — Keyword Gap Analyzer (Flask :5002)
│   ├── app.py                   # Routes + S3 cache
│   ├── agents.py                # run_keyword_gap_analysis()
│   └── omkar_client.py          # Competitor fetch wrapper
│
├── abd_optimizer/               # D4 — ABD Optimizer (Flask :5004)
│   ├── app.py                   # Routes + S3 cache
│   ├── agents.py                # run_ab_optimization() — 3-pass pipeline
│   └── integration_bridge.py   # get_lqs_scores() for Enrichment API
│
├── persona_scorer/              # D3 — Buyer Persona Scorer (Flask :5003)
│   ├── app.py
│   └── agents.py                # 2-pass pipeline
│
├── enrichment_api/              # Unified orchestration layer (FastAPI :5010)
│   ├── main.py                  # Endpoints
│   ├── models.py                # ASINRequest, EnrichRequest (Pydantic)
│   └── orchestrator.py          # Parallel phase runner + all step functions
│
├── DataStore/                   # Shared ML artefacts
│   └── models/lqs_model.pkl     # XGBoost model (do not delete)
│
└── .claude/                     # Claude Code internal docs (not shipped to users)
    ├── arch.md                  # Architecture reference
    ├── agents/                  # Per-module I/O contracts
    └── decisions/               # Architecture Decision Records
```

---

## Design Decisions

**No database, no queue.** Demos are stateless — all results are either in-memory or S3-cached. No PostgreSQL, Redis, or Celery. See `.claude/decisions/001_no_db.md`.

**LLM routing by task type, not by module.** `TaskType.CREATIVE` / `STRUCTURED` / `SCORING` select the appropriate model regardless of which demo calls them. See `.claude/decisions/002_model_routing.md`.

**Max 3 LLM calls per demo run.** This caps cost and latency. If a pipeline needs more, split into passes — not extra calls. D4's 3 passes stay within this cap.

**JSON mode enforced everywhere.** Every LLM call sets `response_format={"type": "json_object"}`. JSON fences are stripped before `json.loads()` regardless (`_strip_fences()` in llm_router).

**Competitor data from Zyte + CompetitorAnalysis — never direct Amazon scraping.** All Amazon data goes through the Zyte EC2 ingestion service or the CompetitorAnalysis module.

**sys.path priority:** `selleros_demos/` at index 0 wins all `shared.*` conflicts. `LQS/` is appended so `marketplaces.*` resolves there without conflicting with top-level modules.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `503 Model not loaded` on LQS `/readyz` | Run `brew install libomp` (macOS only), then restart |
| `Address already in use` | `lsof -ti :<port> \| xargs kill -9` then restart |
| `ANTHROPIC_API_KEY is not set` | Add the key to `.env` and restart. LQS Rufus pass requires this regardless of `DEMO_LLM_PROVIDER` |
| Enrichment `/api/enhance` returns 400 | Run `/api/lqs` first for the ASIN, or add `"force_refresh": true` to the request |
| S3 errors logged as warnings | Check `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET` in `.env`. Cache errors are non-fatal — pipeline continues |
| OpenRouter 429 / quota exhausted | Router auto-retries once with FALLBACK model. If it fails again, switch `DEMO_LLM_PROVIDER=anthropic` in `.env` |
| Competitor list is empty | Seed ASIN's category returned no bestsellers. Try a different ASIN, or the CompetitorAnalysis local cache may need clearing (`CompetitorAnalysis/data/cache/`) |
| `Could not extract a valid ASIN` | Provide a 10-character ASIN (e.g. `B0XXXXXXXX`) or a full Amazon product URL containing `/dp/<ASIN>` |
| Keyword gap returns cached stale result | Pass `"force_refresh": true` in the request body |
| `json.JSONDecodeError` from LLM | LLM returned non-JSON (rare). Retry — the router's `_strip_fences()` handles most cases. If persistent, log the raw output and file an issue |
| `check_dependencies.py` shows a failed import | The missing package name is shown in red. Run `pip install -r requirements.txt` and re-run |
