"""Build the gate-safe feature table from data/raw and cache it at data/out/features.parquet."""

import time
from pathlib import Path

from gclose.backtest import load_features
from gclose.features import FEATURES

t0 = time.time()
out = Path(__file__).resolve().parent.parent / "data" / "out"
out.mkdir(parents=True, exist_ok=True)
f = load_features()
f.to_parquet(out / "features.parquet", index=False)
print(f"{len(f):,} rows in {time.time() - t0:.0f}s")
print("share missing per feature:")
print(f[FEATURES].isna().mean().round(3).to_string())
