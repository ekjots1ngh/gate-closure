"""Gate Closure: forecast whether the GB grid is short or long, trade a battery on it.

The timing rules every module shares. Period t starts at T (UTC) and lasts 30 minutes.
"""

from datetime import timedelta

GATE_CLOSURE = timedelta(minutes=60)   # the decision for period t is made at T - 60 min
PERIOD = timedelta(minutes=30)
PRICE_LAG_PERIODS = 4                   # newest price normally public at the gate is t-4's

# When a price was first public. Until February 2024 Elexon's created_at is the first print
# (median 52 minutes after the period starts, 99th percentile about two hours). From February
# 2024 each price is refreshed with a revised value about a day later and created_at moves with
# it, so the first-print time is no longer recorded; for those rows the median delay is assumed.
FIRST_PRINT_DELAY = timedelta(minutes=52)
REFRESHED_AFTER = timedelta(hours=6)    # a created_at later than this after the start is a refresh
