"""Write web/public/replay.json: everything the demo shows, precomputed so it runs offline.

Replay week selection rule (stated on screen, chosen without looking at our P&L): the
calendar week (Mon to Sun, UTC) inside the walk-forward test period from January 2026
that has the largest range of system prices.

Run: python -m gclose.export
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import decide
from .backtest import headline

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "out"
WEB = ROOT / "web" / "public"


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def real_poison_test(week_start: pd.Timestamp, week_end: pd.Timestamp) -> dict:
    """Poison everything published after a cutoff mid-week, rebuild features and decisions, count changes.

    Uses a 21-day window of the real raw data so it runs in seconds; the model is the one
    fitted on everything before the replay month, exactly as in the walk-forward.
    """
    from .features import build, poison
    from .ingest import load
    from .models import Ours

    lo, hi = week_start - pd.Timedelta(days=14), week_end + pd.Timedelta(days=3)
    pr, wf, nd, im = (load(d) for d in ("prices", "WINDFOR", "NDF", "IMBALNGC"))
    clip = lambda d: d[(d["start_time"] >= lo) & (d["start_time"] < hi)]
    pr, wf, nd, im = clip(pr), clip(wf), clip(nd), clip(im)
    cutoff = week_start + (week_end - week_start) / 2
    clean = build(pr, wf, nd, im)
    dirty = build(*poison(pr, wf, nd, im, cutoff, seed=7))

    full = pd.read_parquet(OUT / "features.parquet")
    month0 = pd.Timestamp(week_start.strftime("%Y-%m-01"), tz="UTC")
    model = Ours().fit(full[full["start_time"] < month0])
    keep = (clean["start_time"] >= week_start) & (clean["gate"] < cutoff)
    from .features import FEATURES
    a, b = clean.loc[keep, FEATURES].reset_index(drop=True), dirty.loc[keep, FEATURES].reset_index(drop=True)
    p_clean, p_dirty = model.predict_proba(clean.loc[keep]), model.predict_proba(dirty.loc[keep])
    feat_changed = int((~np.isclose(a.fillna(0).to_numpy(), b.fillna(0).to_numpy())).any(axis=1).sum())
    after = (clean["gate"] >= cutoff + pd.Timedelta(hours=2))
    bitten = int((~np.isclose(clean.loc[after, "wind_latest"].fillna(0), dirty.loc[after, "wind_latest"].fillna(0))).sum())
    return {
        "cutoff": cutoff.strftime("%Y-%m-%dT%H:%MZ"),
        "decisions_checked": int(keep.sum()),
        "features_changed": feat_changed,
        "forecasts_changed": int((~np.isclose(p_clean, p_dirty)).sum()),
        "rows_after_cutoff_poisoned": bitten,
    }


def main():
    preds = pd.read_csv(OUT / "walkforward.csv")
    preds["start_time"] = pd.to_datetime(preds["start_time"], utc=True)
    f = pd.read_parquet(OUT / "features.parquet")
    rows, expected, V, mix = decide.prepare(preds, f)
    sims = {name: decide.run_policy(rows, e, V) for name, e in expected.items()}
    D = pd.DataFrame({name: decide.daily(s) for name, s in sims.items()})

    # Replay week: largest price range among 2026 test weeks.
    r = rows[rows["start_time"] >= pd.Timestamp("2026-01-05", tz="UTC")].copy()
    r["week"] = r["start_time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("W-SUN")
    rng = r.groupby("week")["ssp"].agg(lambda s: s.max() - s.min())
    week = rng.idxmax()
    sel = rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("W-SUN") == week
    w = rows[sel].reset_index(drop=True)
    fw = f.set_index("start_time").loc[w["start_time"]].reset_index()
    tape = []
    for i in range(len(w)):
        idx = w.index[i]
        tape.append({
            "t": w.loc[i, "start_time"].strftime("%Y-%m-%dT%H:%MZ"),
            "price": _r(w.loc[i, "ssp"]),
            "short": int(w.loc[i, "short"]),
            "p_ours": _r(w.loc[i, "p_ours"], 3),
            "p_persistence": _r(w.loc[i, "p_persistence_cal"], 3),
            "p_neso": _r(w.loc[i, "p_indicated"], 3),
            "wind_revision_mw": _r(fw.loc[i, "wind_revision"], 0),
            "demand_revision_mw": _r(fw.loc[i, "demand_revision"], 0),
            "ours": {"action": int(sims["ours"].loc[sel.to_numpy()].iloc[i]["action"]),
                     "soc": _r(sims["ours"].loc[sel.to_numpy()].iloc[i]["soc"]),
                     "pnl": _r(sims["ours"].loc[sel.to_numpy()].iloc[i]["pnl"])},
            "tilt": {"action": int(sims["tilt"].loc[sel.to_numpy()].iloc[i]["action"]),
                     "soc": _r(sims["tilt"].loc[sel.to_numpy()].iloc[i]["soc"]),
                     "pnl": _r(sims["tilt"].loc[sel.to_numpy()].iloc[i]["pnl"])},
            "oracle": {"action": int(sims["oracle_sign"].loc[sel.to_numpy()].iloc[i]["action"]),
                       "soc": _r(sims["oracle_sign"].loc[sel.to_numpy()].iloc[i]["soc"]),
                       "pnl": _r(sims["oracle_sign"].loc[sel.to_numpy()].iloc[i]["pnl"])},
        })

    money = []
    for name in D.columns:
        lo, hi = decide.bootstrap_weeks(D, lambda d, c=name: d[c].mean(), n=500)
        money.append({"policy": name, "gbp_per_day": _r(D[name].mean(), 1), "lo": _r(lo, 1), "hi": _r(hi, 1)})
    share = lambda d: (d["ours"].mean() - d["tilt"].mean()) / (d["oracle_sign"].mean() - d["tilt"].mean())
    slo, shi = decide.bootstrap_weeks(D, share, n=500)

    brier = headline(preds)
    wk0 = pd.Timestamp(str(week.start_time.date()), tz="UTC")
    poison_result = real_poison_test(wk0, wk0 + pd.Timedelta(days=7))
    print("poison test:", poison_result)
    curve = pd.read_csv(OUT / "skill_curve.csv")

    out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "test_period": "2022-07 to 2026-06 (walk-forward, monthly retrain)",
            "replay_week": str(week),
            "replay_rule": "The 2026 test week with the largest range of system prices, chosen without looking at our P&L.",
            "battery": "1 MW / 2 MWh, 85% round trip, GBP 5/MWh wear, daily loss limit GBP 500",
            "decision_time": "One hour before each half hour (gate closure); newest known price is four periods old.",
        },
        "tape": tape,
        "brier": brier.to_dict(orient="records"),
        "money": money,
        "share_of_gap": {"ours": _r(share(D), 4), "lo": _r(slo, 4), "hi": _r(shi, 4)},
        "skill_curve": curve.to_dict(orient="records"),
        "poison": poison_result,
        "by_year": D.assign(year=pd.to_datetime(D.index).year).groupby("year")[["tilt", "persistence", "indicated", "ours", "oracle_sign"]]
                    .mean().round(1).reset_index().to_dict(orient="records"),
    }
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "replay.json").write_text(json.dumps(out, indent=1))
    print(f"wrote {WEB / 'replay.json'}: replay week {week}, {len(tape)} periods, "
          f"price range {w['ssp'].min():.0f} to {w['ssp'].max():.0f}")


if __name__ == "__main__":
    main()
