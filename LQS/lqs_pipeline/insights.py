"""
STEP 6 — GENERATE INSIGHTS
==========================
Produces gap report, RPI simulation, seller feedback, and optional chart.
Returns a structured dict suitable for JSON serialization (frontend-ready).
"""
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
from loguru import logger


def gap_report(df: pd.DataFrame) -> dict:
    t    = df.loc["TARGET"]
    best = df.drop("TARGET").loc[df.drop("TARGET")["rpi"].idxmax()]
    metrics = ["lqs", "ctr", "cvr", "rpi", "rating", "reviews"]
    return {
        "target_summary"  : {"title": t["title"], "lqs": float(t["lqs"]),
                              "grade": t["grade"], "rpi": float(t["rpi"])},
        "best_competitor" : {"title": best["title"], "lqs": float(best["lqs"]),
                              "grade": best["grade"], "rpi": float(best["rpi"])},
        "gaps": [
            {"metric": m, "target": float(t[m]), "best": float(best[m]),
             "gap": float(best[m] - t[m])}
            for m in metrics
        ],
    }


def rpi_simulation(df: pd.DataFrame) -> list[dict]:
    t    = df.loc["TARGET"]
    best = df.drop("TARGET").loc[df.drop("TARGET")["rpi"].idxmax()]
    scenarios = []
    for label, c_mul, v_mul in [
        ("Current", 1.0, 1.0), ("CTR +10 %", 1.1, 1.0), ("CVR +10 %", 1.0, 1.1),
        ("Both +10 %", 1.1, 1.1), ("Both +25 %", 1.25, 1.25),
    ]:
        cs = min(t["ctr"] * c_mul, 1.0); vs = min(t["cvr"] * v_mul, 1.0)
        rpi = t["price"] * cs * vs
        delta = ((rpi - best["rpi"]) / best["rpi"] * 100) if best["rpi"] else 0
        scenarios.append({"scenario": label, "ctr": cs, "cvr": vs,
                           "rpi": round(rpi, 2), "vs_best_pct": round(delta, 1)})
    return scenarios


def seller_feedback(df: pd.DataFrame, source: str) -> dict:
    t    = df.loc["TARGET"]
    best = df.drop("TARGET").loc[df.drop("TARGET")["rpi"].idxmax()]
    peer_reviews_avg = df.drop("TARGET")["reviews"].mean()

    health, strengths, quick, mid, longt = [], [], [], [], []

    # Health
    if t["lqs"]      < 70: health.append(("CRITICAL", f"LQS={t['lqs']} ({t['grade']}) — weak content."))
    elif t["lqs"]    < 80: health.append(("WARNING",  f"LQS={t['lqs']} ({t['grade']}) — room to improve."))
    else:                  health.append(("HEALTHY",  f"LQS={t['lqs']} ({t['grade']}) — strong baseline."))
    if t["rating"]   < 4.0: health.append(("CRITICAL", f"Rating {t['rating']}★ below trust floor."))
    if t["reviews"]  < 50:  health.append(("CRITICAL", f"Only {int(t['reviews'])} reviews."))
    if t["rpi"] < best["rpi"] * 0.5:
        health.append(("CRITICAL", f"RPI ₹{t['rpi']:.1f} is <50 % of leader (₹{best['rpi']:.1f})."))

    # Strengths
    if t["discount"] > 20:
        strengths.append(f"Strong discount ({t['discount']:.1f} %).")
    if t["ctr"] > best["ctr"]:
        strengths.append("CTR beats leader — clicks aren't the problem.")
    if t["cvr"] > best["cvr"]:
        strengths.append("CVR beats leader — conversion isn't the problem.")
    if not strengths:
        strengths.append("No major strengths — focus on quick wins.")

    # Actions
    if t["discount"] < 10:  quick.append("Apply a coupon/discount of 10 %+")
    if t["reviews"] < 30 and peer_reviews_avg > 100:
        quick.append("Enroll in Amazon Vine for 10-30 verified reviews")
    if t["ctr"] < 0.4:      quick.append("Refresh main image (white BG, 85 % fill)")

    if t["lqs"] < 80:
        mid += ["Rewrite title (brand + model + 3 specs)",
                "Add all 5 bullets — benefit-led copy",
                "Upload 7-9 images"]
    if t["cvr"] < best["cvr"]:
        mid.append("Enable Prime (FBA or SFP)")

    if t["lqs"] < 85:    longt += ["Build A+ content", "Add product video"]
    if t["reviews"] < 500: longt.append("Drive to 500+ reviews via Request Review")
    if t["ctr"] < best["ctr"] * 0.7:
        longt.append("Sponsored Products at top-of-search")

    # Priority ranking (impact × ease)
    candidates = [
        ("Improve main image",        0.05, 0.00, 5),
        ("Apply 10%+ discount",       0.10, 0.10, 5),
        ("Rewrite title + bullets",   0.03, 0.03, 4),
        ("Reach 4.0★ rating",         0.08, 0.10, 3),
        ("Reach 200+ reviews",        0.05, 0.08, 2),
        ("Enable Prime",              0.10, 0.15, 3),
        ("Add A+ content",            0.00, 0.13, 3),
        ("Add product video",         0.00, 0.20, 2),
    ]
    base = t["price"] * t["ctr"] * t["cvr"]
    priorities = []
    for label, dc, dv, ease in candidates:
        nc = min(t["ctr"] + dc, 1.0); nv = min(t["cvr"] + dv, 1.0)
        lift = t["price"] * nc * nv - base
        priorities.append({"action": label, "rpi_lift": round(lift, 1),
                            "ease": ease, "priority": round(lift * ease / 5, 1)})
    priorities.sort(key=lambda x: x["priority"], reverse=True)

    return {
        "asin"           : t["asin"],
        "position"       : source,
        "health"         : [{"level": l, "msg": m} for l, m in health],
        "strengths"      : strengths,
        "quick_wins"     : quick,
        "medium_term"    : mid,
        "long_term"      : longt,
        "priority_actions": priorities,
        "executive_summary": {
            "gap_to_leader"   : round(float(best["rpi"] - t["rpi"]), 1),
            "best_competitor" : best["rpi"],
            "top_action"      : priorities[0]["action"],
            "top_action_lift" : priorities[0]["rpi_lift"],
            "top3_combined"   : round(sum(p["rpi_lift"] for p in priorities[:3]), 1),
        },
    }


