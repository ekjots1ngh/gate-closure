"""The poison check on real data: wipe the future, and nothing decided before it may change.

tests/test_poison.py runs the strict version on synthetic data with planted leaks. This module
runs the same idea end to end on a real week: poison every Elexon row first public after a
mid-week cutoff, rebuild the features, refit nothing, and count how many inputs, forecasts
and battery decisions changed for the half hours decided before the cutoff.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import GATE_LEAD, HOLDOUT_START
from .decide import TestPeriods
from .features import FEATURES, build, first_print_at, load_table
from .ingest import DATASETS, load
from .models import AllFeatures

HISTORY = pd.Timedelta(days=14)  # raw data before the week, so lags and revisions exist
CUTOFF_INTO_WEEK = pd.Timedelta(days=3.5)
AFTER_CUTOFF = pd.Timedelta(days=5.5)  # raw data after the cutoff, so the poison has something to bite
BITE_MARGIN = pd.Timedelta(hours=2)  # rows this far past the cutoff must change, or the check is vacuous
NOISE_SCALE = 1e6
SEED = 7


def poison(raw: list[pd.DataFrame], cutoff: pd.Timestamp, seed: int = SEED) -> list[pd.DataFrame]:
    """Copies of the raw datasets with everything first public at or after `cutoff` replaced by noise."""
    rng = np.random.default_rng(seed)
    prices, *vintages = (frame.copy() for frame in raw)
    late = (first_print_at(prices) >= cutoff).to_numpy()
    prices.loc[late, ["ssp", "sbp", "niv"]] = rng.normal(size=(late.sum(), 3)) * NOISE_SCALE
    for frame in vintages:
        late = frame["publish_time"] >= cutoff
        frame.loc[late, "value"] = rng.normal(size=late.sum()) * NOISE_SCALE
    return [prices, *vintages]


def _changed(a: pd.DataFrame | pd.Series, b: pd.DataFrame | pd.Series) -> np.ndarray:
    """Rows where two aligned frames differ, treating missing as equal to missing."""
    a, b = a.to_numpy(dtype=float), b.to_numpy(dtype=float)
    same = np.isclose(a, b) | (np.isnan(a) & np.isnan(b))
    return ~same if same.ndim == 1 else ~same.all(axis=1)


def real_week(periods: TestPeriods, week_start: pd.Timestamp) -> dict:
    """Poison a real week from mid-week onwards and count what changed before the cutoff."""
    end = min(week_start + CUTOFF_INTO_WEEK + AFTER_CUTOFF, HOLDOUT_START)
    raw = [load(name) for name in DATASETS]
    raw = [d[(d["start_time"] >= week_start - HISTORY) & (d["start_time"] < end)] for d in raw]
    cutoff = week_start + CUTOFF_INTO_WEEK
    clean, dirty = build(*raw), build(*poison(raw, cutoff))

    month_start = week_start.replace(day=1)
    table = load_table()
    model = AllFeatures().fit(table[table["created_at"] < month_start - GATE_LEAD])  # the replay month's refit
    decided = clean["start_time"] - GATE_LEAD
    before = ((clean["start_time"] >= week_start) & (decided < cutoff)).to_numpy()
    after = (decided >= cutoff + BITE_MARGIN).to_numpy()
    p_clean, p_dirty = (
        pd.Series(model.predict_proba(f[before]), index=f.loc[before, "start_time"]) for f in (clean, dirty)
    )

    # Decisions: the backtest's own optimiser and tables, fed each set of forecasts. Compare the
    # best action at every state of charge, so a difference cannot hide behind the battery's path.
    checked = periods.subset(np.flatnonzero(periods.rows["start_time"].isin(p_clean.index)))
    order = checked.rows["start_time"]
    actions = [checked.chain(p.reindex(order).to_numpy()).argmax(axis=-1) for p in (p_clean, p_dirty)]

    return {
        "cutoff": cutoff.isoformat(),
        "decisions_checked": int(before.sum()),
        "features_changed": int(_changed(clean.loc[before, FEATURES], dirty.loc[before, FEATURES]).sum()),
        "forecasts_changed": int(_changed(p_clean, p_dirty).sum()),
        "decisions_changed": int((actions[0] != actions[1]).any(axis=1).sum()),
        "later_rows_poisoned": int(_changed(clean.loc[after, "wind_latest"], dirty.loc[after, "wind_latest"]).sum()),
    }
