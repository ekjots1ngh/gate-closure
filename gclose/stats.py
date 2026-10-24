"""Uncertainty: a vectorised week-block bootstrap, and forecast scores with intervals.

Half hours and days are strongly autocorrelated (a windy week is windy all week), so
intervals resample whole calendar weeks, not individual observations. Per-week sums are
computed once; each resample is then an index draw, so 1,000 resamples of four years cost
one numpy gather. Differences between two series are resampled in pairs (the same weeks for
both), so their interval describes the difference rather than two independent noises.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RESAMPLES = 1000
LEVEL = 0.90


def week_index(times: pd.Series | pd.Index | np.ndarray) -> np.ndarray:
    """Integer week id (0 to W-1) for each timestamp or date, weeks running Monday to Sunday."""
    t = pd.to_datetime(pd.Series(times))
    if t.dt.tz is not None:
        t = t.dt.tz_convert("UTC").dt.tz_localize(None)
    return pd.factorize(t.dt.to_period("W"))[0]


def resampled_means(values: np.ndarray, weeks: np.ndarray, n: int = RESAMPLES, seed: int = 0) -> np.ndarray:
    """Column means of `values` over n week-block resamples.

    values: (N,) or (N, C) observations; weeks: (N,) ids from week_index.
    Returns (n, C): one row of column means per resample.
    """
    x = np.asarray(values, dtype=float).reshape(len(weeks), -1)
    n_weeks = weeks.max() + 1
    sums = np.zeros((n_weeks, x.shape[1]))
    np.add.at(sums, weeks, x)
    counts = np.bincount(weeks, minlength=n_weeks)
    draw = np.random.default_rng(seed).integers(0, n_weeks, size=(n, n_weeks))
    return sums[draw].sum(axis=1) / counts[draw].sum(axis=1)[:, None]


def estimate(value: float, samples: np.ndarray) -> dict[str, float]:
    """A point estimate with the central LEVEL interval of its bootstrap samples."""
    lo, hi = np.quantile(samples, [(1 - LEVEL) / 2, (1 + LEVEL) / 2])
    return {"value": float(value), "lo": float(lo), "hi": float(hi)}


def forecast_scores(
    short: np.ndarray, probs: dict[str, np.ndarray], weeks: np.ndarray, reference: str = "ours"
) -> list[dict]:
    """Brier score and log loss for each forecaster, and the reference's Brier minus each one's.

    Brier and the paired difference carry week-block intervals; negative `reference_minus`
    means the reference forecaster is better.
    """
    names = list(probs)
    p = np.column_stack([probs[name] for name in names])
    y = np.asarray(short, dtype=float)[:, None]
    squared_error = (p - y) ** 2
    q = np.clip(p, 1e-6, 1 - 1e-6)
    log_loss = -(y * np.log(q) + (1 - y) * np.log(1 - q)).mean(axis=0)
    paired = squared_error[:, [names.index(reference)]] - squared_error
    boot = resampled_means(np.hstack([squared_error, paired]), weeks)
    return [
        {
            "model": name,
            "brier": estimate(squared_error[:, j].mean(), boot[:, j]),
            "log_loss": float(log_loss[j]),
            f"{reference}_minus": estimate(paired[:, j].mean(), boot[:, len(names) + j]),
        }
        for j, name in enumerate(names)
    ]
