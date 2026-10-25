"""The poison test: wipe the future, and no gate-safe input may change.

Runs on synthetic data, so it needs no network. The data is built to be awkward: forecasts
publish at random minutes and some prices print late. A cutoff is placed one minute before
every publication in a two-day window, so any input used more than a minute before it was
public changes something. What counts as "the future" comes from the synthetic data's true
publish times and the protocol's gate, never from the code under test.

The last test plants leaks and checks each one is caught, so a pass here means something.
"""

from collections.abc import Iterator

import numpy as np
import pandas as pd
import pytest

from gclose import PERIODS_PER_DAY, PRICE_LAG_PERIODS, features
from gclose.features import build

GATE = pd.Timedelta(minutes=60)  # the protocol's gate, written out here rather than imported from gclose
WINDOW = pd.Timestamp("2026-03-03", tz="UTC"), pd.Timestamp("2026-03-05", tz="UTC")
TARGETS = ("short", "ssp", "niv")  # outcomes of the period itself, not inputs
LATE_SHARE = 0.08  # share of prices that print late, between 60 and 150 minutes after start
NOISE = 1e6


def _vintages(
    rng: np.random.Generator,
    publish_times: pd.DatetimeIndex,
    step: str,
    horizon: int,
    level: tuple[float, float],
    **extra: str,
) -> pd.DataFrame:
    """A forecast dataset: each publish time covers the next `horizon` target periods."""
    targets = np.arange(horizon) * pd.Timedelta(step)
    return pd.DataFrame(
        {
            "publish_time": np.repeat(publish_times, horizon),
            "start_time": np.repeat(publish_times.floor(step), horizon) + np.tile(targets, len(publish_times)),
            "value": rng.normal(*level, horizon * len(publish_times)),
            **extra,
        }
    )


def _synthetic(days: int = 6, seed: int = 1) -> tuple[pd.DataFrame, ...]:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-03-01", periods=PERIODS_PER_DAY * days, freq="30min", tz="UTC")
    print_delay = rng.normal(52, 3, len(t))
    late = rng.random(len(t)) < LATE_SHARE
    print_delay[late] = rng.uniform(60, 150, late.sum())
    prices = pd.DataFrame(
        {
            "start_time": t,
            "created_at": t + pd.to_timedelta(print_delay, unit="min"),
            "ssp": rng.normal(80, 30, len(t)),
            "sbp": 0.0,
            "niv": rng.normal(0, 300, len(t)),
        }
    )
    n_publications = 8 * (days + 1)  # every three hours, at a random minute
    publish_times = pd.date_range("2026-02-28", periods=n_publications, freq="3h", tz="UTC") + pd.to_timedelta(
        rng.integers(0, 180, n_publications), unit="min"
    )
    windfor = _vintages(rng, publish_times, "1h", 73, (10000, 2000))
    ndf = _vintages(rng, publish_times, "30min", 146, (30000, 3000), boundary="N")
    imbalngc = _vintages(rng, publish_times, "30min", 146, (0, 500), boundary="N")
    return prices, windfor, ndf, imbalngc


def _poison(data: tuple[pd.DataFrame, ...], cutoff: pd.Timestamp, seed: int = 0) -> tuple[pd.DataFrame, ...]:
    """Noise over everything whose true publish time is at or after `cutoff`."""
    rng = np.random.default_rng(seed)
    prices, *vintages = (d.copy() for d in data)
    late = prices["created_at"] >= cutoff
    prices.loc[late, ["ssp", "niv"]] = rng.normal(size=(late.sum(), 2)) * NOISE
    for v in vintages:
        late = v["publish_time"] >= cutoff
        v.loc[late, "value"] = rng.normal(size=late.sum()) * NOISE
    return prices, *vintages


def _cutoffs(data: tuple[pd.DataFrame, ...]) -> list[pd.Timestamp]:
    """One minute before every publication (price print or forecast vintage) in WINDOW."""
    prices, *vintages = data
    events = pd.concat([prices["created_at"], *(v["publish_time"] for v in vintages)]).drop_duplicates()
    return sorted(events[(events >= WINDOW[0]) & (events < WINDOW[1])] - pd.Timedelta(minutes=1))


