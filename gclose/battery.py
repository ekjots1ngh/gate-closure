"""The battery: physics, cash flows and the dynamic programme.

1 MW / 2 MWh, so one half-hour step moves 0.5 MWh and the state of charge (SoC) lives on
five levels: 0, 0.5, 1.0, 1.5, 2.0 MWh. Losses are taken on the way out (discharging 0.5 MWh
delivers 85% of it), wear costs GBP 5 per MWh moved in either direction, and once the day's
losses known at the gate pass GBP 500 the battery holds until midnight UTC. Known means
settled: the battery's cash for a period is known when that period's price prints, so at
each gate it sees its own P&L only up to period t-4, the same lag as every other price.

The optimiser is split in two because the two halves have different shapes:
  * Values ("what is each SoC level worth from here on") depend only on prices, never on
    the path the battery took, so they are computed for every period at once with numpy.
  * The path (SoC, the daily loss limit) is inherently sequential, so that loop does
    nothing but look up the best action for the current SoC.
"""

from __future__ import annotations

import numpy as np

from . import PRICE_LAG_PERIODS

STEP = 0.5                 # MWh moved per half hour at 1 MW
CAP = 2.0                  # MWh
EFF = 0.85                 # round-trip efficiency, applied on discharge
WEAR = 5.0                 # GBP per MWh moved
DAILY_LOSS_LIMIT = 500.0   # GBP; hold for the rest of the UTC day once breached

SOC = np.arange(0.0, CAP + STEP / 2, STEP)
K = len(SOC)

# Action order matters: argmax returns the first maximum, so ties resolve to hold,
# then discharge, then charge. A battery should never trade on a tie.
HOLD, DISCHARGE, CHARGE = 0, 1, 2
MOVE = np.array([0, -1, +1])        # change in SoC level for each action
LABEL = np.array([0, +1, -1])       # public convention: +1 discharge, -1 charge


def cash(price) -> np.ndarray:
    """Cash for (hold, discharge, charge) at `price`. Any shape in, shape + (3,) out."""
    price = np.asarray(price, dtype=float)
    return np.stack([np.zeros_like(price),
                     STEP * (EFF * price - WEAR),
                     -STEP * (price + WEAR)], axis=-1)


def q_values(v_next: np.ndarray, price) -> np.ndarray:
    """Q[..., k, a]: cash now plus the value of the SoC level that action a leads to.

    v_next has shape (..., K) and price broadcasts against (...). Moves past empty or
    full are -inf so they can never be chosen.
    """
    c = cash(price)[..., None, :]                                   # (..., 1, 3)
    q = np.full(v_next.shape + (3,), -np.inf)
    q[..., HOLD] = v_next
    q[..., 1:, DISCHARGE] = c[..., DISCHARGE] + v_next[..., :-1]
    q[..., :-1, CHARGE] = c[..., CHARGE] + v_next[..., 1:]
    return q


def bellman(v_next: np.ndarray, price) -> np.ndarray:
    """One step of backward induction: value of each SoC level before a period at `price`."""
    return q_values(v_next, price).max(axis=-1)


def value_tables(profile: np.ndarray, horizon: int = 47) -> np.ndarray:
    """V[s, k]: value of SoC level k at the start of half-hour slot s.

    Plans `horizon` steps ahead on a 48-slot daily price profile. All 48 starting slots are
    solved together, one vectorised Bellman step per lookahead step.
    """
    start = np.arange(48)
    v = np.zeros((48, K))
    for h in range(horizon - 1, -1, -1):
        v = bellman(v, profile[(start + h) % 48])
    return v


def hindsight_q(realised: np.ndarray) -> np.ndarray:
    """Q-values with every future price known: one backward pass over the whole series.

    No policy that decides at the gate can beat this; it is the ceiling, not a target.
    """
    q = np.empty((len(realised), K, 3))
    v = np.zeros(K)
    for i in range(len(realised) - 1, -1, -1):
        q[i] = q_values(v, realised[i])
        v = q[i].max(axis=-1)
    return q


def simulate(q: np.ndarray, realised: np.ndarray, day: np.ndarray):
    """Walk the battery through time.

    q:        (n, K, 3) Q-values per period, built from forecasts known at the gate.
    realised: (n,) settled prices; they decide the cash, never the action.
    day:      (n,) UTC date of each period, for the daily loss limit.
    Returns (action label, SoC after the period, cash) as three (n,) arrays.
    """
    best = q.argmax(axis=-1)            # (n, K): the best action for every SoC the battery could be at
    paid = cash(realised)               # (n, 3): what each action actually paid
    n = len(realised)
    action, soc, pnl = np.empty(n, dtype=np.int8), np.empty(n), np.zeros(n)
    k, today, first, known, halted = 0, None, 0, 0.0, False
    for i in range(n):
        if day[i] != today:
            today, first, known, halted = day[i], i, 0.0, False
        settled = i - PRICE_LAG_PERIODS  # newest period whose price, and so our cash, is known at this gate
        if settled >= first:
            known += pnl[settled]
        halted = halted or known < -DAILY_LOSS_LIMIT
        a = HOLD if halted else best[i, k]
        k += MOVE[a]
        pnl[i] = paid[i, a]
        action[i], soc[i] = LABEL[a], SOC[k]
    return action, soc, pnl
