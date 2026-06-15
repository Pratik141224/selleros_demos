import json
from datetime import datetime

import pandas as pd

from src.utils.s3_client import get_s3


def _parquet_key(seed_asin):
    return f"output/{seed_asin}/competitors.parquet"


def save_competitors_parquet(seed_asin, competitors):

    s3 = get_s3()
    key = _parquet_key(seed_asin)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    rows = [
        {
            "run_timestamp": timestamp,
            "seed_asin": seed_asin,
            "competitor_asin": p.get("asin"),
            "title": p.get("title"),
            "brand": p.get("brand"),
            "price": p.get("price"),
            "rating": p.get("rating"),
            "review_count": p.get("review_count"),
            "deep_score": p.get("deep_score"),
            "product_url": p.get("product_url"),
            "main_image": p.get("main_image"),
            "all_images": json.dumps(p.get("images", [])),
            "description": p.get("description", ""),
            "bullet_points": json.dumps(p.get("bullet_points", []))
        }
        for p in competitors
    ]

    new_df = pd.DataFrame(rows)

    existing_df = s3.get_parquet(key)

    if existing_df is not None:
        combined_df = pd.concat(
            [existing_df, new_df],
            ignore_index=True
        )
    else:
        combined_df = new_df

    s3.put_parquet(key, combined_df)

    print(f"\nPARQUET SAVED: s3://{s3.bucket}/{s3._key(key)}")
    print(f"TOTAL ROWS: {len(combined_df)} (+{len(new_df)} new)")
