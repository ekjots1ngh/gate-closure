"""The poison test: wipe the future, and no gate-safe feature may change.

Runs on synthetic data, so it needs no network. The data is built to be awkward: forecasts
publish at random minutes and some prices print late. A cutoff is placed one minute before
every publication in a two-day window, so any input used more than a minute before it was
public changes something. What counts as "the future" comes from the synthetic data's true
publish times and the protocol's gate (T - 60 min), never from the code under test. The last test plants leaks and checks that
each one is caught, so a pass here means something.
"""

import numpy as np
import pandas as pd
import pytest

from gclose import features
from gclose.features import build

GATE = pd.Timedelta(minutes=60)
WINDOW = pd.Timestamp("2026-03-03", tz="UTC"), pd.Timestamp("2026-03-05", tz="UTC")
TARGETS = ("short", "ssp", "niv")      # outcomes of the period itself, not inputs


def _vintages(rng, pubs, step, horizon, mean, sd, **extra):
    """A forecast dataset: each publish time covers the next `horizon` target periods."""
    pub = np.repeat(pubs, horizon)
    target = np.repeat(pubs.floor(step), horizon) + np.tile(pd.to_timedelta(np.arange(horizon) * pd.Timedelta(step)), len(pubs))
    return pd.DataFrame({"publish_time": pub, "start_time": target, "value": rng.normal(mean, sd, len(pub)), **extra})


def _synthetic(days=6, seed=1):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-03-01", periods=48 * days, freq="30min", tz="UTC")
    delay = rng.normal(52, 3, len(t))
    late = rng.random(len(t)) < 0.08
    delay[late] = rng.uniform(60, 150, late.sum())                        # some prices print late
    prices = pd.DataFrame({"start_time": t, "created_at": t + pd.to_timedelta(delay, unit="min"),
                           "ssp": rng.normal(80, 30, len(t)), "sbp": 0.0, "niv": rng.normal(0, 300, len(t))})
    pubs = (pd.date_range("2026-02-28", periods=8 * (days + 1), freq="3h", tz="UTC")
            + pd.to_timedelta(rng.integers(0, 180, 8 * (days + 1)), unit="min"))   # at random minutes
    windfor = _vintages(rng, pubs, "1h", 73, 10000, 2000)
    ndf = _vintages(rng, pubs, "30min", 146, 30000, 3000, boundary="N")
    imb = _vintages(rng, pubs, "30min", 146, 0, 500, boundary="N")
    return prices, windfor, ndf, imb


def _poison(data, cutoff, seed=0):
    """Noise over everything whose true publish time is at or after `cutoff`."""
    rng = np.random.default_rng(seed)
    prices, *vintages = (d.copy() for d in data)
    late = prices["created_at"] >= cutoff
    prices.loc[late, ["ssp", "niv"]] = rng.normal(size=(late.sum(), 2)) * 1e6
    for v in vintages:
        late = v["publish_time"] >= cutoff
        v.loc[late, "value"] = rng.normal(size=late.sum()) * 1e6
    return prices, *vintages


def _cutoffs(data) -> list[pd.Timestamp]:
    """One minute before every publication (price print or forecast vintage) in WINDOW."""
    prices, *vintages = data
    events = pd.concat([prices["created_at"], *(v["publish_time"] for v in vintages)]).drop_duplicates()
    return sorted(events[(events >= WINDOW[0]) & (events < WINDOW[1])] - pd.Timedelta(minutes=1))


def _leaks(data) -> int:
    """Rows decided before a cutoff whose inputs change when that cutoff's future is poisoned.

    Every column build() returns is checked except the period's own outcomes, so a leak into a
    feature that is not (yet) in FEATURES is caught too.
    """
    clean = build(*data)
    inputs = clean.select_dtypes("number").columns.difference(TARGETS)
    decided = clean["start_time"] - GATE
    total = 0
    for cutoff in _cutoffs(data):
        dirty = build(*_poison(data, cutoff))
        rows = (decided < cutoff).to_numpy()
        a, b = clean.loc[rows, inputs].to_numpy(float), dirty.loc[rows, inputs].to_numpy(float)
        same = np.isclose(a, b, rtol=0, atol=1e-9) | (np.isnan(a) & np.isnan(b))
        total += int((~same).any(axis=1).sum())
    return total


def test_future_noise_changes_nothing_before_the_gate():
    data = _synthetic()
    assert _leaks(data) == 0
    # The poison does bite after the gate, so the check above is not vacuous.
    clean, dirty = build(*data), build(*_poison(data, WINDOW[0]))
    after = (clean["start_time"] - GATE >= WINDOW[0] + pd.Timedelta(hours=3)).to_numpy()
    assert not np.allclose(clean.loc[after, "wind_latest"], dirty.loc[after, "wind_latest"])


def test_newest_price_feature_is_four_periods_old_when_printed_in_time():
    prices, *rest = _synthetic(days=2)
    f = build(prices, *rest)
    on_time = (prices["created_at"] - prices["start_time"] < pd.Timedelta(minutes=60)).to_numpy()
    i = np.flatnonzero(on_time[:-4])[20] + 4                                # any row whose t-4 printed in time
    assert f.loc[i, "ssp_lag4"] == prices.loc[i - 4, "ssp"]
    assert f.loc[i, "start_time"] - prices.loc[i - 4, "start_time"] == pd.Timedelta(minutes=120)


LEAKS = ["late prints ignored", "price lag 3", "gate 45 min", "gate 30 min", "decide at the period start"]


@pytest.mark.parametrize("leak", LEAKS)
def test_planted_leaks_are_caught(monkeypatch, leak):
    if leak in ("late prints ignored", "price lag 3"):
        monkeypatch.setattr(features, "first_print_at", lambda p: p["start_time"])   # every price "public" at once
        if leak == "price lag 3":
            monkeypatch.setattr(features, "PRICE_LAG_PERIODS", 3)
    else:
        minutes = {"gate 45 min": 45, "gate 30 min": 30, "decide at the period start": 0}[leak]
        monkeypatch.setattr(features, "GATE_CLOSURE", pd.Timedelta(minutes=minutes))
    assert _leaks(_synthetic()) > 0
