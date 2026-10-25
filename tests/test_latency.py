"""The value-of-time study moves the gate; the newest visible price must move with it."""

from datetime import timedelta

import gclose
from gclose import features, latency


def timing() -> tuple:
    return gclose.GATE_LEAD, features.GATE_LEAD, features.PRICE_LAG_PERIODS


def test_the_price_lag_follows_the_gate():
    lags = {minutes: latency.price_lag(timedelta(minutes=minutes)) for minutes in (30, 60, 90, 120)}
    assert lags == {30: 3, 60: gclose.PRICE_LAG_PERIODS, 90: 5, 120: 6}


def test_moving_the_gate_leaves_nothing_behind():
    before = timing()
    with latency.gate_lead(30):
        inside = timing()
    assert inside == (timedelta(minutes=30), timedelta(minutes=30), 3)
    assert timing() == before
