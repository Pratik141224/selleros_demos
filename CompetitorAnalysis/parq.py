import pandas as pd

df = pd.read_parquet(
    "data/output/B0021GBNPC/20260607_005556.parquet"
)

df.to_csv(
    "competitors.csv",
    index=False
)