def _leaks(data: tuple[pd.DataFrame, ...]) -> Iterator[int]:
    """For each cutoff, the rows decided before it whose inputs change when its future is poisoned.

    Every column build() returns is checked except the period's own outcomes, so a leak into a
    column that is not (yet) in FEATURES is caught too.
    """
    clean = build(*data)
    inputs = clean.select_dtypes("number").columns.difference(TARGETS)
    decided = clean["start_time"] - GATE
    for cutoff in _cutoffs(data):
        dirty = build(*_poison(data, cutoff))
        rows = (decided < cutoff).to_numpy()
        a, b = clean.loc[rows, inputs].to_numpy(float), dirty.loc[rows, inputs].to_numpy(float)
        same = np.isclose(a, b, rtol=0, atol=1e-9) | (np.isnan(a) & np.isnan(b))
        yield int((~same).any(axis=1).sum())


def test_future_noise_changes_nothing_before_the_gate():
    data = _synthetic()
    assert sum(_leaks(data)) == 0
    # The poison does bite after the gate, so the check above is not vacuous.
    clean, dirty = build(*data), build(*_poison(data, WINDOW[0]))
    after = (clean["start_time"] - GATE >= WINDOW[0] + pd.Timedelta(hours=3)).to_numpy()
    assert not np.allclose(clean.loc[after, "wind_latest"], dirty.loc[after, "wind_latest"])


def test_newest_price_is_four_periods_old_when_printed_in_time():
    prices, *rest = _synthetic(days=2)
    table = build(prices, *rest)
    printed_in_time = (prices["created_at"] - prices["start_time"] < GATE).to_numpy()
    newest = np.flatnonzero(printed_in_time[:-PRICE_LAG_PERIODS])[PERIODS_PER_DAY // 2]  # any, past the warm-up
    i = newest + PRICE_LAG_PERIODS
    assert table.loc[i, "price_newest"] == prices.loc[newest, "ssp"]
    assert table.loc[i, "start_time"] - prices.loc[newest, "start_time"] == PRICE_LAG_PERIODS * pd.Timedelta("30min")


PLANTED = {
    "late prints ignored": {"first_print_at": lambda p: p["start_time"]},
    "price lag 3": {"first_print_at": lambda p: p["start_time"], "PRICE_LAG_PERIODS": 3},
    "gate 45 min": {"GATE_LEAD": pd.Timedelta(minutes=45)},
    "gate 30 min": {"GATE_LEAD": pd.Timedelta(minutes=30)},
    "decide at the period start": {"GATE_LEAD": pd.Timedelta(0)},
}


@pytest.mark.parametrize("patches", PLANTED.values(), ids=PLANTED.keys())
def test_planted_leaks_are_caught(monkeypatch, patches):
    for name, value in patches.items():
        monkeypatch.setattr(features, name, value)
    assert any(changed > 0 for changed in _leaks(_synthetic()))


def test_a_forecast_published_exactly_at_the_gate_is_not_used():
    """Public "before the gate" means strictly before: real WINDFOR, NDF and IMBALNGC vintages land on :00 and :30."""
    prices, windfor, ndf, imbalngc = _synthetic(days=3)
    table = features.build(prices, windfor, ndf, imbalngc)
    row = table.iloc[len(table) // 2]
    on_the_gate = (
        imbalngc[imbalngc["start_time"] == row["start_time"]].iloc[:1].assign(publish_time=row["gate"], value=123_456.0)
    )
    later = features.build(prices, windfor, ndf, pd.concat([imbalngc, on_the_gate], ignore_index=True))
    assert later.loc[later["start_time"] == row["start_time"], "indicated_latest"].iloc[0] != 123_456.0
    just_before = on_the_gate.assign(publish_time=row["gate"] - pd.Timedelta(seconds=1))
    earlier = features.build(prices, windfor, ndf, pd.concat([imbalngc, just_before], ignore_index=True))
    assert earlier.loc[earlier["start_time"] == row["start_time"], "indicated_latest"].iloc[0] == 123_456.0
