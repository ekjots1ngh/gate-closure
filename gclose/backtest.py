"""Walk-forward scoring of the P(short) forecasts.

Each test month, every model is refitted on all data before that month and scored on the
month itself. The holdout (July to October 2026) is never touched here.

Run: python -m gclose.backtest   ->  data/out/walkforward.parquet and the Brier table.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from . import stats
from .features import build
from .models import LADDER

OUT = Path(__file__).resolve().parent.parent / "data" / "out"

TRAIN_END = pd.Timestamp("2026-07-01", tz="UTC")   # first holdout instant; nothing at or after it is used
FIRST_TEST, LAST_TEST = "2022-07", "2026-06"      # PROTOCOL.md amendment 1


def load_features(rebuild: bool = False) -> pd.DataFrame:
    """The cached feature table, rebuilt from data/raw if missing or asked to."""
    cache = OUT / "features.parquet"
    if cache.exists() and not rebuild:
        return pd.read_parquet(cache)
    from .ingest import load
    f = build(load("prices"), load("WINDFOR"), load("NDF"), load("IMBALNGC"))
    OUT.mkdir(parents=True, exist_ok=True)
    f.to_parquet(cache, index=False)
    return f


def test_months(f: pd.DataFrame) -> Iterator[tuple[str, pd.Series, pd.Series]]:
    """(month, train mask, test mask) for each walk-forward month, oldest first."""
    for m in pd.period_range(FIRST_TEST, LAST_TEST, freq="M"):
        t0 = m.start_time.tz_localize("UTC")
        t1 = (m + 1).start_time.tz_localize("UTC")
        yield str(m), f["start_time"] < t0, (f["start_time"] >= t0) & (f["start_time"] < t1)


def walk_forward(f: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample P(short) from every model in the ladder, for every test month."""
    f = f[f["start_time"] < TRAIN_END]
    blocks = []
    for _, train, test in test_months(f):
        block = f.loc[test, ["start_time", "short", "ssp"]].copy()
        for name, model in LADDER.items():
            block[f"p_{name}"] = model().fit(f[train]).predict_proba(f[test])
        blocks.append(block)
    return pd.concat(blocks, ignore_index=True)


def brier_table(preds: pd.DataFrame) -> pd.DataFrame:
    """Brier score per model with a 90% week-block bootstrap interval."""
    y = preds["short"].to_numpy()
    names = list(LADDER)
    sq_err = np.column_stack([(preds[f"p_{n}"].to_numpy() - y) ** 2 for n in names])
    boot = stats.resampled_means(sq_err, stats.week_index(preds["start_time"]))
    rows = []
    for j, name in enumerate(names):
        lo, hi = stats.interval(boot[:, j])
        rows.append({"model": name, "brier": round(sq_err[:, j].mean(), 4), "lo": round(lo, 4), "hi": round(hi, 4)})
    return pd.DataFrame(rows)


def main() -> None:
    preds = walk_forward(load_features())
    preds.to_parquet(OUT / "walkforward.parquet", index=False)
    print(f"walk-forward {FIRST_TEST} to {LAST_TEST}, {len(preds):,} half hours")
    print(brier_table(preds).to_string(index=False))


if __name__ == "__main__":
    main()
