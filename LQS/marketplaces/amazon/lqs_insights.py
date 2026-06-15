"""
marketplaces/amazon/lqs_insights.py

Generates insights from Amazon marketplace LQS scores.
Mirrors the structure of insights.py (gap_report, simulation, feedback)
but is based on a9_compliance / rufus_readiness / overall rather than
the ML pipeline's lqs / ctr / cvr / rpi.
"""
from __future__ import annotations

_CRITICAL_FLAGS = {
    "CRITICAL_KW_MISS",
    "BROWSE_NODE_MISSING",
    "BACKEND_OVER_BYTE_LIMIT",
}
_HIGH_FLAGS = {
    "TITLE_TOO_LONG",
    "TOO_FEW_BULLETS",
    "MOBILE_KEYWORD_MISSING",
    "ONLY_FEATURE_LISTING",
    "NO_FAQ_COVERAGE",
}

# ── helpers ────────────────────────────────────────────────────────────────────

def _target(results: list[dict]) -> dict:
    return next(r for r in results if r["label"] == "TARGET")


def _competitors(results: list[dict]) -> list[dict]:
    return [r for r in results if r["label"] != "TARGET"]


def _best_competitor(results: list[dict]) -> dict | None:
    comps = _competitors(results)
    if not comps:
        return None
    return max(comps, key=lambda r: r["scores"]["overall"])


# ── gap report ─────────────────────────────────────────────────────────────────

def gap_report(results: list[dict]) -> dict:
    t = _target(results)
    best = _best_competitor(results)

    metrics = ["overall", "a9_compliance", "rufus_readiness", "lqs_score"]
    gaps = []
    for m in metrics:
        t_val   = t["scores"].get(m, 0)
        b_val   = best["scores"].get(m, 0) if best else t_val
        gaps.append({
            "metric": m,
            "target": t_val,
            "best":   b_val,
            "gap":    b_val - t_val,
        })

    return {
        "target_summary": {
            "title":   t["title"],
            "asin":    t["asin"],
            "overall": t["scores"]["overall"],
            "a9":      t["scores"]["a9_compliance"],
            "rufus":   t["scores"]["rufus_readiness"],
            "flags":   [f for f in t["flags"] if f.split(":")[0] in _CRITICAL_FLAGS | _HIGH_FLAGS],
        },
        "best_competitor": {
            "title":   best["title"]   if best else None,
            "asin":    best["asin"]    if best else None,
            "overall": best["scores"]["overall"]        if best else None,
            "a9":      best["scores"]["a9_compliance"]  if best else None,
            "rufus":   best["scores"]["rufus_readiness"] if best else None,
        },
        "gaps": gaps,
    }


# ── score comparison table ─────────────────────────────────────────────────────

def score_comparison(results: list[dict]) -> list[dict]:
    """Flat table — one row per product (target + competitors)."""
    return [
        {
            "label":           r["label"],
            "asin":            r["asin"],
            "title":           r["title"][:80],
            "overall":         r["scores"]["overall"],
            "a9_compliance":   r["scores"]["a9_compliance"],
            "rufus_readiness": r["scores"]["rufus_readiness"],
            "lqs_score":       r["scores"]["lqs_score"],
            "projected_ctr":   r["projected_ctr_range"],
            "gmv_estimate":    r["gmv_impact_inr"],
            "critical_flags":  [f for f in r["flags"] if f.split(":")[0] in _CRITICAL_FLAGS],
        }
        for r in results
    ]


# ── dimension weakness analysis ────────────────────────────────────────────────

def dimension_gaps(results: list[dict]) -> list[dict]:
    """
    For each A9 and Rufus dimension, compare TARGET vs the competitor average.
    Returns dimensions sorted by gap (worst first).
    """
    t     = _target(results)
    comps = _competitors(results)
    if not comps:
        return []

    gaps: list[dict] = []

    for scorer in ("a9", "rufus"):
        t_breakdown = t.get("dimension_breakdown", {}).get(scorer, {})
        for dim, t_score in t_breakdown.items():
            comp_scores = [
                c.get("dimension_breakdown", {}).get(scorer, {}).get(dim, 0)
                for c in comps
            ]
            avg_comp = sum(comp_scores) / len(comp_scores)
            gaps.append({
                "scorer":       scorer,
                "dimension":    dim,
                "target_score": t_score,
                "comp_avg":     round(avg_comp, 1),
                "gap":          round(avg_comp - t_score, 1),
            })

    gaps.sort(key=lambda x: x["gap"], reverse=True)
    return gaps


# ── seller feedback ────────────────────────────────────────────────────────────

