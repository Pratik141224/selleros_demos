"""
shared — SellerOS common utilities

Public API (import from `shared` directly):

    call, TaskType              — multi-provider LLM router (openrouter / anthropic / openai / groq)
    extract_asin                — parse 10-char ASIN from URL or bare string
    fetch_own_listing           — fetch seller's own listing via Zyte /extract/product
    fetch_competitor_summaries  — CompetitorAnalysis-backed competitor fetch
    build_competitor_block      — build plain-text competitor block for LLM prompts
    cache_get, cache_put        — S3 result cache with 15-day TTL

Note: claude_client.py is legacy (predates llm_router.py). It is kept for backwards
compatibility with persona_scorer / sosdemo but is NOT exported from this package.
"""

from shared.llm_router import call, TaskType
from shared.zyte_client import (
    extract_asin,
    fetch_own_listing,
    fetch_competitor_summaries,
    build_competitor_block,
)
from shared.s3_cache import get as cache_get, put as cache_put

__all__ = [
    # LLM routing
    "call",
    "TaskType",
    # Zyte / competitor data
    "extract_asin",
    "fetch_own_listing",
    "fetch_competitor_summaries",
    "build_competitor_block",
    # S3 caching
    "cache_get",
    "cache_put",
]
