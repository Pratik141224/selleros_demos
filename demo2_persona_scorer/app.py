"""
demo2_persona_scorer/app.py

Flask application for the Buyer Persona & Intent Match Scorer demo.
Run: python app.py
Open: http://localhost:5001
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from agents import run_persona_analysis

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyse", methods=["POST"])
def analyse():
    """
    POST /api/analyse
    Body (JSON):
      {
        "title":       "product title string",
        "description": "bullets or description text",
        "category":    "electronics_audio" | "fashion_men" | ...,
        "platform":    "amazon" | "flipkart" | "myntra" | "meesho",
        "price":       "₹1,499"   (optional)
      }
    Returns full persona analysis JSON.
    """
    data = request.get_json(force=True)

    title       = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    category    = data.get("category", "electronics_audio")
    platform    = data.get("platform", "amazon")
    price       = (data.get("price") or "").strip()

    # Basic validation
    if not title:
        return jsonify({"error": "Product title is required."}), 400
    if len(description) < 20:
        return jsonify({"error": "Please provide at least a short description (20+ chars)."}), 400

    try:
        result = run_persona_analysis(
            title=title,
            description=description,
            category=category,
            platform=platform,
            price=price,
        )
        return jsonify(result)

    except EnvironmentError as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": f"AI response parsing failed: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


if __name__ == "__main__":
    print("=" * 55)
    print("  SellerOS — Buyer Persona & Intent Match Scorer")
    print("  http://localhost:5001")
    print("=" * 55)
    app.run(debug=True, port=5001)
