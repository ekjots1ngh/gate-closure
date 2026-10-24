"""Gate Closure: forecast whether the GB grid will be short or long, and trade a battery on it.

Everything PROTOCOL.md fixes lives here, so no module carries its own copy: where files go, the
timing rules, and the test windows. Period t starts at T (UTC) and lasts 30 minutes.
"""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"  # Elexon data as pulled, committed to the repo
OUT = ROOT / "data" / "out"  # everything the pipeline computes, rebuilt on demand
DOCS = ROOT / "docs"  # rendered results and figures

# Timing. The decision for period t is made at its gate, T - GATE_LEAD.
GATE_LEAD = timedelta(minutes=60)
PERIODS_PER_DAY = 48
PRICE_LAG_PERIODS = 4  # the newest price normally public at the gate is t-4's

# When a price was first public. Until February 2024 Elexon's created_at is the first print
# (median 52 minutes after the period starts, 99th percentile about two hours). From February
# 2024 each price is refreshed with a revised value about a day later and created_at moves with
# it, so the first-print time is no longer recorded; for those rows the median delay is assumed.
FIRST_PRINT_DELAY = timedelta(minutes=52)
REFRESHED_AFTER = timedelta(hours=6)  # a created_at later than this after the start is a refresh
REVISED_PRICES_FROM = pd.Timestamp("2024-02-01", tz="UTC")

# Test windows (PROTOCOL.md amendment 1). The holdout starts at HOLDOUT_START and is never
# touched by the walk-forward.
FIRST_TEST_MONTH, LAST_TEST_MONTH = "2022-07", "2026-06"
HOLDOUT_START = pd.Timestamp("2026-07-01", tz="UTC")


def slot_of(times: pd.Series) -> np.ndarray:
    """Half hour of the UTC day, 0 to 47. Never settlement-period arithmetic: some days have 46 or 50."""
    return (times.dt.hour * 2 + times.dt.minute // 30).to_numpy()
