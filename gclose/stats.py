"""Week-block bootstrap, vectorised.

Half-hours and days are strongly autocorrelated (a windy week is windy all week), so
intervals resample whole calendar weeks, not individual observations. Per-week sums are
computed once; each resample is then just an index draw, so 1,000 resamples of four years
cost one numpy gather instead of 1,000 pandas concatenations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def week_index(times) -> np.ndarray:
    """Integer week id (0..W-1) for each timestamp or date, Monday to Sunday."""
    t = pd.to_datetime(pd.Series(times))
    if t.dt.tz is not None:
        t = t.dt.tz_convert("UTC").dt.tz_localize(None)
    return pd.factorize(t.dt.to_period("W"))[0]


def resampled_means(values, weeks: np.ndarray, n: int = 1000, seed: int = 0) -> np.ndarray:
    """Column means of `values` over n week-block resamples.

    values: (N,) or (N, C) observations; weeks: (N,) ids from week_index.
    Returns (n, C): one row of column means per resample.
    """
    x = np.asarray(values, dtype=float).reshape(len(weeks), -1)
    w = weeks.max() + 1
    sums = np.zeros((w, x.shape[1]))
    np.add.at(sums, weeks, x)
    counts = np.bincount(weeks, minlength=w)
    draw = np.random.default_rng(seed).integers(0, w, size=(n, w))
    return sums[draw].sum(axis=1) / counts[draw].sum(axis=1)[:, None]


def interval(samples: np.ndarray, level: float = 0.90) -> tuple[float, float]:
    """Central `level` interval of bootstrap samples."""
    tail = (1 - level) / 2
    lo, hi = np.quantile(samples, [tail, 1 - tail])
    return float(lo), float(hi)
