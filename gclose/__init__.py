"""Gate Closure: forecast whether the GB grid is short or long, trade a battery on it."""

from datetime import timedelta

GATE_CLOSURE = timedelta(minutes=60)   # decision happens this long before the period starts
PERIOD = timedelta(minutes=30)
PRICE_LAG_PERIODS = 4                   # newest price known at gate closure is for t-4
