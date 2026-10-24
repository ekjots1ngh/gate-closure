"""Point-in-time feature table: one row per half hour, built only from what was public at the gate.

The rule: the decision for period t (starting at T) is made at the gate, T - 60 min. A
forecast row may be used only if its publish_time is strictly before the gate. A price row
exists 15 minutes after its period ends, so the newest price visible at the gate is for
period t-4 (t-3 ends exactly at the gate and prints 15 minutes too late).

Lags are taken by row on the time-sorted table. Where Elexon is missing a period (a handful
of days have 45 or 47), a lag reaches slightly further back: staler, never later.

`asof_features()` in store.sql is the database twin of `_latest_before()` below.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import GATE_CLOSURE, PRICE_LAG_PERIODS

TS = "datetime64[ns, UTC]"   # one timestamp dtype everywhere: merge_asof refuses mixed resolutions


def _latest_before(keys: pd.Series, at: pd.Series, vint: pd.DataFrame) -> pd.DataFrame:
    """Newest vintage for each row: start_time == keys[i] and publish_time strictly before at[i].

    One merge_asof does this for every row at once: rows are sorted by `at`, vintages by
    publish_time, and `by` keeps each forecast matched to its own target period.
    Returns `value` and `publish_time`, aligned to the input index (NaN where none exists).
    """
    left = pd.DataFrame({"start_time": keys.astype(TS), "at": at.astype(TS)}, index=keys.index)
    left = left.dropna().reset_index().sort_values("at")
    right = vint[["start_time", "publish_time", "value"]].astype({"start_time": TS, "publish_time": TS})
    m = pd.merge_asof(left, right.sort_values("publish_time"), left_on="at", right_on="publish_time",
                      by="start_time", direction="backward", allow_exact_matches=False)
    return m.set_index("index")[["value", "publish_time"]].reindex(keys.index)


def _latest_and_previous(keys: pd.Series, gate: pd.Series, vint: pd.DataFrame):
    """The newest vintage before the gate, and the one before that (for revision features)."""
    latest = _latest_before(keys, gate, vint)
    previous = _latest_before(keys, latest["publish_time"], vint)
    return latest["value"], previous["value"]


def _national(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """National rows only. Fails loudly: a silent empty join would make a baseline meaningless."""
    if "boundary" in df:
        df = df[df["boundary"].astype(str) == "N"]
    if df.empty:
        raise ValueError(f"{name}: no national (boundary 'N') rows. Run `python -m gclose.ingest check` "
                         f"and look at the boundaries it lists.")
    return df


def build(prices: pd.DataFrame, windfor: pd.DataFrame, ndf: pd.DataFrame, imbalngc: pd.DataFrame) -> pd.DataFrame:
    """Targets and gate-safe features, one row per settlement period, sorted by start_time."""
    p = prices[["start_time", "ssp", "niv"]].sort_values("start_time").reset_index(drop=True)
    p["start_time"] = p["start_time"].astype(TS)
    p["gate"] = p["start_time"] - GATE_CLOSURE
    p["short"] = (p["niv"] > 0).astype(int)

    # Recent state of the system, from the newest settled periods.
    lag = PRICE_LAG_PERIODS
    for k in (lag, lag + 1, lag + 2):
        p[f"short_lag{k}"] = p["short"].shift(k)
    for k in (lag, lag + 1):
        p[f"niv_lag{k}"] = p["niv"].shift(k)
    seen = p["ssp"].shift(lag)
    p["ssp_lag4"] = seen
    p["ssp_mean48"] = seen.rolling(48, min_periods=24).mean()
    p["ssp_std48"] = seen.rolling(48, min_periods=24).std()
    side = p["short"].shift(lag)
    p["streak"] = side.groupby((side != side.shift()).cumsum()).cumcount() + 1   # length of the current run

    # Forecasts as they stood at the gate. A late cut to the wind forecast is the mechanism
    # behind a short system, so the revision (latest minus previous vintage) is the feature
    # with a physical story. WINDFOR is hourly, so it is matched on the hour.
    p["wind_latest"], wind_prev = _latest_and_previous(p["start_time"].dt.floor("h"), p["gate"], windfor)
    p["wind_revision"] = p["wind_latest"] - wind_prev
    ndf = _national(ndf, "NDF")
    p["demand_latest"], demand_prev = _latest_and_previous(p["start_time"], p["gate"], ndf)
    p["demand_revision"] = p["demand_latest"] - demand_prev
    p["imbal_latest"] = _latest_before(p["start_time"], p["gate"], _national(imbalngc, "IMBALNGC"))["value"]

    # Clock in UTC. Never settlement-period arithmetic: 25 October 2026 has 50 periods.
    p["hour"] = p["start_time"].dt.hour
    p["weekday"] = p["start_time"].dt.weekday
    return p


FEATURES = [
    "short_lag4", "short_lag5", "short_lag6", "niv_lag4", "niv_lag5", "ssp_lag4",
    "ssp_mean48", "ssp_std48", "streak",
    "wind_latest", "wind_revision", "demand_latest", "demand_revision", "imbal_latest",
    "hour", "weekday",
]


def poison(prices: pd.DataFrame, windfor: pd.DataFrame, ndf: pd.DataFrame, imbalngc: pd.DataFrame,
           decided_at: pd.Timestamp, seed: int = 0):
    """Copies of the raw data with everything public at or after `decided_at` replaced by noise.

    If build() respects the gate, no feature of a period whose gate is before `decided_at`
    can change. tests/test_poison.py asserts exactly that.
    """
    rng = np.random.default_rng(seed)

    def scramble(v: pd.DataFrame) -> pd.DataFrame:
        v = v.copy()
        late = v["publish_time"] >= decided_at
        v.loc[late, "value"] = rng.normal(size=late.sum()) * 1e6
        return v

    pr = prices.copy()
    late = pr["start_time"] + pd.Timedelta(minutes=45) >= decided_at    # a price exists 45 min after its start
    pr.loc[late, ["ssp", "sbp", "niv"]] = rng.normal(size=(late.sum(), 3)) * 1e6
    return pr, scramble(windfor), scramble(ndf), scramble(imbalngc)
