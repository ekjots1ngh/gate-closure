"""Walk-forward evaluation with week-block bootstrap intervals.

Run: python -m gclose.backtest
Reads data/raw/*.parquet, writes data/out/walkforward.csv and prints the headline table.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import battery
from .features import FEATURES, build
from .models import LADDER, brier

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT = Path(__file__).resolve().parent.parent / "data" / "out"
OUT.mkdir(parents=True, exist_ok=True)

TRAIN_END = pd.Timestamp("2026-06-30 23:59", tz="UTC")   # holdout starts after this; opened once


MIN_TRAIN_MONTHS = 6   # first test month = earliest month pulled + this many


def load_features() -> pd.DataFrame:
    from .ingest import load
    return build(load("prices"), load("WINDFOR"), load("NDF"), load("IMBALNGC"))


def walk_forward(f: pd.DataFrame, first_test: str | None = None, last_test="2026-06") -> pd.DataFrame:
    """Retrain each month on everything before it, predict that month, for every model."""
    f = f[f["start_time"] <= TRAIN_END]
    if first_test is None:
        first = f["start_time"].min().tz_convert("UTC").tz_localize(None).to_period("M") + MIN_TRAIN_MONTHS
        first_test = str(first)
    print(f"walk-forward: train from {f['start_time'].min():%Y-%m}, test {first_test} to {last_test}")
    months = pd.period_range(first_test, last_test, freq="M")
    preds = []
    for m in months:
        t0, t1 = m.start_time.tz_localize("UTC"), (m + 1).start_time.tz_localize("UTC")
        train, test = f[f["start_time"] < t0], f[(f["start_time"] >= t0) & (f["start_time"] < t1)]
        if len(test) == 0:
            continue
        block = test[["start_time", "short", "ssp", "short_lag4"]].copy()
        for name, cls in LADDER.items():
            block[f"p_{name}"] = cls().fit(train).predict_proba(test)
        preds.append(block)
    return pd.concat(preds, ignore_index=True)


def week_block_bootstrap(series: pd.Series, times: pd.Series, n=1000, seed=0, q=(0.05, 0.95)):
    """Resample whole ISO weeks with replacement; return mean and the (5%, 95%) interval."""
    rng = np.random.default_rng(seed)
    weeks = times.dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("W").to_numpy()
    uniq = np.unique(weeks)
    by_week = {w: series.to_numpy()[weeks == w] for w in uniq}
    means = []
    for _ in range(n):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        means.append(np.concatenate([by_week[w] for w in pick]).mean())
    means = np.array(means)
    return float(series.mean()), float(np.quantile(means, q[0])), float(np.quantile(means, q[1]))


def headline(preds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    y = preds["short"].to_numpy()
    for name in LADDER:
        p = preds[f"p_{name}"].to_numpy()
        per = pd.Series((p - y) ** 2)
        mean, lo, hi = week_block_bootstrap(per, preds["start_time"])
        rows.append({"model": name, "brier": round(mean, 4), "lo": round(lo, 4), "hi": round(hi, 4)})
    return pd.DataFrame(rows)


def battery_table(preds: pd.DataFrame) -> pd.DataFrame:
    preds = preds.assign(p_short=preds["p_ours"])
    policies = {
        "fixed_cycle": battery.fixed_cycle(),
        "persistence": battery.persistence_rule(),
        "ours_threshold": battery.threshold_rule(),
        "oracle": battery.oracle(),
    }
    rows = []
    for name, pol in policies.items():
        sim = battery.simulate(preds, pol)
        daily = sim.groupby(sim["start_time"].dt.date)["pnl"].sum()
        mean, lo, hi = week_block_bootstrap(daily.reset_index(drop=True), pd.Series(pd.to_datetime(daily.index, utc=True)))
        rows.append({"policy": name, "gbp_per_day": round(mean, 1), "lo": round(lo, 1), "hi": round(hi, 1)})
    t = pd.DataFrame(rows).set_index("policy")
    gap = t.loc["oracle", "gbp_per_day"] - t.loc["fixed_cycle", "gbp_per_day"]
    t["share_of_oracle_gap"] = ((t["gbp_per_day"] - t.loc["fixed_cycle", "gbp_per_day"]) / gap).round(3)
    return t.reset_index()


if __name__ == "__main__":
    f = load_features()
    preds = walk_forward(f)
    preds.to_csv(OUT / "walkforward.csv", index=False)
    print(headline(preds).to_string(index=False))
    print()
    print(battery_table(preds).to_string(index=False))