def seller_feedback(results: list[dict]) -> dict:
    t     = _target(results)
    best  = _best_competitor(results)
    flags = set(f.split(":")[0] for f in t["flags"])

    # Health
    health: list[dict] = []
    critical_hits = flags & _CRITICAL_FLAGS
    high_hits     = flags & _HIGH_FLAGS

    if critical_hits:
        health.append({
            "level": "CRITICAL",
            "msg":   f"Listing has {len(critical_hits)} critical issue(s) blocking indexation: "
                     f"{', '.join(sorted(critical_hits))}",
        })
    if high_hits:
        health.append({
            "level": "WARNING",
            "msg":   f"{len(high_hits)} high-priority issue(s) need fixing before publish: "
                     f"{', '.join(sorted(high_hits))}",
        })
    if not critical_hits and not high_hits:
        overall = t["scores"]["overall"]
        if overall >= 75:
            health.append({"level": "HEALTHY", "msg": f"No blocking issues. Overall score {overall}/100."})
        else:
            health.append({"level": "WARNING", "msg": f"No critical flags but overall score is low ({overall}/100). Review medium-priority items."})

    # Strengths
    strengths: list[str] = []
    t_bd = t.get("dimension_breakdown", {})
    for scorer_key in ("a9", "rufus"):
        for dim, score in t_bd.get(scorer_key, {}).items():
            if score >= 80:
                strengths.append(f"Strong {scorer_key.upper()} {dim.replace('_', ' ')} ({score}/100).")

    if best and t["scores"]["a9_compliance"] > best["scores"]["a9_compliance"]:
        strengths.append("A9 compliance beats the best competitor.")
    if best and t["scores"]["rufus_readiness"] > best["scores"]["rufus_readiness"]:
        strengths.append("Rufus readiness beats the best competitor.")
    if not strengths:
        strengths.append("No dimensions scoring above 80 — broad improvement needed.")

    # Quick wins: high-impact critical/high flag fixes already in fix_priority
    fix_pri = t.get("fix_priority", [])
    quick_wins = [
        f["fix_suggestion"]
        for f in fix_pri
        if f.get("impact_score", 0) >= 60
    ][:3]

    # Medium term: rufus dimensions below 60
    rufus_bd = t_bd.get("rufus", {})
    medium_term: list[str] = []
    rufus_dim_labels = {
        "intent_coverage":            "Rewrite bullets to answer the 5 canonical Rufus buyer questions.",
        "use_case_specificity":       "Replace demographic language with concrete use-case situations in each bullet.",
        "objection_handling":         "Add durability specs and compatibility notes to pre-empt known return reasons.",
        "persona_clarity":            "Make at least one buyer persona identifiable by situation, not demographics.",
        "faq_readiness":              "Add Q&A pairs that answer use-case, compatibility, and durability questions conversationally.",
        "semantic_depth":             "Add activity/occasion context (e.g. 'for the monsoon commute') and related concepts beyond direct keywords.",
        "conversational_naturalness": "Remove exclamation marks and banned openers; add two contractions.",
        "review_alignment":           "Ensure listing claims don't contradict top review themes.",
    }
    for dim, label in rufus_dim_labels.items():
        if rufus_bd.get(dim, 100) < 60:
            medium_term.append(label)

    # Medium term: A9 structural issues not already in quick wins
    a9_bd = t_bd.get("a9", {})
    if a9_bd.get("backend_keywords", 10) < 5:
        medium_term.append("Expand backend search terms to fill all 249 bytes with non-duplicate terms.")
    if a9_bd.get("attribute_completeness", 3) < 2:
        medium_term.append("Populate structured product attributes (colour, size, model) in Seller Central.")
    if a9_bd.get("content_richness", 2) < 1:
        medium_term.append("Add a product description of at least 100 characters.")

    # Long term
    long_term: list[str] = []
    if a9_bd.get("content_richness", 2) < 2:
        long_term.append("Build A+ content — adds up to +1 pt on Content Richness and boosts Rufus context.")
    if not t.get("dimension_breakdown", {}).get("rufus", {}).get("faq_readiness"):
        long_term.append("Build a Q&A section with conversationally-phrased questions and detailed answers.")
    if best and t["scores"]["overall"] < best["scores"]["overall"] - 10:
        long_term.append(
            f"Target overall score >{best['scores']['overall']} to match the category leader "
            f"(current gap: {best['scores']['overall'] - t['scores']['overall']} pts)."
        )

    # Priority fixes — from the scorer's fix_priority (already impact-ranked)
    priority_fixes = fix_pri[:5]

    # Executive summary
    overall_gap = (best["scores"]["overall"] - t["scores"]["overall"]) if best else 0
    exec_summary = {
        "overall_gap_to_leader": overall_gap,
        "a9_gap_to_leader":      (best["scores"]["a9_compliance"] - t["scores"]["a9_compliance"]) if best else 0,
        "rufus_gap_to_leader":   (best["scores"]["rufus_readiness"] - t["scores"]["rufus_readiness"]) if best else 0,
        "top_fix":               priority_fixes[0]["fix_suggestion"] if priority_fixes else "No critical issues.",
        "critical_flag_count":   len(critical_hits),
        "high_flag_count":       len(high_hits),
    }

    return {
        "asin":             t["asin"],
        "health":           health,
        "strengths":        strengths,
        "quick_wins":       quick_wins,
        "medium_term":      medium_term,
        "long_term":        long_term,
        "priority_fixes":   priority_fixes,
        "executive_summary": exec_summary,
    }


# ── public entrypoint ──────────────────────────────────────────────────────────

def generate_marketplace_insights(results: list[dict]) -> dict:
    """
    Single entrypoint. Takes the list of scored products (target + competitors)
    and returns a frontend-ready insights dict.

    results item schema:
        {label, asin, title, scores, dimension_breakdown, flags, fix_priority,
         projected_ctr_range, gmv_impact_inr}
    """
    return {
        "gap_report":       gap_report(results),
        "score_comparison": score_comparison(results),
        "dimension_gaps":   dimension_gaps(results),
        "feedback":         seller_feedback(results),
    }
