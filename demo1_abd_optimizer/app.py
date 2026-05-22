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

app = Flask(__name__)
CORS(app)


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
            leaf_category_id=listing["leaf_category_id"],
            own_asin=listing["asin"],
            n=5,
            max_pages=5,
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
      }
    Returns full ABD optimization JSON.
    """
    data = request.get_json(force=True)

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
        result = run_ab_optimization(
            title=title,
            bullets=bullets,
            description=description,
            category=category,
            competitor_context=competitor_context if competitor_context else None,
        )
        return jsonify(result)

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