def plot_comparison(df: pd.DataFrame, source: str,
                     save_path: Optional[str] = "competitor_analysis.png") -> str:
    colors = ["#e74c3c"] + ["#3498db"] * (len(df) - 1)
    labels = list(df.index)

    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.suptitle(f"Competitor Analysis — {source} (red) vs Page-1 (blue)",
                 fontsize=13, fontweight="bold")

    ax = axes[0, 0]
    bars = ax.bar(labels, df["rpi"], color=colors, edgecolor="white")
    ax.set_title("RPI = Price × CTR × CVR")
    ax.set_xticklabels(labels, rotation=20, ha="right")
    for b, v in zip(bars, df["rpi"]):
        ax.text(b.get_x()+b.get_width()/2, b.get_height()+0.3,
                f"{v:.1f}", ha="center", fontsize=8, fontweight="bold")

    ax = axes[0, 1]
    gc = {"A":"#27ae60","B":"#f39c12","C":"#e74c3c"}
    bars = ax.bar(labels, df["lqs"],
                  color=[gc.get(g,"#95a5a6") for g in df["grade"]], edgecolor="white")
    ax.set_title("LQS"); ax.set_ylim(60, 100)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    for b, v, g in zip(bars, df["lqs"], df["grade"]):
        ax.text(b.get_x()+b.get_width()/2, b.get_height()+0.3,
                f"{v:.1f} ({g})", ha="center", fontsize=8, fontweight="bold")

    ax = axes[1, 0]
    for i,(lbl,row) in enumerate(df.iterrows()):
        ax.scatter(row["ctr"], row["cvr"],
                   s=max(row["reviews"]**0.4, 30)*8, c=colors[i],
                   alpha=0.75, edgecolors="white", linewidth=1.2, zorder=3)
        ax.annotate(lbl,(row["ctr"],row["cvr"]),
                    textcoords="offset points",xytext=(5,5),fontsize=8)
    ax.set_xlabel("CTR"); ax.set_ylabel("CVR")
    ax.set_title("CTR vs CVR"); ax.grid(True, alpha=0.3)

    ax = axes[1, 1]
    for i,(lbl,row) in enumerate(df.iterrows()):
        ax.scatter(row["price"], row["rpi"], c=colors[i], s=100,
                   alpha=0.8, edgecolors="white", linewidth=1.2, zorder=3)
        ax.annotate(lbl,(row["price"],row["rpi"]),
                    textcoords="offset points",xytext=(5,5),fontsize=8)
    ax.set_xlabel("Price (₹)"); ax.set_ylabel("RPI")
    ax.set_title("Price vs RPI"); ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Chart saved → {}", save_path)
    return save_path


def generate_insights(df: pd.DataFrame, source: str,
                       make_chart: bool = True) -> dict:
    """Single entrypoint for all insights. Returns frontend-ready dict."""
    logger.debug("generate_insights: source={!r} make_chart={} products={}", source, make_chart, len(df))
    insights = {
        "scores"        : df.to_dict("index"),
        "gap_report"    : gap_report(df),
        "rpi_simulation": rpi_simulation(df),
        "feedback"      : seller_feedback(df, source),
    }
    if make_chart:
        insights["chart_path"] = plot_comparison(df, source)
    return insights