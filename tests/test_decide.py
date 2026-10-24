"""The decision layer's tables: the identity that makes "forecast versus schedule" a fair comparison."""

import numpy as np
import pandas as pd

from gclose.decide import Tables


def test_base_rate_mix_reproduces_the_profile():
    """With P(short) at the slot's base rate, the expected price is exactly the plain profile.

    This is why the chain policy fed the base rate takes the schedule's actions, so any
    difference between chain/ours and chain/schedule is the forecast's doing.
    """
    rng = np.random.default_rng(2)
    t = pd.date_range("2026-01-01", "2026-04-30 23:30", freq="30min", tz="UTC")
    short = (rng.random(len(t)) < 0.55).astype(int)
    table = pd.DataFrame(
        {
            "start_time": t,
            "created_at": t + pd.Timedelta(minutes=52),
            "short": short,
            "ssp": rng.normal(70, 30, len(t)) + 40 * short,
        }
    )
    tables = Tables.build(table, [pd.Timestamp("2026-04-01", tz="UTC")])
    mix = tables.short_share * tables.mu_short + (1 - tables.short_share) * tables.mu_long
    np.testing.assert_allclose(mix, tables.profile, atol=1e-9)
