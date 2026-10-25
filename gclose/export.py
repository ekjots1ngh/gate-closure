"""Write web/public/replay.json: everything the demo shows, precomputed so it runs offline.

The replay week is chosen by a rule stated on screen and applied without looking at P&L: the
calendar week (Monday to Sunday, UTC) of 2026 test data with the widest range of system prices.

Run: python -m gclose.export   (after gclose.decide's inputs exist; reruns the study, about 10 s)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from . import FIRST_TEST_MONTH, LAST_TEST_MONTH, ROOT, battery, receipts
from .decide import Study, TestPeriods, rounded, run_study
from .features import load_table

REPLAY = ROOT / "web" / "public" / "replay.json"
REPLAY_YEAR = 2026
TAPE_POLICIES = {"ours": "chain/ours", "schedule": "chain/schedule", "side_oracle": "chain/side_oracle"}


def _records(df: pd.DataFrame) -> list[dict]:
    """JSON-ready records with NaN as null (json.dumps would otherwise write invalid NaN)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def _weeks(periods: TestPeriods) -> pd.Series:
    return periods.rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("W-SUN")


def replay_week(periods: TestPeriods) -> pd.Period:
    """The REPLAY_YEAR week with the widest range of settled prices, counting whole weeks only."""
    weeks = _weeks(periods)
    whole = weeks.map(lambda w: w.start_time.year == REPLAY_YEAR)
    return periods.rows[whole].groupby(weeks[whole])["ssp"].agg(np.ptp).idxmax()


# What the model saw at each gate, shown on the demo's map: forecast levels and their latest revisions.
DRIVERS = ("wind_latest", "wind_revision", "demand_latest", "demand_revision", "indicated_latest")


def tape(study: Study, week: np.ndarray) -> list[dict]:
    """One record per half hour of the replay week: price, forecasts, drivers, and each battery's move."""
    rows = study.periods.rows[week].reset_index(drop=True)
    drivers = rows[["start_time"]].merge(load_table()[["start_time", *DRIVERS]], on="start_time", how="left")
    records = _records(
        pd.DataFrame(
            {
                "t": rows["start_time"].map(pd.Timestamp.isoformat),
                "price": rows["ssp"],
                "short": rows["short"],
                "p_ours": rows["p_ours"],
                "p_persistence_cal": rows["p_persistence_cal"],
                "p_indicated": rows["p_indicated"],
                **{f"{name}_mw": drivers[name] for name in DRIVERS},
            }
        )
    )
    for key, policy in TAPE_POLICIES.items():
        trajectory = study.trajectories[policy]
        moves = pd.DataFrame(
            {"action": trajectory.action[week], "soc": trajectory.soc[week], "pnl": trajectory.pnl[week]}
        )
        for record, move in zip(records, _records(moves), strict=True):
            record[key] = move
    return records


def value_of_time() -> list[dict] | None:
    """The latency study's summary per decision time, if `python -m gclose.latency` has been run."""
    from .latency import LATENCY  # imported here: gclose.latency itself imports this module

    if not LATENCY.exists():
        return None
    return [
        {
            "minutes": lead["minutes"],
            "brier": {name: lead["brier"][name]["value"] for name in ("ours", "persistence_cal", "indicated")},
            "ours_gbp": lead["money"]["chain/ours"]["value"],
            "schedule_gbp": lead["money"]["chain/schedule"]["value"],
            "gain": lead["gain"],
        }
        for lead in json.loads(LATENCY.read_text(encoding="utf-8"))["leads"]
    ]


def main() -> None:
    study = run_study()
    week = replay_week(study.periods)
    in_week = (_weeks(study.periods) == week).to_numpy()
    poison = receipts.real_week(study.periods, pd.Timestamp(week.start_time, tz="UTC"))
    print("poison check on the replay week:", poison)

    replay = {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(timespec="minutes"),
            "test_period": f"{FIRST_TEST_MONTH} to {LAST_TEST_MONTH}, walk-forward, refitted monthly",
            "replay_week": str(week),
            "replay_rule": f"The {REPLAY_YEAR} week with the widest range of system prices, chosen without "
            "looking at P&L.",
            "battery": f"{battery.STEP * 2:g} MW / {battery.CAP:g} MWh, {battery.EFF:.0%} round trip, "
            f"GBP {battery.WEAR:g}/MWh wear, daily loss limit GBP {battery.DAILY_LOSS_LIMIT:g}",
            "tape_policies": TAPE_POLICIES,
        },
        "tape": tape(study, in_week),
        "poison": poison,
        "value_of_time": value_of_time(),
        **study.results,
    }
    REPLAY.parent.mkdir(parents=True, exist_ok=True)
    REPLAY.write_text(json.dumps(rounded(replay), indent=1), encoding="utf-8")
    prices = study.periods.realised[in_week]
    print(f"wrote {REPLAY}: week {week}, {in_week.sum()} half hours, price {prices.min():.0f} to {prices.max():.0f}")


if __name__ == "__main__":
    main()
