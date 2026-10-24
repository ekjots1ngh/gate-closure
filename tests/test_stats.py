"""The statistics, checked against brute force and against cases with known answers."""

import numpy as np
import pandas as pd

from gclose import stats


def test_resampled_means_match_a_brute_force_bootstrap():
    rng = np.random.default_rng(0)
    weeks = np.repeat(np.arange(6), [3, 5, 4, 6, 2, 4])
    values = rng.normal(size=(len(weeks), 2))
    fast = stats.resampled_means(values, weeks, n=50, seed=1)
    draws = np.random.default_rng(1).integers(0, 6, size=(50, 6))
    slow = np.array([np.vstack([values[weeks == w] for w in draw]).mean(axis=0) for draw in draws])
    np.testing.assert_allclose(fast, slow)


def test_brier_decomposition_is_exact_when_each_bin_holds_one_forecast_value():
    rng = np.random.default_rng(2)
    p = rng.choice([0.15, 0.55, 0.85], size=5000)
    y = (rng.random(5000) < p).astype(float)
    d = stats.brier_decomposition(p, y)
    assert abs(d["residual"]) < 1e-12
    assert np.isclose(d["reliability"] - d["resolution"] + d["uncertainty"], np.mean((p - y) ** 2))
    assert d["reliability"] < 0.001 and d["resolution"] > 0.05  # calibrated, and it sorts outcomes


def test_diebold_mariano_points_to_the_better_forecast():
    rng = np.random.default_rng(3)
    noise = rng.normal(size=4000)
    better, worse = noise**2, (noise + 0.3) ** 2
    test = stats.diebold_mariano(better, worse, lags=10)
    assert test["statistic"] < -5 and test["p_value"] < 1e-6
    assert stats.diebold_mariano(worse, better, lags=10)["statistic"] == -test["statistic"]


def test_drawdown_is_the_largest_fall_from_a_running_peak():
    assert stats.risk(pd.Series([1.0, -3.0, 2.0, 0.5]))["max_drawdown"] == 3.0


def test_autocorrelation_of_an_alternating_series_is_minus_one_then_one():
    lags = stats.autocorrelation(np.tile([1.0, 0.0], 500), 2)
    np.testing.assert_allclose(lags, [-1.0, 1.0], atol=0.01)
