"""
CompetitorAnalysis/src/clients/ingestion_client.py

Drop-in replacement for ZyteClient. Routes all product data requests through the
shared RawIngestionService (ZYTE_BASE_URL) instead of calling the Zyte API directly.

Benefits over the direct ZyteClient:
  - Redis + S3 caching (14-day TTL) — repeat calls for the same ASIN return in <10 ms
  - Automatic retries and fallbacks inside the service
  - No ZYTE_API_KEY required — auth is handled server-side

Method signatures and return shapes are identical to ZyteClient so all callers
(product_pipeline, bestseller_pipeline, etc.) require only a 1-line import swap.
"""

import os
import re

import requests

ZYTE_BASE_URL = os.getenv("ZYTE_BASE_URL", "http://54.197.215.125:4001")
TIMEOUT = 90        # single-product ceiling (Zyte cold call ~20 s)
BATCH_TIMEOUT = 300  # batch ceiling: up to 20 ASINs × 20 s / 5 concurrent = 4 waves → ~80 s + overhead


class IngestionClient:
    """Routes CompetitorAnalysis Zyte calls through the shared RawIngestionService."""

    def fetch_product(self, asin: str) -> dict:
        """
        POST /scrape/product — raw Zyte product object.

        Returns {"product": <zyte_product_dict>} — same envelope as the direct
        ZyteClient so product_pipeline.py reads response["product"] unchanged.
        """
        resp = requests.post(
            f"{ZYTE_BASE_URL}/scrape/product",
            json={"asin": asin, "marketplace": "IN"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return {"product": resp.json()["data"]}

    def fetch_product_list(self, url: str) -> dict:
        """
        POST /scrape/product-list — product list from any URL (category, bestseller, …).

        Returns {"productList": {"products": [...]}} — same envelope as the direct
        ZyteClient so bestseller_pipeline.py reads response["productList"]["products"]
        unchanged.
        """
        resp = requests.post(
            f"{ZYTE_BASE_URL}/scrape/product-list",
            json={"url": url},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        products = resp.json().get("data", {}).get("products", [])
        return {"productList": {"products": products}}

    def fetch_html(self, url: str) -> str:
        """
        GET /scrape/product/{asin}/html — cached browser HTML for an ASIN.

        Extracts the ASIN from the URL, then retrieves the HTML cached by the
        ingestion service when fetch_product() was called for that ASIN.
        Returns "" if no ASIN is found in the URL or the HTML is not yet cached
        (24 h Redis TTL). Never raises — callers treat "" as a no-op.

        Note: category/listing/hierarchy URLs that contain no ASIN always return "".
        Those pipelines (CategoryPipeline, ListingPipeline, etc.) are standalone
        utilities not called from find_competitors() so this degradation is acceptable.
        """
        m = re.search(r"/dp/([A-Z0-9]{10})", url, re.IGNORECASE)
        if not m:
            return ""
        asin = m.group(1).upper()
        try:
            resp = requests.get(
                f"{ZYTE_BASE_URL}/scrape/product/{asin}/html",
                params={"marketplace": "IN"},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json().get("html", "")
        except Exception:
            pass
        return ""

    def fetch_products_batch(self, asins: list[str]) -> dict[str, dict]:
        """
        POST /scrape/products/batch — fetch up to 20 ASINs in a single request.

        The service fans the ASINs out with ZYTE_MAX_CONCURRENCY=5 internally.
        For 20 cache-miss ASINs: ~2× single-ASIN latency (2 waves of 5) instead of 20×.
        For Redis hits: < 100 ms for the entire batch.

        Returns {asin: {"product": <raw_zyte_data>}} for successful ASINs only.
        Failed ASINs (data contains "error") are omitted — callers skip them silently.
        Return shape per ASIN is identical to fetch_product() so _map_response() works
        on both single and batch results.
        """
        if not asins:
            return {}
        resp = requests.post(
            f"{ZYTE_BASE_URL}/scrape/products/batch",
            json={"asins": asins[:20], "marketplace": "IN"},
            timeout=BATCH_TIMEOUT,
        )
        resp.raise_for_status()
        out = {}
        for asin, result in resp.json().get("results", {}).items():
            data = result.get("data", {})
            if "error" not in data:
                out[asin] = {"product": data}
        return out
