"""Rebuild the gate-safe feature table from data/raw into data/out/features.parquet.

Run from the repo root: python scripts/build_features.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gclose.backtest import load_features  # noqa: E402
from gclose.features import FEATURES  # noqa: E402

t0 = time.time()
f = load_features(rebuild=True)
print(f"{len(f):,} rows in {time.time() - t0:.0f}s")
print("share missing per feature:")
print(f[FEATURES].isna().mean().round(3).to_string())
