"""The statistics: uncertainty, forecast evaluation and risk, each in a few lines of numpy.

Half hours and days are strongly autocorrelated (a windy week is windy all week), so
intervals resample whole calendar weeks, not individual observations. Per-week sums are
computed once; each resample is then an index draw, so 1,000 resamples of four years cost
one numpy gather. Differences between two series are resampled in pairs (the same weeks for
both), so their interval describes the difference rather than two independent noises.

Forecasts are judged with proper scoring rules (Brier score, log loss), split into
calibration and resolution (Murphy's decomposition), and compared with the Diebold-Mariano
test as a textbook cross-check on the bootstrap.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

RESAMPLES = 1000
LEVEL = 0.90
RELIABILITY_BINS = 10
DM_LAGS = 336  # Newey-West truncation for Diebold-Mariano: one week of half hours
DAYS_PER_YEAR = 365


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


def brier_decomposition(p: np.ndarray, y: np.ndarray, bins: int = RELIABILITY_BINS) -> dict:
    """Murphy's decomposition: Brier = reliability - resolution + uncertainty.

    reliability   how far each bin's average forecast is from what happened in it (calibration; lower is better)
    resolution    how far each bin's outcome rate is from the base rate (sorting skill; higher is better)
    uncertainty   base rate * (1 - base rate): the Brier score of always forecasting the base rate
    With forecasts grouped into bins the identity holds up to a small within-bin term, `residual`.
    `bins` holds the reliability diagram: average forecast, observed rate and count per bin.
    """
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    which = np.minimum((p * bins).astype(int), bins - 1)
    count = np.bincount(which, minlength=bins)
    used = count > 0
    mean_p = np.bincount(which, weights=p, minlength=bins)[used] / count[used]
    rate = np.bincount(which, weights=y, minlength=bins)[used] / count[used]
    base = y.mean()
    reliability = float(np.sum(count[used] * (mean_p - rate) ** 2) / len(y))
    resolution = float(np.sum(count[used] * (rate - base) ** 2) / len(y))
    uncertainty = float(base * (1 - base))
    brier = float(np.mean((p - y) ** 2))
    return {
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
        "residual": brier - (reliability - resolution + uncertainty),
        "bins": [
            {"forecast": float(f), "observed": float(o), "count": int(n)}
            for f, o, n in zip(mean_p, rate, count[used], strict=True)
        ],
    }


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, lags: int = DM_LAGS) -> dict:
    """Do forecasts A and B have the same expected loss? Diebold and Mariano (1995).

    d = loss_a - loss_b, and the statistic is mean(d) / sqrt(long-run variance / n). The long-run
    variance is Newey-West (Bartlett weights up to `lags`), so autocorrelated losses do not
    overstate the evidence. Negative statistics favour A; the p-value is two-sided, normal.
    """
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    n, centred = len(d), d - d.mean()
    long_run = centred @ centred / n
    for lag in range(1, lags + 1):
        long_run += 2 * (1 - lag / (lags + 1)) * (centred[lag:] @ centred[:-lag]) / n
    statistic = d.mean() / math.sqrt(long_run / n)
    return {"statistic": float(statistic), "p_value": math.erfc(abs(statistic) / math.sqrt(2))}


def forecast_scores(
    short: np.ndarray, probs: dict[str, np.ndarray], weeks: np.ndarray, reference: str = "ours"
) -> list[dict]:
    """Every forecaster's scores, and how the reference compares with each.

    brier, with a week-block interval; log loss in nats and in bits (a coin flip is 1 bit);
    Murphy's decomposition; and the reference's Brier minus each forecaster's, with a paired
    interval and the Diebold-Mariano test. Negative `reference_minus` means the reference is better.
    """
    names = list(probs)
    p = np.column_stack([probs[name] for name in names])
    y = np.asarray(short, dtype=float)[:, None]
    squared_error = (p - y) ** 2
    q = np.clip(p, 1e-6, 1 - 1e-6)
    log_loss = -(y * np.log(q) + (1 - y) * np.log(1 - q)).mean(axis=0)
    ref = names.index(reference)
    paired = squared_error[:, [ref]] - squared_error
    boot = resampled_means(np.hstack([squared_error, paired]), weeks)
    return [
        {
            "model": name,
            "brier": estimate(squared_error[:, j].mean(), boot[:, j]),
            "log_loss": float(log_loss[j]),
            "log_loss_bits": float(log_loss[j] / math.log(2)),
            "decomposition": brier_decomposition(p[:, j], y[:, 0]),
            f"{reference}_minus": estimate(paired[:, j].mean(), boot[:, len(names) + j]),
            "diebold_mariano": None if j == ref else diebold_mariano(squared_error[:, ref], squared_error[:, j]),
        }
        for j, name in enumerate(names)
    ]


def risk(daily: pd.Series) -> dict:
    """Annualised Sharpe ratio and maximum drawdown of a daily P&L series.

    Applied to a forecast's gain over the schedule, the Sharpe ratio is an information ratio:
    the reward per unit of risk for deviating from the benchmark.
    """
    cumulative = daily.cumsum()
    return {
        "sharpe": float(daily.mean() / daily.std() * math.sqrt(DAYS_PER_YEAR)),
        "max_drawdown": float((cumulative.cummax() - cumulative).max()),
    }


def autocorrelation(x: np.ndarray, lags: int) -> np.ndarray:
    """Sample autocorrelation of x at lags 1..lags."""
    centred = np.asarray(x, dtype=float) - np.mean(x)
    variance = centred @ centred
    return np.array([centred[lag:] @ centred[:-lag] / variance for lag in range(1, lags + 1)])
