"""
Opsell LQS — FastAPI service.

Run locally:
    uvicorn api:app --reload --port 8000

Endpoints:
    POST /analyze    Full 6-step pipeline → scores + insights JSON
    GET  /healthz    Liveness probe (process alive)
    GET  /readyz     Readiness probe (model loaded)
"""
import hashlib
import logging
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, model_validator

import lqs_pipeline.pipeline as pipeline_module
from config import CFG
from shared import s3_cache
from lqs_pipeline.Ingestion import ingest
from lqs_pipeline.Extraction import extract_all
from lqs_pipeline.QC import run_qc
from lqs_pipeline.features import build_all_features
from lqs_pipeline.insights import generate_insights
from marketplaces.base_lqs import ListingInput
from marketplaces.amazon import AmazonLQSScorer
from marketplaces.amazon.asin_pipeline import run as run_asin_lqs_pipeline


# ── Logging setup ─────────────────────────────────────────────────────────────

class _InterceptHandler(logging.Handler):
    """Bridge stdlib logging (uvicorn, fastapi, etc.) into loguru."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _setup_logging() -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(_name).handlers = [_InterceptHandler()]


_setup_logging()


# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Opsell LQS API v2.0.0")
    try:
        pipeline_module.load_model()
        app.state.model_ready = True
        logger.info("Model loaded — API ready")
    except Exception as exc:
        app.state.model_ready = False
        logger.error("Model failed to load: {}", exc)
    yield
    logger.info("Shutting down")


app = FastAPI(title="Opsell LQS API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CFG.allow_origins.split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# ── Request / Response models ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    mode : Literal["asin", "url", "query"]
    asin : Optional[str] = None
    url  : Optional[str] = None
    query: Optional[str] = None
    force_refresh: bool  = False  # bypass cache and re-run the full pipeline

    @model_validator(mode="after")
    def _check_required_fields(self):
        if self.mode == "asin" and not self.asin:
            raise ValueError("'asin' is required when mode='asin'")
        if self.mode == "url" and not self.url:
            raise ValueError("'url' is required when mode='url'")
        if self.mode == "query" and not self.query:
            raise ValueError("'query' is required when mode='query'")
        return self


class ListingScoreRequest(BaseModel):
    """
    Text-based listing quality scoring request for Amazon marketplace.

    primary_keyword / secondary_keywords — optional; auto-extracted from
    backend_keywords or title when absent.

    lqs_score_override — pass the lqs score from the existing ML pipeline
    (pipeline.predict_lqs) to use it as the lqs_score component. Omit to
    fall back to the content-quality heuristic.
    """
    title:               str
    description:         str            = ""
    bullets:             list[str]      = []
    backend_keywords:    str            = ""
    browse_node:         str            = ""
    brand:               str            = ""
    category:            str            = ""
    aplus_content:       str            = ""
    images:              list[dict]     = []
    attributes:          dict           = {}
    qa_pairs:            list[dict]     = []
    review_summary:      dict           = {}
    primary_keyword:     str            = ""
    secondary_keywords:  list[str]      = []
    lqs_score_override:  Optional[int]  = None
    force_refresh:       bool           = False  # bypass cache and re-run Rufus LLM


_amazon_scorer = AmazonLQSScorer()


class AnalyzeListingRequest(BaseModel):
    asin:          str
    marketplace:   str  = "amazon"  # platform: "amazon", "myntra", etc.
    country:       str  = "IN"      # country code: "IN", "US", "UK", etc.
    force_refresh: bool = False     # bypass cache and re-scrape + re-score


# ── S3 cache namespace helpers ────────────────────────────────────────────────
# Namespaces map to paths inside s3://{S3_BUCKET}/{S3_RAW_PREFIX_LQS}/.
# TTL (15 days) is enforced inside s3_cache.get().

def _pipeline_ns(req: AnalyzeRequest) -> str:
    identifier = req.asin or req.url or req.query or "unknown"
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", identifier)[:120]
    return f"pipeline/{req.mode}/{safe}"


def _marketplace_ns(req: AnalyzeListingRequest) -> str:
    return f"marketplace/{req.marketplace.strip().lower()}/{req.country.strip().upper()}/{req.asin.strip().upper()}"


def _text_score_ns(req: ListingScoreRequest) -> str:
    raw = "|".join([
        req.title, "|".join(req.bullets), req.description,
        req.primary_keyword, req.backend_keywords,
        str(sorted(req.qa_pairs)), str(req.review_summary),
    ])
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"text_score/{digest}"


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse("dashboard.html")


@app.get("/healthz", tags=["ops"])
def healthz():
    """Liveness probe — returns 200 as long as the process is running."""
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
def readyz(request: Request):
    """Readiness probe — returns 503 until the ML model is loaded."""
    if not request.app.state.model_ready:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ready"}


@app.post("/analyze-listing", tags=["scoring"])
def analyze_listing(req: AnalyzeListingRequest):
    """
    Amazon marketplace LQS for a live ASIN + its category competitors.

    Flow:
      1. Fetch target + competitors from Zyte (reuses Ingestion pipeline)
      2. Map Zyte fields → ListingInput via field_map.yaml (no hardcoded field names)
      3. Score each product with AmazonLQSScorer (A9 + Rufus passes)
      4. Generate gap report, dimension gaps, and seller feedback

    Results cached 10 minutes keyed by ASIN + marketplace.
    Pass force=true to bypass cache and re-scrape.

    Requires ANTHROPIC_API_KEY (Rufus LLM pass).
    """
    logger.info(
        "POST /analyze-listing | force_refresh={} | asin={} | marketplace={} | country={}",
        req.force_refresh, req.asin, req.marketplace, req.country,
    )
    t0 = time.perf_counter()

    ns = _marketplace_ns(req)

    if not req.force_refresh:
        cached = s3_cache.get(ns)
        if cached:
            logger.info("POST /analyze-listing S3 HIT | {}", ns)
            return {**cached, "cached": True}

    try:
        payload = run_asin_lqs_pipeline(req.asin, country=req.country)
        elapsed = time.perf_counter() - t0

        target_scores = next(
            r["scores"] for r in payload["results"] if r["label"] == "TARGET"
        )
        logger.info(
            "POST /analyze-listing complete | {:.2f}s | asin={} overall={} a9={} rufus={}",
            elapsed,
            req.asin,
            target_scores["overall"],
            target_scores["a9_compliance"],
            target_scores["rufus_readiness"],
        )

        response = {"ok": True, "cached": False, **payload}
        s3_cache.put(ns, response)
        return response

    except (ValueError, RuntimeError) as exc:
        logger.warning("POST /analyze-listing 400 | asin={} — {}", req.asin, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except EnvironmentError as exc:
        logger.error("POST /analyze-listing 503 — {}", exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("POST /analyze-listing 500 | asin={}", req.asin)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/listing-score", tags=["scoring"])
def listing_score(req: ListingScoreRequest):
    """
    Amazon marketplace LQS — text-based, two-pass scoring.

    Pass 1 (A9)    — deterministic, no LLM, instant.
    Pass 2 (Rufus) — LLM-evaluated via Anthropic API (~2–4 s).

    Results are cached in S3 for 15 days keyed by a hash of the listing content.
    Pass force_refresh=true to bypass the cache and re-run the Rufus LLM.

    Requires ANTHROPIC_API_KEY to be set in the environment.
    """
    logger.info("POST /listing-score | force_refresh={} | title={!r}", req.force_refresh, req.title[:60])
    t0 = time.perf_counter()

    ns = _text_score_ns(req)

    if not req.force_refresh:
        cached = s3_cache.get(ns)
        if cached:
            logger.info("POST /listing-score S3 HIT | {}", ns[-16:])
            return {**cached, "cached": True}

    try:
        listing = ListingInput(
            title=req.title,
            description=req.description,
            bullets=req.bullets,
            backend_keywords=req.backend_keywords,
            browse_node=req.browse_node,
            brand=req.brand,
            category=req.category,
            aplus_content=req.aplus_content,
            images=req.images,
            attributes=req.attributes,
            qa_pairs=req.qa_pairs,
            review_summary=req.review_summary,
            primary_keyword=req.primary_keyword,
            secondary_keywords=req.secondary_keywords,
            lqs_score_override=req.lqs_score_override,
        )
        result = _amazon_scorer.score(listing)
        elapsed = time.perf_counter() - t0
        logger.info(
            "POST /listing-score complete | {:.2f}s | overall={} a9={} rufus={}",
            elapsed,
            result.scores["overall"],
            result.scores["a9_compliance"],
            result.scores["rufus_readiness"],
        )
        payload = {"ok": True, "cached": False, **result.to_dict()}
        s3_cache.put(ns, payload)
        return payload

    except (ValueError, RuntimeError) as exc:
        logger.warning("POST /listing-score 400 — {}", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except EnvironmentError as exc:
        logger.error("POST /listing-score 503 — {}", exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("POST /listing-score 500 — unhandled error")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/analyze", tags=["scoring"])
def analyze(req: AnalyzeRequest):
    """
    Run the full 6-step pipeline:
    Ingest → Extract → QC → Features → Score → Insights

    Results are cached in S3 for 15 days keyed by mode + identifier.
    Pass force_refresh=true to bypass the cache and re-scrape from source.

    Returns competitor scores, gap report, RPI simulation, and seller feedback.
    """
    if not app.state.model_ready:
        raise HTTPException(status_code=503, detail="Model not loaded yet — try /readyz")

    identifier = req.asin or req.url or req.query or "(unknown)"
    logger.info("POST /analyze | force_refresh={} | mode={} | identifier={!r}", req.force_refresh, req.mode, identifier)
    t0 = time.perf_counter()

    ns = _pipeline_ns(req)

    if not req.force_refresh:
        cached = s3_cache.get(ns)
        if cached:
            logger.info("POST /analyze S3 HIT | {}", ns)
            return {**cached, "cached": True}

    try:
        kwargs: dict = {}
        if req.asin:  kwargs["asin"]  = req.asin
        if req.url:   kwargs["url"]   = req.url
        if req.query: kwargs["query"] = req.query

        # Step 1 — Ingest
        t1 = time.perf_counter()
        logger.debug("Step 1: Ingestion starting")
        ingested = ingest(req.mode, **kwargs)
        logger.debug("Step 1: Ingestion done in {:.2f}s — {} competitor(s) collected",
                     time.perf_counter() - t1, len(ingested["competitors"]))

        # Step 2 — Extract
        t2 = time.perf_counter()
        logger.debug("Step 2: Extraction starting")
        extracted = extract_all(ingested)
        logger.debug("Step 2: Extraction done in {:.2f}s", time.perf_counter() - t2)

        # Step 3 — QC
        t3 = time.perf_counter()
        logger.debug("Step 3: QC starting")
        qc_data = run_qc(extracted)
        logger.debug("Step 3: QC done in {:.2f}s", time.perf_counter() - t3)

        # Step 4 — Features
        t4 = time.perf_counter()
        logger.debug("Step 4: Feature engineering starting")
        feat_data = build_all_features(qc_data)
        logger.debug("Step 4: Feature engineering done in {:.2f}s", time.perf_counter() - t4)

        # Step 5 — Score
        t5 = time.perf_counter()
        logger.debug("Step 5: Pipeline scoring starting")
        df = pipeline_module.run_pipeline(feat_data)
        logger.debug("Step 5: Scoring done in {:.2f}s", time.perf_counter() - t5)

        # Step 6 — Insights
        t6 = time.perf_counter()
        logger.debug("Step 6: Insights generation starting")
        insights = generate_insights(df, extracted["source"], make_chart=False)
        logger.debug("Step 6: Insights done in {:.2f}s", time.perf_counter() - t6)

        total = time.perf_counter() - t0
        logger.info("POST /analyze complete | {:.2f}s total | target={} LQS={} grade={}",
                    total, identifier, df.loc["TARGET"]["lqs"], df.loc["TARGET"]["grade"])

        scores = (
            df.reset_index()
              .rename(columns={"index": "label"})
              .to_dict("records")
        )

        payload = {
            "ok"            : True,
            "cached"        : False,
            "source"        : extracted["source"],
            "scores"        : scores,
            "gap_report"    : insights["gap_report"],
            "rpi_simulation": insights["rpi_simulation"],
            "feedback"      : insights["feedback"],
        }
        s3_cache.put(ns, payload)
        return payload

    except (ValueError, RuntimeError) as exc:
        logger.warning("POST /analyze 400 | mode={} identifier={!r} — {}", req.mode, identifier, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("POST /analyze 500 — unhandled error | mode={} identifier={!r}", req.mode, identifier)
        raise HTTPException(status_code=500, detail=str(exc))
