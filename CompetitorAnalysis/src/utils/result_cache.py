from datetime import datetime, timedelta

from src.utils.s3_client import get_s3

CACHE_DAYS = 14


def load_cached_results(seed_asin):

    s3 = get_s3()
    key = f"output/{seed_asin}/competitors.parquet"

    df = s3.get_parquet(key)

    if df is None or df.empty:
        return None

    latest_ts = df["run_timestamp"].max()

    run_time = datetime.strptime(
        latest_ts,
        "%Y%m%d_%H%M%S"
    )

    age = datetime.now() - run_time

    if age > timedelta(days=CACHE_DAYS):
        return None

    latest_run_df = df[
        df["run_timestamp"] == latest_ts
    ]

    print(f"\nCACHE HIT: s3://{s3.bucket}/{s3._key(key)}")
    print(f"Run timestamp: {latest_ts} (age: {age.days}d)")

    return latest_run_df
