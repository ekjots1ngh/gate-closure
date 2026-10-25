"""The holdout: 1 July to 23 October 2026, opened once, after the freeze.

The frozen recipe runs exactly as the walk-forward did (monthly refits on what was public at
each month's first gate, the same optimiser, the same summaries) over months the research never
looked at. Opening it writes docs/HOLDOUT.md and data/out/holdout.json; the command refuses to
run a second time once docs/HOLDOUT.md exists.

Run: python -m gclose.holdout   (once, on Sunday morning)
"""

from __future__ import annotations

import json

import pandas as pd

from . import DOCS, OUT, price_models, report
from .backtest import ladder, walk_forward
from .decide import TestPeriods, rounded, study
from .features import load_table

FIRST_MONTH, LAST_MONTH = "2026-07", "2026-10"
END = pd.Timestamp("2026-10-24", tz="UTC")  # data to 23 October inclusive, as protocolled
REPORT = DOCS / "HOLDOUT.md"
RESULTS = OUT / "holdout.json"


def main() -> None:
    if REPORT.exists():
        raise SystemExit(f"the holdout has already been opened once: {REPORT}")
    opened_at = pd.Timestamp.now(tz="UTC")
    table = load_table()
    table = table[table["start_time"] < END]
    forecasts = walk_forward(table, ladder, FIRST_MONTH, LAST_MONTH, end=None)
    price_forecasts = walk_forward(table, price_models.fit_predict, FIRST_MONTH, LAST_MONTH, end=None)
    results = study(TestPeriods.build(table, forecasts, price_forecasts)).results
    RESULTS.write_text(json.dumps(rounded(results), indent=1), encoding="utf-8")
    scope = (
        f"Opened once, at {opened_at:%Y-%m-%d %H:%M} UTC, by `python -m gclose.holdout`; do not edit by hand.\n"
        f"Holdout, 1 July to 23 October 2026, with the frozen recipe; {len(forecasts):,} half hours."
    )
    REPORT.write_text(report.render(rounded(results), title="Holdout", scope=scope), encoding="utf-8")
    ours, schedule = results["money"]["chain/ours"], results["money"]["chain/schedule"]
    gain = results["gain"]["chain/ours"]["gbp"]
    print(
        f"holdout: chain/ours GBP {ours['value']:.1f}/day vs schedule {schedule['value']:.1f}; "
        f"gain {gain['value']:+.2f} [{gain['lo']:+.2f}, {gain['hi']:+.2f}]; wrote {REPORT}"
    )


if __name__ == "__main__":
    main()
