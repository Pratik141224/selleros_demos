"""
demo1_abd_optimizer/app.py

Flask application for the Title, Bullet & Description ABD Optimizer demo.
Run: python app.py
Open: http://localhost:5004
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from agents import run_ab_optimization
from omkar_client import fetch_own_listing, fetch_competitor_summaries
from shared.s3_cache import get as cache_get, put as cache_put
from integration_bridge import get_lqs_scores, get_missing_keywords

app = Flask(__name__)
CORS(app)

_TE_PREFIX = os.getenv("S3_RAW_PREFIX_TE", "TextEnhancement")


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
        "competitors": [
            {"asin": str, "title": str, "bullets": list[str], "description": str},
            ...   (up to 5)
        ]
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


@app.route("/api/optimize", methods=["POST"])
def optimize():
    """
    POST /api/optimize
    Body (JSON):
      {
        "title":       "current product title",     (required)
        "bullets":     ["bullet 1", ...],           (required, 1–5)
        "description": "current description",       (optional)
        "category":    "electronics" | "fashion" | ..., (optional, or raw category name)
        "competitor_context": [                     (optional, from /api/fetch-listing)
            {"asin": str, "title": str, "bullets": [...], "description": str},
            ...
        ]
        "asin":          str,   (optional, enables S3 caching keyed by ASIN)
        "force_refresh": bool,  (optional, default false — bypass cache when true)
      }
    Returns full ABD optimization JSON.
    """
    data = request.get_json(force=True)

    asin          = (data.get("asin") or "").strip().upper()
    force_refresh = bool(data.get("force_refresh", False))

    # ── S3 cache check ─────────────────────────────────────────────────────────
    if asin and not force_refresh:
        cached = cache_get(_TE_PREFIX, asin)
        if cached:
            return jsonify({**cached, "cached": True})

    title       = (data.get("title") or "").strip()
    bullets     = [b.strip() for b in (data.get("bullets") or []) if b and b.strip()]
    description = (data.get("description") or "").strip()
    category    = data.get("category", "electronics")
    competitor_context = data.get("competitor_context") or []

    if not title:
        return jsonify({"error": "Product title is required."}), 400
    if not bullets:
        return jsonify({"error": "At least one bullet point is required."}), 400

    try:
        # Pre-fetch LQS and keyword gap data via direct function calls (no HTTP)
        lqs_context      = get_lqs_scores(title, bullets, description, category)
        missing_keywords = get_missing_keywords(
            title, bullets, description, competitor_context or [], category,
            asin=asin,
        )

        result = run_ab_optimization(
            title=title,
            bullets=bullets,
            description=description,
            category=category,
            competitor_context=competitor_context if competitor_context else None,
            lqs_context=lqs_context or None,
            missing_keywords=missing_keywords or None,
        )

        # ── S3 cache write ──────────────────────────────────────────────────────
        if asin:
            cache_put(_TE_PREFIX, asin, result)

        return jsonify({
            **result,
            "cached": False,
            "integration": {
                "lqs_scores_used":     bool(lqs_context),
                "keyword_gap_used":    bool(missing_keywords),
                "keywords_injected":   len(missing_keywords),
            },
        })

    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("  SellerOS — Title, Bullet and Description ABD Optimizer")
    print("  http://localhost:5004")
    print("=" * 55)
    app.run(debug=True, port=5004)
