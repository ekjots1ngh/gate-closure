"""The battery and its policies. Decision at the gate for period t; paid the realised price.

Battery per PROTOCOL.md: 1 MW, 2 MWh, 0.5 MWh per half hour, 85% round trip,
5 GBP/MWh wear, SoC in [0, 2], daily loss limit 500 GBP then hold until midnight UTC.

A policy is a function (row, soc) -> action in {-1 charge, 0 hold, +1 discharge}
where row carries the gate-safe features plus whatever forecast columns the policy needs
(p_short, price_p50, ...). simulate() walks the periods in order and returns a P&L series.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STEP_MWH = 0.5
CAP_MWH = 2.0
EFF = 0.85
WEAR = 5.0            # GBP per MWh of throughput
DAILY_LOSS_LIMIT = 500.0


def simulate(df: pd.DataFrame, policy, price_col: str = "ssp") -> pd.DataFrame:
    """Walk every period in df (sorted by start_time) and apply the policy.

    Discharging sells STEP_MWH at the realised price. Charging buys STEP_MWH / EFF... we put
    the loss on the way out instead: charge stores STEP_MWH, discharge delivers STEP_MWH * EFF.
    """
    soc = 0.0
    day = None
    day_pnl = 0.0
    halted = False
    out = []
    for row in df.itertuples(index=False):
        t = row.start_time
        if day != t.date():
            day, day_pnl, halted = t.date(), 0.0, False
        a = 0 if halted else int(policy(row, soc))
        price = getattr(row, price_col)
        pnl = 0.0
        if a == 1 and soc >= STEP_MWH:
            soc -= STEP_MWH
            pnl = STEP_MWH * EFF * price - STEP_MWH * WEAR
        elif a == -1 and soc + STEP_MWH <= CAP_MWH:
            soc += STEP_MWH
            pnl = -STEP_MWH * price - STEP_MWH * WEAR
        else:
            a = 0
        day_pnl += pnl
        if day_pnl < -DAILY_LOSS_LIMIT:
            halted = True
        out.append((t, a, soc, pnl))
    return pd.DataFrame(out, columns=["start_time", "action", "soc", "pnl"])


# ------------------------------------------------------------------ policies

def fixed_cycle(charge_hours=(1, 2, 3, 4), discharge_hours=(17, 18, 19, 20)):
    """The tilt: charge in cheap overnight hours, discharge in the evening peak. No forecast."""
    def policy(row, soc):
        h = row.start_time.hour
        if h in charge_hours:
            return -1
        if h in discharge_hours:
            return 1
        return 0
    return policy


def persistence_rule():
    """Discharge if t-4 was short, charge if it was long."""
    def policy(row, soc):
        s = row.short_lag4
        if s != s:        # NaN
            return 0
        return 1 if s == 1 else -1
    return policy


def threshold_rule(p_col="p_short", hi=0.65, lo=0.35):
    """Point-forecast policy, simplest form: act when P(short) is confident."""
    def policy(row, soc):
        p = getattr(row, p_col)
        if p >= hi:
            return 1
        if p <= lo:
            return -1
        return 0
    return policy


def oracle():
    """Perfect foresight on the sign of the imbalance. The ceiling for the DP to chase."""
    def policy(row, soc):
        return 1 if row.short == 1 else -1
    return policy


# TODO (after the 18:00 gate): point_dp(horizon=12) and distribution_dp(two-state chain)
# as value iteration over soc in {0, 0.5, ..., 2} using price_p50 / per-state quantiles.
