"""Decision layer: one optimiser, many forecasts.

Every policy is the same dynamic programme; only the expected price for the period being
decided changes. That isolates what the forecast is worth.

At gate closure for period t (slot s = half hour of day, UTC):
  * E[price_t] = p_short * mu_short[s] + (1 - p_short) * mu_long[s]
    where mu_short / mu_long are trailing-90-day mean prices by slot and state, computed only
    from periods that settled before the test month began (no lookahead).
  * The value of what is left in the battery after period t comes from a backward induction
    over the next 47 half hours on the trailing-90-day unconditional slot profile.
  * Pick charge / hold / discharge maximising immediate cash + continuation value.

Policies:
  tilt          p_short unused: E[price_t] = unconditional profile. The no-forecast benchmark.
  persistence   p from calibrated persistence (P(short_t | short_{t-4})).
  indicated     p from NESO's indicated imbalance, recalibrated.
  ours          p from our logistic model.
  oracle_sign   p = realised short (0/1): perfect knowledge of the side, not the price.
  oracle_price  E[price_t] = realised price: the ceiling for a one-period decision.

Run: python -m gclose.decide   (needs data/out/walkforward.csv and data/out/features.parquet)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .battery import CAP_MWH, DAILY_LOSS_LIMIT, EFF, STEP_MWH, WEAR

OUT = Path(__file__).resolve().parent.parent / "data" / "out"
SOC = np.round(np.arange(0, CAP_MWH + 1e-9, STEP_MWH), 3)          # 0, 0.5, ..., 2.0
K = len(SOC)
HORIZON = 47
LOOKBACK_DAYS = 90


def _rewards(price: float) -> np.ndarray:
    """Cash for (discharge, hold, charge) at this price, per half-hour step."""
    return np.array([STEP_MWH * (EFF * price - WEAR), 0.0, -STEP_MWH * (price + WEAR)])


def _bellman(v_next: np.ndarray, price: float) -> np.ndarray:
    r = _rewards(price)
    v = np.full(K, -np.inf)
    for k in range(K):
        v[k] = max(v[k], r[1] + v_next[k])                       # hold
        if k > 0:
            v[k] = max(v[k], r[0] + v_next[k - 1])               # discharge
        if k < K - 1:
            v[k] = max(v[k], r[2] + v_next[k + 1])               # charge
    return v


def value_tables(profile: np.ndarray) -> np.ndarray:
    """V[s] = value of each SoC level at the start of slot s, planning HORIZON steps on the profile."""
    V = np.zeros((48, K))
    for s0 in range(48):
        v = np.zeros(K)
        for h in reversed(range(HORIZON)):
            v = _bellman(v, profile[(s0 + h) % 48])
        V[s0] = v
    return V


def slot(ts: pd.Series) -> pd.Series:
    return ts.dt.hour * 2 + ts.dt.minute // 30


def month_tables(f: pd.DataFrame, month_start: pd.Timestamp):
    """Trailing-90-day profiles from periods that settled before month_start."""
    hist = f[(f["start_time"] < month_start - pd.Timedelta(hours=1)) &
             (f["start_time"] >= month_start - pd.Timedelta(days=LOOKBACK_DAYS))]
    s = slot(hist["start_time"])
    prof = hist.groupby(s)["ssp"].mean().reindex(range(48)).interpolate().bfill().ffill().to_numpy()
    mu_s = hist[hist["short"] == 1].groupby(s[hist["short"] == 1])["ssp"].mean().reindex(range(48)).fillna(pd.Series(prof)).to_numpy()
    mu_l = hist[hist["short"] == 0].groupby(s[hist["short"] == 0])["ssp"].mean().reindex(range(48)).fillna(pd.Series(prof)).to_numpy()
    return prof, mu_s, mu_l, value_tables(prof)


def run_policy(rows: pd.DataFrame, exp_price: np.ndarray, V_by_month: dict) -> pd.DataFrame:
    """Simulate one policy over all rows in time order. rows needs start_time, ssp, month, slot_next."""
    soc_k, day, day_pnl, halted = 0, None, 0.0, False
    pnl = np.zeros(len(rows))
    act = np.zeros(len(rows), dtype=int)
    socs = np.zeros(len(rows))
    months = rows["month"].to_numpy()
    nxt = rows["slot_next"].to_numpy()
    realised = rows["ssp"].to_numpy()
    days = rows["start_time"].dt.date.to_numpy()
    for i in range(len(rows)):
        if days[i] != day:
            day, day_pnl, halted = days[i], 0.0, False
        a = 0
        if not halted:
            v_next = V_by_month[months[i]][nxt[i]]
            r = _rewards(exp_price[i])
            best, a = r[1] + v_next[soc_k], 0
            if soc_k > 0 and r[0] + v_next[soc_k - 1] > best:
                best, a = r[0] + v_next[soc_k - 1], 1
            if soc_k < K - 1 and r[2] + v_next[soc_k + 1] > best:
                best, a = r[2] + v_next[soc_k + 1], -1
        cash = _rewards(realised[i])[{1: 0, 0: 1, -1: 2}[a]]
        soc_k -= a
        pnl[i], act[i], socs[i] = cash, a, SOC[soc_k]
        day_pnl += cash
        if day_pnl < -DAILY_LOSS_LIMIT:
            halted = True
    return pd.DataFrame({"start_time": rows["start_time"].to_numpy(), "action": act, "pnl": pnl, "soc": socs})


def prepare(preds: pd.DataFrame, f: pd.DataFrame):
    """Attach month keys, next-slot index and per-month tables; return rows plus E[price] per policy."""
    rows = preds.sort_values("start_time").reset_index(drop=True).copy()
    rows["month"] = rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M").astype(str)
    rows["slot"] = slot(rows["start_time"])
    rows["slot_next"] = (rows["slot"] + 1) % 48
    tables = {}
    for m in rows["month"].unique():
        start = pd.Timestamp(m + "-01", tz="UTC")
        tables[m] = month_tables(f, start)
    prof = np.array([tables[m][0][s] for m, s in zip(rows["month"], rows["slot"])])
    mu_s = np.array([tables[m][1][s] for m, s in zip(rows["month"], rows["slot"])])
    mu_l = np.array([tables[m][2][s] for m, s in zip(rows["month"], rows["slot"])])
    V = {m: t[3] for m, t in tables.items()}
    mix = lambda p: p * mu_s + (1 - p) * mu_l
    expected = {
        "tilt": prof,
        "persistence": mix(rows["p_persistence_cal"].to_numpy()),
        "indicated": mix(rows["p_indicated"].to_numpy()),
        "ours": mix(rows["p_ours"].to_numpy()),
        "oracle_sign": mix(rows["short"].to_numpy().astype(float)),
        "oracle_price": rows["ssp"].to_numpy(),
    }
    return rows, expected, V, mix


def daily(sim: pd.DataFrame) -> pd.Series:
    return sim.groupby(sim["start_time"].dt.tz_convert("UTC").dt.date)["pnl"].sum()


def bootstrap_weeks(daily_df: pd.DataFrame, stat, n=1000, seed=0):
    """Resample whole weeks of a daily table (columns = policies); return stat's 5% and 95%."""
    rng = np.random.default_rng(seed)
    weeks = pd.to_datetime(daily_df.index).to_period("W").to_numpy()
    uniq = np.unique(weeks)
    idx = {w: np.where(weeks == w)[0] for w in uniq}
    vals = []
    for _ in range(n):
        pick = np.concatenate([idx[w] for w in rng.choice(uniq, size=len(uniq), replace=True)])
        vals.append(stat(daily_df.iloc[pick]))
    return float(np.quantile(vals, 0.05)), float(np.quantile(vals, 0.95))


