"""The battery optimiser, checked against the obvious slow version and its own rules."""

import numpy as np
import pandas as pd

from gclose import battery as b
from gclose.decide import Tables


def _slow_value_tables(profile, horizon=47):
    """Textbook backward induction: one slot, one SoC level, one action at a time."""
    V = np.zeros((48, b.K))
    for s in range(48):
        v = np.zeros(b.K)
        for h in range(horizon - 1, -1, -1):
            price = profile[(s + h) % 48]
            new = v.copy()                                                     # hold
            for k in range(b.K):
                if k > 0:
                    new[k] = max(new[k], b.STEP * (b.EFF * price - b.WEAR) + v[k - 1])
                if k < b.K - 1:
                    new[k] = max(new[k], -b.STEP * (price + b.WEAR) + v[k + 1])
            v = new
        V[s] = v
    return V


def test_value_tables_match_the_scalar_loop():
    profile = np.random.default_rng(0).normal(80, 40, 48)
    np.testing.assert_allclose(b.value_tables(profile), _slow_value_tables(profile), atol=1e-9)


def test_ties_hold():
    action, soc, pnl = b.simulate(np.zeros((3, b.K, 3)), np.full(3, 50.0), np.zeros(3, dtype=int))
    assert (action == 0).all() and (soc == 0).all() and (pnl == 0).all()


def test_simulate_respects_physics_cash_and_the_loss_limit():
    rng = np.random.default_rng(1)
    days, n = 30, 48 * 30
    realised = rng.normal(80, 600, n)                              # wild enough to breach the limit
    q = b.q_values(rng.normal(0, 100, (n, b.K)), rng.normal(80, 40, n))
    day = np.repeat(np.arange(days), 48)
    action, soc, pnl = b.simulate(q, realised, day)

    assert soc.min() >= 0 and soc.max() <= b.CAP
    assert np.allclose(np.diff(np.r_[0.0, soc]), -b.STEP * action)    # +1 discharges one step
    paid = b.cash(realised)[np.arange(n), np.select([action == 1, action == -1], [b.DISCHARGE, b.CHARGE], b.HOLD)]
    assert np.allclose(pnl, paid)

    breached = 0
    for d in range(days):
        running = np.cumsum(pnl[day == d])
        over = np.flatnonzero(running < -b.DAILY_LOSS_LIMIT)
        if len(over):
            breached += 1
            assert (action[day == d][over[0] + 1:] == 0).all()
    assert breached > 0, "test data never hit the loss limit, so the check above proved nothing"


def test_base_rate_mix_reproduces_the_profile():
    """With P(short) = the slot's base rate, the expected price is the plain profile.

    This is why the chain policy fed the base rate makes exactly the tilt's decisions, and
    any difference between chain_ours and chain_tilt is the forecast's doing.
    """
    rng = np.random.default_rng(2)
    t = pd.date_range("2026-01-01", "2026-04-30 23:30", freq="30min", tz="UTC")
    short = (rng.random(len(t)) < 0.55).astype(int)
    f = pd.DataFrame({"start_time": t, "short": short, "ssp": rng.normal(70, 30, len(t)) + 40 * short})
    tab = Tables.build(f, ["2026-04"])
    mix = tab.pi * tab.mu_short + (1 - tab.pi) * tab.mu_long
    np.testing.assert_allclose(mix, tab.profile, atol=1e-9)
