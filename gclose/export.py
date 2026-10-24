"""Write web/public/replay.json: everything the demo shows, precomputed so it runs offline.

Replay week, chosen by a rule stated on screen and applied without looking at our P&L:
the calendar week (Monday to Sunday, UTC) of 2026 test data with the largest range of
system prices.

Run: python -m gclose.export   (needs walkforward.parquet and features.parquet)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import decide
from . import GATE_CLOSURE
from .backtest import OUT, TRAIN_END
from .features import FEATURES

WEB = Path(__file__).resolve().parent.parent / "web" / "public"
TAPE_POLICIES = {"ours": "chain_ours", "tilt": "chain_tilt", "oracle": "chain_oracle"}


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame to JSON-ready records, with NaN as null (json.dumps would write invalid NaN)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def replay_week(rows: pd.DataFrame) -> pd.Period:
    utc = rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    weeks = utc.dt.to_period("W-SUN")
    in_2026 = utc >= pd.Timestamp("2026-01-05")          # first Monday of 2026
    return rows[in_2026].groupby(weeks[in_2026])["ssp"].agg(np.ptp).idxmax()


def tape(book: decide.Book, sims: dict, f: pd.DataFrame, sel: np.ndarray) -> list[dict]:
    """One record per half hour of the replay week: price, forecasts, and each battery's move."""
    r = book.rows[sel]
    drivers = r[["start_time"]].merge(f[["start_time", "wind_revision", "demand_revision"]], on="start_time", how="left")
    flat = pd.DataFrame({
        "t": r["start_time"].dt.strftime("%Y-%m-%dT%H:%MZ").to_numpy(),
        "price": r["ssp"].round(2).to_numpy(),
        "short": r["short"].to_numpy(),
        "p_ours": r["p_ours"].round(3).to_numpy(),
        "p_persistence": r["p_persistence_cal"].round(3).to_numpy(),
        "p_neso": r["p_indicated"].round(3).to_numpy(),
        "wind_revision_mw": drivers["wind_revision"].round(0).to_numpy(),
        "demand_revision_mw": drivers["demand_revision"].round(0).to_numpy(),
    })
    out = _records(flat)
    for key, name in TAPE_POLICIES.items():
        moves = pd.DataFrame({k: sims[name][k][sel] for k in ("action", "soc", "pnl")}).round({"pnl": 2})
        for rec, move in zip(out, _records(moves)):
            rec[key] = move
    return out


def real_poison_test(book: decide.Book, week_start: pd.Timestamp) -> dict:
    """Poison the real raw data after a mid-week cutoff, rebuild, and count what changed.

    Checks inputs, forecasts and the battery's decisions for every half hour decided before
    the cutoff. A 17-day window keeps it to seconds and stops before the holdout; the model
    is the one fitted for the replay month, exactly as in the walk-forward.
    """
    from .features import build, poison
    from .ingest import load
    from .models import Ours

    lo, hi = week_start - pd.Timedelta(days=14), min(week_start + pd.Timedelta(days=9), TRAIN_END)
    raw = [load(d) for d in ("prices", "WINDFOR", "NDF", "IMBALNGC")]
    raw = [d[(d["start_time"] >= lo) & (d["start_time"] < hi)] for d in raw]
    cutoff = week_start + pd.Timedelta(days=3.5)
    clean, dirty = build(*raw), build(*poison(*raw, cutoff, seed=7))

    month0 = week_start.replace(day=1)
    full = pd.read_parquet(OUT / "features.parquet")
    model = Ours().fit(full[full["created_at"] < month0 - GATE_CLOSURE])
    decided = clean["start_time"] - GATE_CLOSURE                 # the protocol's gate, not the code's
    before = ((clean["start_time"] >= week_start) & (decided < cutoff)).to_numpy()
    after = (decided >= cutoff + pd.Timedelta(hours=2)).to_numpy()
    same = lambda a, b: np.isclose(np.nan_to_num(a.to_numpy(dtype=float)), np.nan_to_num(b.to_numpy(dtype=float)))
    p_clean, p_dirty = model.predict_proba(clean[before]), model.predict_proba(dirty[before])

    # Decisions: the same optimiser and tables the backtest uses, fed each set of forecasts.
    idx = np.flatnonzero(book.rows["start_time"].isin(clean.loc[before, "start_time"]))
    sub = book.subset(idx)
    order = clean.loc[before, "start_time"].reset_index(drop=True)
    align = lambda p: pd.Series(p, index=order).reindex(sub.rows["start_time"]).to_numpy()
    acts = [sub.chain(align(p)).argmax(-1) for p in (p_clean, p_dirty)]   # best action at every SoC level

    return {
        "cutoff": cutoff.strftime("%Y-%m-%dT%H:%MZ"),
        "decisions_checked": int(before.sum()),
        "features_changed": int((~same(clean.loc[before, FEATURES], dirty.loc[before, FEATURES])).any(axis=1).sum()),
        "forecasts_changed": int((~np.isclose(p_clean, p_dirty)).sum()),
        "decisions_changed": int((acts[0] != acts[1]).any(axis=1).sum()),
        "rows_after_cutoff_poisoned": int((~same(clean.loc[after, "wind_latest"], dirty.loc[after, "wind_latest"])).sum()),
    }


def main() -> None:
    book, sims, daily, results = decide.run()
    f = pd.read_parquet(OUT / "features.parquet")
    week = replay_week(book.rows)
    sel = (book.rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("W-SUN") == week).to_numpy()
    week_start = pd.Timestamp(week.start_time, tz="UTC")
    poison_result = real_poison_test(book, week_start)
    print("poison test:", poison_result)

    out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "test_period": "2022-07 to 2026-06 (walk-forward, monthly retrain)",
            "replay_week": str(week),
            "replay_rule": "The 2026 test week with the largest range of system prices, chosen without looking at our P&L.",
            "battery": "1 MW / 2 MWh, 85% round trip, GBP 5/MWh wear, daily loss limit GBP 500",
            "decision_time": "One hour before each half hour (gate closure); newest known price is four periods old.",
            "tape_policies": TAPE_POLICIES,
        },
        "tape": tape(book, sims, f, sel),
        "poison": poison_result,
        **results,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "replay.json").write_text(json.dumps(out, indent=1))
    prices = book.realised[sel]
    print(f"wrote {WEB / 'replay.json'}: week {week}, {sel.sum()} periods, price {prices.min():.0f} to {prices.max():.0f}")


if __name__ == "__main__":
    main()
