"""The battery optimiser, checked against the obvious slow version and against its own rules."""

import numpy as np

from gclose import PERIODS_PER_DAY, PRICE_LAG_PERIODS, battery


def _slow_value_tables(profile: np.ndarray, horizon: int = PERIODS_PER_DAY - 1) -> np.ndarray:
    """Textbook backward induction: one slot, one SoC level, one action at a time."""
    values = np.zeros((PERIODS_PER_DAY, battery.K))
    for slot in range(PERIODS_PER_DAY):
        v = np.zeros(battery.K)
        for h in range(horizon - 1, -1, -1):
            price = profile[(slot + h) % PERIODS_PER_DAY]
            new = v.copy()  # hold
            for k in range(battery.K):
                if k > 0:
                    new[k] = max(new[k], battery.STEP * (battery.EFF * price - battery.WEAR) + v[k - 1])
                if k < battery.K - 1:
                    new[k] = max(new[k], -battery.STEP * (price + battery.WEAR) + v[k + 1])
            v = new
        values[slot] = v
    return values


def test_value_tables_match_the_scalar_loop():
    profile = np.random.default_rng(0).normal(80, 40, PERIODS_PER_DAY)
    np.testing.assert_allclose(battery.value_tables(profile), _slow_value_tables(profile), atol=1e-9)


def test_ties_hold():
    trajectory = battery.simulate(np.zeros((3, battery.K, 3)), np.full(3, 50.0), np.zeros(3, dtype=int))
    assert (trajectory.action == 0).all() and (trajectory.soc == 0).all() and (trajectory.pnl == 0).all()


def test_simulate_respects_physics_cash_and_a_loss_limit_on_settled_cash():
    rng = np.random.default_rng(1)
    days = 30
    n = PERIODS_PER_DAY * days
    realised = rng.normal(80, 600, n)  # wild enough to breach the loss limit
    q = battery.q_values(rng.normal(0, 100, (n, battery.K)), rng.normal(80, 40, n))
    day = np.repeat(np.arange(days), PERIODS_PER_DAY)
    t = battery.simulate(q, realised, day)

    assert t.soc.min() >= 0 and t.soc.max() <= battery.CAP
    assert np.allclose(np.diff(np.r_[0.0, t.soc]), -battery.STEP * t.action)  # +1 discharges one step
    chosen = np.select([t.action == 1, t.action == -1], [battery.DISCHARGE, battery.CHARGE], battery.HOLD)
    assert np.allclose(t.pnl, battery.cash(realised)[np.arange(n), chosen])

    # Once the losses the battery could see at the gate (its cash up to t-4) pass the limit, it holds.
    held = 0
    for d in range(days):
        today = day == d
        settled = np.cumsum(t.pnl[today])
        for i in range(PRICE_LAG_PERIODS, PERIODS_PER_DAY):
            if settled[i - PRICE_LAG_PERIODS] < -battery.DAILY_LOSS_LIMIT:
                assert t.action[today][i] == 0
                held += 1
    assert held > 0, "the test data never hit the loss limit, so the check above proved nothing"


def test_hindsight_is_a_ceiling():
    """Knowing every price can only beat a policy that does not."""
    rng = np.random.default_rng(3)
    n = PERIODS_PER_DAY * 5
    realised = rng.normal(80, 60, n)
    day = np.repeat(np.arange(5), PERIODS_PER_DAY)
    profile = np.full(PERIODS_PER_DAY, realised.mean())
    myopic = battery.q_values(np.tile(battery.value_tables(profile)[0], (n, 1)), realised)
    hindsight = battery.simulate(battery.hindsight_q(realised), realised, day).pnl.sum()
    assert hindsight >= battery.simulate(myopic, realised, day).pnl.sum()
