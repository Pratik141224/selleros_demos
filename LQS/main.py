"""
 CLI — runs all 6 pipeline steps end-to-end.

Usage:
    python main.py --mode asin  --asin  B0G2MM7VH9  --comp-query "laptop under 50000"
    python main.py --mode url   --url   "https://www.amazon.in/dp/B0G2MM7VH9"
    python main.py --mode query --query "laptop under 50000"
"""
import argparse
import json
import logging
from pprint import pprint

from lqs_pipeline.Ingestion  import ingest
from lqs_pipeline.Extraction import extract_all
from lqs_pipeline.QC         import run_qc
from lqs_pipeline.features   import build_all_features
from lqs_pipeline.pipeline   import run_pipeline
from lqs_pipeline.insights   import generate_insights

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
    datefmt="%H:%M:%S",
)


def run(mode: str, **kwargs) -> dict:
    """Run all 6 steps. Each step's output is the next step's input."""
    print(">>> STEP 1: INGESTION")
    ingested = ingest(mode, **kwargs)

    print(">>> STEP 2: EXTRACTION")
    extracted = extract_all(ingested)

    print(">>> STEP 3: QC")
    qc_data = run_qc(extracted)

    print(">>> STEP 4: FEATURES")
    feat_data = build_all_features(qc_data)

    print(">>> STEP 5: MODEL PIPELINE")
    df = run_pipeline(feat_data)
    print("\nSCORES")
    print(df[["title","price","rating","reviews","lqs","grade","ctr","cvr","rpi"]].to_string())

    print("\n>>> STEP 6: INSIGHTS")
    insights = generate_insights(df, extracted["source"])

    print("\nGAP REPORT");        pprint(insights["gap_report"])
    print("\nRPI SIMULATION");    pprint(insights["rpi_simulation"])
    print("\nSELLER FEEDBACK");   pprint(insights["feedback"])
    print(f"\nChart saved: {insights.get('chart_path')}")

    # Save full output as JSON (frontend can consume this directly)
    out = {"scores": df.to_dict("index"), **insights}
    with open("output.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print("\n✓ Full output saved to output.json")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["asin","url","query"], required=True)
    p.add_argument("--asin")
    p.add_argument("--url")
    p.add_argument("--query")
    p.add_argument("--comp-query")
    args = p.parse_args()

    kwargs = {k: v for k, v in vars(args).items() if v and k != "mode"}
    if "comp_query" in kwargs:
        kwargs["comp_query"] = kwargs.pop("comp_query")
    run(args.mode, **kwargs)


if __name__ == "__main__":
    main()