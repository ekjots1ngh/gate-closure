"""The poison test: wipe the future, and no gate-safe feature may change.

Runs on synthetic data so CI needs no network. `make test` runs it; the demo's P key
runs the same function on the real cache.
"""

import numpy as np
import pandas as pd

from gclose import features
from gclose.features import FEATURES, build, poison


def _synthetic(days=6, seed=1):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-03-01", periods=48 * days, freq="30min", tz="UTC")
    prices = pd.DataFrame({"start_time": t, "ssp": rng.normal(80, 30, len(t)),
                           "sbp": rng.normal(80, 30, len(t)), "niv": rng.normal(0, 300, len(t))})
    # Eight vintages a day, each covering the next 73 hours, like WINDFOR.
    pubs = pd.date_range("2026-02-28", periods=8 * (days + 1), freq="3h", tz="UTC")
    rows = []
    for pub in pubs:
        for h in range(73):
            st = pub.floor("h") + pd.Timedelta(hours=h)
            rows.append((pub, st, rng.normal(10000, 2000)))
    windfor = pd.DataFrame(rows, columns=["publish_time", "start_time", "value"])
    half = []
    for pub in pubs:
        for k in range(146):
            st = pub.floor("30min") + pd.Timedelta(minutes=30 * k)
            half.append((pub, st, rng.normal(30000, 3000), "N"))
    ndf = pd.DataFrame(half, columns=["publish_time", "start_time", "value", "boundary"])
    imb = ndf.copy()
    imb["value"] = rng.normal(0, 500, len(imb))
    return prices, windfor, ndf, imb


def test_future_noise_changes_nothing_before_the_gate():
    prices, windfor, ndf, imb = _synthetic()
    decided_at = pd.Timestamp("2026-03-04 12:00", tz="UTC")
    clean = build(prices, windfor, ndf, imb)
    pr2, w2, n2, i2 = poison(prices, windfor, ndf, imb, decided_at)
    dirty = build(pr2, w2, n2, i2)

    safe = clean["gate"] < decided_at
    a = clean.loc[safe, FEATURES].reset_index(drop=True)
    b = dirty.loc[safe, FEATURES].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=0, atol=1e-9)

    # And the poison did bite after the gate, so the test is not vacuous.
    after = clean["gate"] >= decided_at + pd.Timedelta(hours=3)
    assert not np.allclose(clean.loc[after, "wind_latest"].fillna(0), dirty.loc[after, "wind_latest"].fillna(0))


def test_newest_price_feature_is_four_periods_old():
    prices, windfor, ndf, imb = _synthetic(days=2)
    f = build(prices, windfor, ndf, imb)
    i = 50
    assert f.loc[i, "ssp_lag4"] == prices.loc[i - 4, "ssp"]
    assert f.loc[i, "start_time"] - prices.loc[i - 4, "start_time"] == pd.Timedelta(minutes=120)
