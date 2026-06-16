"""
enrichment_api/main.py

SellerOS AI Enrichment API — FastAPI service on port 5010.

Endpoints:
  GET  /healthz             — liveness check
  POST /api/competitors     — ranked competitors for an ASIN
  POST /api/keyword-gap     — keyword gap analysis (fetches listing + competitors)
  POST /api/lqs             — full LQS pipeline (A9 + Rufus + insights)
  POST /api/enhance         — 3-pass ABD text optimization
  POST /api/enrich          — orchestrated pipeline (parallel phases, all 4 steps)

Run: uvicorn enrichment_api.main:app --port 5010 --reload
"""
from __future__ import annotations

import os
import sys

# Path setup must happen before any local imports.
# LQS is excluded — it runs as a separate service to avoid shared/ package conflicts.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from enrichment_api.models import ASINRequest, EnrichRequest
from enrichment_api import orchestrator as orch
from shared.s3_cache import get as cache_get

app = FastAPI(title="SellerOS Enrichment API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/competitors")
def competitors(req: ASINRequest):
    """Fetch ranked competitors for the given ASIN via CompetitorAnalysis."""
    comps = orch.run_competitors(req.asin, req.force_refresh)
    return {"asin": req.asin, "competitors": comps, "count": len(comps)}


@app.post("/api/keyword-gap")
def keyword_gap(req: ASINRequest):
    """
    Fetch listing + competitors, then run keyword gap analysis.

    Required body: {"asin": "<10-char ASIN>"}
    Optional:      {"country": "IN", "force_refresh": false}
    """
    try:
        listing = orch.fetch_listing(req.asin, req.country)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Listing fetch failed: {exc}")

    comps     = orch.run_competitors(req.asin, req.force_refresh)
    summaries = orch._comp_summaries(comps)
    return orch.run_keyword_gap(req.asin, listing, summaries, req.force_refresh)


@app.post("/api/lqs")
def lqs(req: ASINRequest):
    """Full LQS pipeline — target gets A9 + Rufus + insights; competitors get scores only."""
    result = orch.run_lqs(req.asin, req.country)
    if not result:
        raise HTTPException(status_code=502, detail="LQS pipeline returned no data")
    return result


@app.post("/api/enhance")
def enhance(req: ASINRequest):
    """
    Full 3-pass ABD text enhancement.

    Requires /api/lqs to have been run first for this ASIN — scores are read
    from the LQS cache so Enhancement uses the exact same A9 + Rufus values.
    Pass force_refresh=true to re-run LQS inline and bust both caches.
    """
    # ── Require LQS scores to be cached ──────────────────────────────────────
    lqs_cached = cache_get(orch._LQS_PREFIX, req.asin)
    if not lqs_cached and not req.force_refresh:
        raise HTTPException(
            status_code=400,
            detail=(
                f"LQS scores not found for {req.asin}. "
                "Run POST /api/lqs first, or pass force_refresh=true to compute inline."
            ),
        )
    if req.force_refresh or not lqs_cached:
        lqs_cached = orch.run_lqs(req.asin, req.country, force_refresh=True)
        if not lqs_cached:
            raise HTTPException(status_code=502, detail="LQS pipeline returned no data")

    # ── Fetch listing + competitors ───────────────────────────────────────────
    listing   = orch.fetch_listing(req.asin, req.country)
    comps     = orch.run_competitors(req.asin, req.force_refresh)
    summaries = orch._comp_summaries(comps)

    # ── Keyword gap: read from cache; run inline if missing ───────────────────
    kw = cache_get(orch._KG_PREFIX, req.asin) or {}
    if not kw:
        kw = orch.run_keyword_gap(req.asin, listing, summaries, req.force_refresh)

    # ── Build lqs_context from cached LQS + keyword gap scores ───────────────
    a9_context = orch._lqs_context_for_enhance(lqs_cached, kw)
    missing    = orch._extract_missing_keywords(kw)
    return orch.run_enhance(req.asin, listing, summaries, a9_context, missing, req.force_refresh)


@app.post("/api/enrich")
def enrich(req: EnrichRequest):
    """
    Orchestrated pipeline — runs all steps in optimal parallel phases.

    Default steps: competitors → keywords + lqs (parallel) → enhance.
    Pass 'steps' to run a subset: ["competitors", "keywords", "lqs", "enhance"].
    """
    return orch.run_enrich(req.asin, req.country, req.steps, req.force_refresh)
