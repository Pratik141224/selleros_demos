"""
keyword_gap/omkar_client.py — re-export wrapper

All data-fetch logic has moved to shared/zyte_client.py.
This file exists only for import compatibility.
"""
from shared.zyte_client import (
    extract_asin,
    fetch_own_listing,
    fetch_competitor_summaries,
)

__all__ = [
    "extract_asin",
    "fetch_own_listing",
    "fetch_competitor_summaries",
]