def main():
    preds = pd.read_csv(OUT / "walkforward.csv", parse_dates=["start_time"])
    preds["start_time"] = pd.to_datetime(preds["start_time"], utc=True)
    f = pd.read_parquet(OUT / "features.parquet")
    rows, expected, V, mix = prepare(preds, f)

    sims = {name: run_policy(rows, e, V) for name, e in expected.items()}
    D = pd.DataFrame({name: daily(s) for name, s in sims.items()})
    D.to_csv(OUT / "daily_pnl.csv")

    table = []
    for name in D.columns:
        lo, hi = bootstrap_weeks(D, lambda d, c=name: d[c].mean())
        trades = (sims[name]["action"] != 0).mean()
        table.append({"policy": name, "gbp_per_day": round(D[name].mean(), 1), "lo": round(lo, 1), "hi": round(hi, 1),
                      "active_share": round(trades, 3)})
    print(pd.DataFrame(table).to_string(index=False))

    share = lambda d: (d["ours"].mean() - d["tilt"].mean()) / (d["oracle_sign"].mean() - d["tilt"].mean())
    lo, hi = bootstrap_weeks(D, share)
    print(f"\nours closes {share(D):.1%} of the tilt-to-oracle_sign gap  [90% interval {lo:.1%}, {hi:.1%}]")
    for b in ("persistence", "indicated"):
        s = lambda d, b=b: (d[b].mean() - d["tilt"].mean()) / (d["oracle_sign"].mean() - d["tilt"].mean())
        print(f"{b:11s} closes {s(D):.1%}")

    # Same thing by year, and without the top 1% of days by |pnl| of the oracle, so spikes can't carry it.
    D.index = pd.to_datetime(D.index)
    print("\nby year, GBP/day:")
    print(D.groupby(D.index.year)[["tilt", "persistence", "indicated", "ours", "oracle_sign"]].mean().round(1).to_string())
    cut = D["oracle_sign"].abs().quantile(0.99)
    Dt = D[D["oracle_sign"].abs() <= cut]
    print(f"\nwithout top 1% days: ours closes {share(Dt):.1%}")

    # Value of skill: scale our errors from 0 (oracle) to 1.5x and rerun the same optimiser.
    y = rows["short"].to_numpy().astype(float)
    p = rows["p_ours"].to_numpy()
    curve = []
    for k in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5):
        pk = np.clip(y + k * (p - y), 0, 1)
        brier = float(np.mean((pk - y) ** 2))
        sim = run_policy(rows, mix(pk), V)
        curve.append({"k": k, "brier": round(brier, 4), "gbp_per_day": round(daily(sim).mean(), 1)})
    for b in ("p_coin", "p_persistence_cal", "p_indicated"):
        pb = rows[b].to_numpy()
        curve.append({"k": b, "brier": round(float(np.mean((pb - y) ** 2)), 4),
                      "gbp_per_day": round(D[{"p_coin": "tilt", "p_persistence_cal": "persistence", "p_indicated": "indicated"}[b]].mean(), 1)})
    C = pd.DataFrame(curve)
    C.to_csv(OUT / "skill_curve.csv", index=False)
    print("\nvalue of skill (k = multiple of our errors; 0 = oracle sign, 1 = ours):")
    print(C.to_string(index=False))


if __name__ == "__main__":
    main()
