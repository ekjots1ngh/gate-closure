"""Point-in-time feature table.

The one rule: for target period t starting at T, a feature may only use rows whose
publish_time (forecasts) or whose own start_time + 30 min + 15 min (prices, i.e. when the
indicative print exists) is before the gate, T - 60 min. In practice the newest price
known at the gate is period t-4.

This is the pandas twin of asof_features() in store.sql so the pipeline runs with no
database. Both must agree; tests/test_asof.py checks that on a sample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import GATE_CLOSURE, PRICE_LAG_PERIODS

RAW_COLS = ["start_time", "ssp", "niv"]


def _asof_vintage(targets: pd.DataFrame, vint: pd.DataFrame, key_time: str, name: str,
                  previous: bool = False) -> pd.Series:
    """Newest vintage per target published strictly before the gate.

    targets: start_time, gate, and key_time (the forecast start_time to match on).
    vint: dataset rows with publish_time, start_time, value.
    If previous=True, return the vintage before the newest one (for revision features).
    """
    v = vint.sort_values("publish_time")
    out = pd.Series(np.nan, index=targets.index, name=name)
    groups = {k: g for k, g in v.groupby("start_time")}
    pubs = {k: g["publish_time"].to_numpy() for k, g in groups.items()}
    vals = {k: g["value"].to_numpy() for k, g in groups.items()}
    for i, (kt, gate) in enumerate(zip(targets[key_time].to_numpy(), targets["gate"].to_numpy())):
        if kt not in pubs:
            continue
        n = np.searchsorted(pubs[kt], gate, side="left")   # vintages strictly before gate
        idx = n - 2 if previous else n - 1
        if idx >= 0:
            out.iat[i] = vals[kt][idx]
    return out


def build(prices: pd.DataFrame, windfor: pd.DataFrame, ndf: pd.DataFrame, imbalngc: pd.DataFrame) -> pd.DataFrame:
    """Return one row per settlement period with targets and gate-safe features."""
    p = prices[RAW_COLS].copy().sort_values("start_time").reset_index(drop=True)
    p["gate"] = p["start_time"] - GATE_CLOSURE
    p["short"] = (p["niv"] > 0).astype(int)

    # Lagged state. Period t-4 is the newest whose indicative price existed at the gate.
    for k in (PRICE_LAG_PERIODS, PRICE_LAG_PERIODS + 1, PRICE_LAG_PERIODS + 2):
        p[f"short_lag{k}"] = p["short"].shift(k)
        p[f"niv_lag{k}"] = p["niv"].shift(k)
    p["ssp_lag4"] = p["ssp"].shift(PRICE_LAG_PERIODS)
    lagged = p["ssp"].shift(PRICE_LAG_PERIODS)
    p["ssp_mean48"] = lagged.rolling(48, min_periods=24).mean()
    p["ssp_std48"] = lagged.rolling(48, min_periods=24).std()
    s = p["short"].shift(PRICE_LAG_PERIODS)
    p["streak"] = s.groupby((s != s.shift()).cumsum()).cumcount() + 1

    # Forecast vintages, as-of the gate. WINDFOR is hourly: match on the hour.
    p["hour_start"] = p["start_time"].dt.floor("h")
    nat = lambda df: df[df["boundary"].astype(str).isin(["N", "nan"])] if "boundary" in df else df
    p["wind_latest"] = _asof_vintage(p, windfor, "hour_start", "wind_latest")
    p["wind_prev"] = _asof_vintage(p, windfor, "hour_start", "wind_prev", previous=True)
    p["wind_revision"] = p["wind_latest"] - p["wind_prev"]
    p["demand_latest"] = _asof_vintage(p, nat(ndf), "start_time", "demand_latest")
    p["demand_prev"] = _asof_vintage(p, nat(ndf), "start_time", "demand_prev", previous=True)
    p["demand_revision"] = p["demand_latest"] - p["demand_prev"]
    p["imbal_latest"] = _asof_vintage(p, nat(imbalngc), "start_time", "imbal_latest")

    # Clock, in UTC. Never settlement_period arithmetic: 25 Oct 2026 has 50 periods.
    p["hour"] = p["start_time"].dt.hour
    p["weekday"] = p["start_time"].dt.weekday
    return p.drop(columns=["hour_start"])


FEATURES = [
    "short_lag4", "short_lag5", "short_lag6", "niv_lag4", "niv_lag5", "ssp_lag4",
    "ssp_mean48", "ssp_std48", "streak",
    "wind_latest", "wind_revision", "demand_latest", "demand_revision", "imbal_latest",
    "hour", "weekday",
]


def poison(prices: pd.DataFrame, windfor: pd.DataFrame, ndf: pd.DataFrame, imbalngc: pd.DataFrame,
           decided_at: pd.Timestamp, seed: int = 0):
    """Return copies where everything published after decided_at is replaced by noise.

    If build() is honest, features for any period whose gate is before decided_at are
    unchanged. tests/test_poison.py asserts exactly that.
    """
    rng = np.random.default_rng(seed)

    def noise_vint(v):
        v = v.copy()
        m = v["publish_time"] >= decided_at
        v.loc[m, "value"] = rng.normal(size=m.sum()) * 1e6
        return v

    pr = prices.copy()
    # A price row "exists" 45 min after its start (period end + 15 min indicative print).
    exists_at = pr["start_time"] + pd.Timedelta(minutes=45)
    m = exists_at >= decided_at
    pr.loc[m, ["ssp", "sbp", "niv"]] = rng.normal(size=(m.sum(), 3)) * 1e6
    return pr, noise_vint(windfor), noise_vint(ndf), noise_vint(imbalngc)
