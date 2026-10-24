"""The walk-forward: every forecaster refitted each month on what was public before it.

Each test month, a forecaster is fitted on every outcome public at that month's first gate and
scored on the month itself. The holdout (from HOLDOUT_START) is never touched here. The same
driver runs the boosted and ridge checks in gclose.price_models.

Run: python -m gclose.backtest   ->  data/out/forecasts.parquet, and the forecast scores
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import NamedTuple

import numpy as np
import pandas as pd

from . import FIRST_TEST_MONTH, GATE_LEAD, HOLDOUT_START, LAST_TEST_MONTH, OUT, stats
from .features import load_table
from .models import LADDER

FORECASTS = OUT / "forecasts.parquet"

FitPredict = Callable[[pd.DataFrame, pd.DataFrame], dict[str, np.ndarray]]


class Split(NamedTuple):
    month: str
    train: pd.Series  # boolean mask: outcomes public at the month's first gate
    test: pd.Series  # boolean mask: the month's half hours


def monthly_splits(table: pd.DataFrame, first: str, last: str) -> Iterator[Split]:
    """One split per month from `first` to `last` ("YYYY-MM"), oldest first.

    A row is a training row if its stored price was created before the month's first gate,
    T0 - GATE_LEAD, so the refit learns only outcomes that were public by then.
    """
    for month in pd.period_range(first, last, freq="M"):
        t0 = month.start_time.tz_localize("UTC")
        t1 = (month + 1).start_time.tz_localize("UTC")
        yield Split(
            str(month), table["created_at"] < t0 - GATE_LEAD, (table["start_time"] >= t0) & (table["start_time"] < t1)
        )


def walk_forward(
    table: pd.DataFrame,
    fit_predict: FitPredict,
    first: str = FIRST_TEST_MONTH,
    last: str = LAST_TEST_MONTH,
    end: pd.Timestamp | None = HOLDOUT_START,
) -> pd.DataFrame:
    """Out-of-sample columns from `fit_predict(train, test)` for every month from `first` to `last`, stacked.

    Rows from `end` onwards are dropped first, so by default the walk-forward cannot see the
    holdout at all; only gclose.holdout passes end=None.
    """
    if end is not None:
        table = table[table["start_time"] < end]
    months = []
    for split in monthly_splits(table, first, last):
        test = table[split.test]
        months.append(test[["start_time", "short", "ssp"]].assign(**fit_predict(table[split.train], test)))
    return pd.concat(months, ignore_index=True)


def ladder(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    """P(short) from every forecaster in the protocol's ladder."""
    return {f"p_{name}": forecaster().fit(train).predict_proba(test) for name, forecaster in LADDER.items()}


def scores(forecasts: pd.DataFrame) -> list[dict]:
    """Brier and log loss for every forecaster in the ladder, with paired intervals against ours."""
    probs = {name: forecasts[f"p_{name}"].to_numpy() for name in LADDER}
    return stats.forecast_scores(forecasts["short"].to_numpy(), probs, stats.week_index(forecasts["start_time"]))


def main() -> None:
    forecasts = walk_forward(load_table(), ladder)
    forecasts.to_parquet(FORECASTS, index=False)
    print(f"walk-forward {FIRST_TEST_MONTH} to {LAST_TEST_MONTH}, {len(forecasts):,} half hours")
    for s in scores(forecasts):
        b, d = s["brier"], s["ours_minus"]
        print(
            f"  {s['model']:16s} Brier {b['value']:.4f} [{b['lo']:.4f}, {b['hi']:.4f}]   "
            f"log loss {s['log_loss']:.4f}   ours minus {d['value']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]"
        )


if __name__ == "__main__":
    main()
