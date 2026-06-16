"""
keyword_gap/app.py

Flask application for the Keyword Gap Analyzer demo.
Run: python app.py
Open: http://localhost:5002
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from agents import run_keyword_gap_analysis
from omkar_client import fetch_own_listing, fetch_competitor_summaries
from shared.s3_cache import get as cache_get, put as cache_put

app = Flask(__name__)
CORS(app)

_KG_PREFIX = os.getenv("S3_RAW_PREFIX_KG", "KeywordGap")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch-listing", methods=["POST"])
def fetch_listing():
    """
    POST /api/fetch-listing
    Body: { "asin": "<ASIN or Amazon product URL>" }

    Returns:
    {
        "asin": str,
        "title": str,
        "bullets": list[str],
        "description": str,
        "leaf_category_id": str,
        "leaf_category_name": str,
        "competitors": [{"asin", "title", "bullets", "description"}, ...]
    }
    """
    data = request.get_json(force=True)
    asin_input = (data.get("asin") or "").strip()

    if not asin_input:
        return jsonify({"error": "ASIN or Amazon product URL is required."}), 400

    try:
        listing = fetch_own_listing(asin_input)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Failed to fetch product listing: {e}"}), 500

    try:
        competitors = fetch_competitor_summaries(
            seed_asin=listing["asin"],
            n=5,
        )
    except Exception:
        competitors = []

    return jsonify({**listing, "competitors": competitors})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    POST /api/analyze
    Body (JSON):
      {
        "title":             str,           (required)
        "bullets":           list[str],     (required, 1–5)
        "description":       str,           (optional)
        "backend_keywords":  str,           (optional, current backend string)
        "category":          str,           (optional, dropdown key or raw category name)
        "competitor_context": list[dict],   (optional, from /api/fetch-listing)
        "ppc_search_terms":  list[str],     (optional, converting terms from ad reports)
        "target_locale":     str,           (optional, default "IN")
        "asin":              str,           (optional, enables S3 caching keyed by ASIN)
        "force_refresh":     bool,          (optional, default false — bypass cache when true)
      }
    Returns full keyword gap analysis JSON.
    """
    data = request.get_json(force=True)

    asin          = (data.get("asin") or "").strip().upper()
    force_refresh = bool(data.get("force_refresh", False))

    # ── S3 cache check ─────────────────────────────────────────────────────────
    if asin and not force_refresh:
        cached = cache_get(_KG_PREFIX, asin)
        if cached:
            return jsonify({**cached, "cached": True})

    title              = (data.get("title") or "").strip()
    bullets            = [b.strip() for b in (data.get("bullets") or []) if b and b.strip()]
    description        = (data.get("description") or "").strip()
    backend_keywords   = (data.get("backend_keywords") or "").strip()
    category           = data.get("category", "custom")
    leaf_category_name = (data.get("leaf_category_name") or "").strip()
    competitor_context = data.get("competitor_context") or []

    # Resolve the actual product category so the LLM is never mislabelled.
    # Priority order:
    #   1. leaf_category_name forwarded from /api/fetch-listing  → 0 extra Zyte calls
    #   2. ASIN Zyte lookup (cache-hit only — fetch-listing ran first)  → 1 fast call
    #   3. Explicit category key from client (e.g. "fashion", "kitchen")
    #   4. "custom" default → "General consumer product" (safe fallback)
    if leaf_category_name and category in ("electronics", "custom", ""):
        category = leaf_category_name
    elif asin and category in ("electronics", "custom", ""):
        try:
            from shared.zyte_client import fetch_own_listing as _fetch_listing
            _leaf = (_fetch_listing(asin) or {}).get("leaf_category_name", "")
            if _leaf:
                category = _leaf
        except Exception:
            pass  # keep default — never block the analysis on a category lookup
    ppc_search_terms = [t.strip() for t in (data.get("ppc_search_terms") or []) if t and t.strip()]
    target_locale    = (data.get("target_locale") or "IN").strip().upper()

    if not title:
        return jsonify({"error": "Product title is required."}), 400
    if not bullets:
        return jsonify({"error": "At least one bullet point is required."}), 400

    try:
        result = run_keyword_gap_analysis(
            title=title,
            bullets=bullets,
            description=description,
            backend_keywords=backend_keywords,
            competitors=competitor_context if competitor_context else None,
            category=category,
            ppc_search_terms=ppc_search_terms if ppc_search_terms else None,
            target_locale=target_locale,
            asin=asin,
        )

        # ── S3 cache write ──────────────────────────────────────────────────────
        if asin:
            cache_put(_KG_PREFIX, asin, result)

        return jsonify({**result, "cached": False})

    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("  SellerOS — Keyword Gap Analyzer")
    print("  http://localhost:5002")
    print("=" * 55)
    app.run(debug=True, port=5002)
