"""Decision layer: one optimiser, many forecasts.

Every policy is the same dynamic programme over the battery's five SoC levels. Only the
information fed into it changes, so any difference in money is the forecast's doing.

What the optimiser knows at the gate for period t (slot s = half hour of the UTC day):
  * Trailing 90-day tables, from periods whose price was public at the test month's first
    gate: the mean price by slot (`profile`), the mean price by slot when short / when long
    (`mu_short`, `mu_long`), the share of short periods by slot (`pi`), and the lag-1
    autocorrelation of the side (`lam`). Note pi * mu_short + (1 - pi) * mu_long == profile.
  * A forecast: either P(short) for period t, turned into an expected price
    p * mu_short + (1 - p) * mu_long, or an expected price directly.

Two policy families:
  one-step   the forecast prices period t only; everything after is valued on the profile.
  chain      the forecast is also carried forward, because the side persists:
             p_{t+h} = pi[s+h] + (p - pi[s]) * lam^h for the next CHAIN_STEPS periods.
             lam is about 0.5, so the forecast's effect halves every half hour. With p = pi
             this is exactly the tilt.

Two reference points: `*_oracle` knows the side of period t in advance (but not its price,
nor anything later), and `hindsight` knows every price in advance: the true ceiling.

Run: python -m gclose.decide   ->  data/out/daily_pnl.parquet, data/out/results.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import GATE_CLOSURE, battery, stats
from .backtest import brier_table

OUT = Path(__file__).resolve().parent.parent / "data" / "out"
LOOKBACK = pd.Timedelta(days=90)
CHAIN_STEPS = 8
FIRST_PRINT_ERA_END = pd.Timestamp("2024-02-01")   # Elexon starts refreshing prices the next day


def slot_of(times: pd.Series) -> np.ndarray:
    """Half hour of the UTC day, 0..47."""
    return (times.dt.hour * 2 + times.dt.minute // 30).to_numpy()


@dataclass
class Tables:
    """Trailing-window tables stacked by test month: arrays are (months, 48[, K])."""
    profile: np.ndarray
    mu_short: np.ndarray
    mu_long: np.ndarray
    pi: np.ndarray
    lam: np.ndarray
    value: np.ndarray        # (months, 48, K) value of each SoC level at the start of each slot

    @classmethod
    def build(cls, f: pd.DataFrame, months: list[str]) -> "Tables":
        slots = pd.Index(range(48))
        parts = {k: [] for k in ("profile", "mu_short", "mu_long", "pi", "lam")}
        for m in months:
            start = pd.Timestamp(m + "-01", tz="UTC")
            # Only periods whose stored price was public at the month's first gate.
            hist = f[(f["start_time"] >= start - LOOKBACK) & (f["created_at"] < start - GATE_CLOSURE)]
            by = hist.groupby(slot_of(hist["start_time"]))
            profile = by["ssp"].mean().reindex(slots).interpolate().bfill().ffill()
            short = hist["short"] == 1
            mu_s = hist[short].groupby(slot_of(hist.loc[short, "start_time"]))["ssp"].mean().reindex(slots)
            mu_l = hist[~short].groupby(slot_of(hist.loc[~short, "start_time"]))["ssp"].mean().reindex(slots)
            side = hist["short"].to_numpy()
            parts["profile"].append(profile.to_numpy())
            parts["mu_short"].append(mu_s.fillna(profile).to_numpy())
            parts["mu_long"].append(mu_l.fillna(profile).to_numpy())
            parts["pi"].append(by["short"].mean().reindex(slots).fillna(0.5).to_numpy())
            parts["lam"].append(np.clip(np.corrcoef(side[1:], side[:-1])[0, 1], 0.0, 0.99))
        arrays = {k: np.array(v) for k, v in parts.items()}
        value = np.stack([battery.value_tables(p) for p in arrays["profile"]])
        return cls(value=value, **arrays)


@dataclass
class Book:
    """The test periods in time order, with everything the policies index by."""
    rows: pd.DataFrame
    tables: Tables
    m: np.ndarray            # month index into tables
    s: np.ndarray            # slot
    day: np.ndarray          # UTC day number, for the loss limit and daily P&L
    realised: np.ndarray     # settled price; decides cash, never actions

    @classmethod
    def build(cls, preds: pd.DataFrame, f: pd.DataFrame) -> "Book":
        rows = preds.sort_values("start_time").reset_index(drop=True)
        utc = rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None)
        month = utc.dt.to_period("M").astype(str)
        months = sorted(month.unique())
        return cls(rows=rows, tables=Tables.build(f, months),
                   m=month.map({k: i for i, k in enumerate(months)}).to_numpy(),
                   s=slot_of(rows["start_time"]),
                   day=(utc.dt.normalize() - pd.Timestamp("1970-01-01")).dt.days.to_numpy(),
                   realised=rows["ssp"].to_numpy())

    def subset(self, idx: np.ndarray) -> "Book":
        """The same book restricted to some rows (tables unchanged)."""
        return Book(self.rows.iloc[idx].reset_index(drop=True), self.tables,
                    self.m[idx], self.s[idx], self.day[idx], self.realised[idx])

    def expected(self, p: np.ndarray, ahead: int = 0) -> np.ndarray:
        """Expected price `ahead` periods after each row, given P(short) for that period."""
        s = (self.s + ahead) % 48
        t = self.tables
        return p * t.mu_short[self.m, s] + (1 - p) * t.mu_long[self.m, s]

    def one_step(self, price_now: np.ndarray) -> np.ndarray:
        """Q-values when the forecast informs period t only."""
        v_next = self.tables.value[self.m, (self.s + 1) % 48]
        return battery.q_values(v_next, price_now)

    def chain(self, p: np.ndarray) -> np.ndarray:
        """Q-values when P(short) is also carried CHAIN_STEPS periods forward."""
        t = self.tables
        v = t.value[self.m, (self.s + CHAIN_STEPS) % 48]
        base = t.pi[self.m, self.s]
        for h in range(CHAIN_STEPS - 1, 0, -1):
            p_h = np.clip(t.pi[self.m, (self.s + h) % 48] + (p - base) * t.lam[self.m] ** h, 0, 1)
            v = battery.bellman(v, self.expected(p_h, ahead=h))
        return battery.q_values(v, self.expected(p))

    def run(self, q: np.ndarray) -> dict[str, np.ndarray]:
        action, soc, pnl = battery.simulate(q, self.realised, self.day)
        return {"action": action, "soc": soc, "pnl": pnl}

    def daily(self, pnl: np.ndarray) -> pd.Series:
        days, idx = np.unique(self.day, return_inverse=True)
        return pd.Series(np.bincount(idx, weights=pnl), index=pd.to_datetime(days, unit="D"))


def _aligned(book: Book, path: Path, cols: list[str]) -> pd.DataFrame | None:
    """Columns of another output file, aligned to the book's rows, or None if not built yet."""
    if not path.exists():
        return None
    return book.rows[["start_time"]].merge(pd.read_parquet(path)[["start_time", *cols]], on="start_time", how="left")


def run_policies(book: Book, f: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    """Every policy in the study. Names: <family>_<forecast>, price_<forecast>, hindsight."""
    t, r = book.tables, book.rows
    profile = t.profile[book.m, book.s]
    sides = {"persistence": r["p_persistence_cal"].to_numpy(), "indicated": r["p_indicated"].to_numpy(),
             "ours": r["p_ours"].to_numpy(), "oracle": r["short"].to_numpy(dtype=float)}
    price_preds = _aligned(book, OUT / "price_preds.parquet", ["p_hgb", "price_ridge", "price_hgb"])
    if price_preds is not None:
        sides["hgb"] = price_preds["p_hgb"].fillna(0.5).to_numpy()

    q = {"one_tilt": book.one_step(profile), "chain_tilt": book.chain(t.pi[book.m, book.s])}
    for name, p in sides.items():
        q[f"one_{name}"] = book.one_step(book.expected(p))
        q[f"chain_{name}"] = book.chain(p)
    # Direct price forecasts, tried and reported (they lose money: see results).
    q["price_oracle"] = book.one_step(book.realised)
    last_seen = book.rows[["start_time"]].merge(f[["start_time", "ssp_lag4"]], on="start_time", how="left")["ssp_lag4"]
    q["price_last_seen"] = book.one_step(np.where(last_seen.isna(), profile, last_seen))
    if price_preds is not None:
        for c in ("price_ridge", "price_hgb"):
            q[c] = book.one_step(np.where(price_preds[c].isna(), profile, price_preds[c]))
    q["hindsight"] = battery.hindsight_q(book.realised)
    return {name: book.run(qv) for name, qv in q.items()}


def skill_curve(book: Book, family: str, ks=(0.0, 0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)) -> list[dict]:
    """Money against forecast error: our errors scaled by k (0 = oracle side, 1 = ours)."""
    y = book.rows["short"].to_numpy(dtype=float)
    p = book.rows["p_ours"].to_numpy()
    out = []
    for k in ks:
        pk = np.clip(y + k * (p - y), 0, 1)
        q = book.one_step(book.expected(pk)) if family == "one" else book.chain(pk)
        out.append({"k": k, "brier": round(float(np.mean((pk - y) ** 2)), 4),
                    "gbp_per_day": round(float(book.daily(book.run(q)["pnl"]).mean()), 1)})
    return out


def _edges(daily: pd.DataFrame) -> dict:
    """For each forecast, its gain over the tilt in GBP/day and as a share of the tilt-to-oracle gap.

    Intervals resample weeks in pairs (the same weeks for every column), so a difference's
    interval reflects the difference, not two independent noises.
    """
    boot = pd.DataFrame(stats.resampled_means(daily.to_numpy(), stats.week_index(daily.index)), columns=daily.columns)
    out = {}
    for family in ("one", "chain"):
        for who in ("persistence", "indicated", "ours", "hgb"):
            name = f"{family}_{who}"
            if name not in daily:
                continue
            gain = lambda d: d[name] - d[f"{family}_tilt"]
            share = lambda d: gain(d) / (d[f"{family}_oracle"] - d[f"{family}_tilt"])
            g_lo, g_hi = stats.interval(gain(boot))
            s_lo, s_hi = stats.interval(share(boot))
            out[name] = {"gain_gbp": round(float(gain(daily.mean())), 2), "gain_lo": round(g_lo, 2), "gain_hi": round(g_hi, 2),
                         "share": round(float(share(daily.mean())), 4), "lo": round(s_lo, 4), "hi": round(s_hi, 4)}
    return out


def summarise(book: Book, sims: dict, daily: pd.DataFrame) -> dict:
    """Money with intervals, gains over the tilt, spike and era robustness, by year, value of skill."""
    boot = stats.resampled_means(daily.to_numpy(), stats.week_index(daily.index))
    money = []
    for j, c in enumerate(daily.columns):
        lo, hi = stats.interval(boot[:, j])
        money.append({"policy": c, "gbp_per_day": round(daily[c].mean(), 1), "lo": round(lo, 1), "hi": round(hi, 1),
                      "active_share": round(float((sims[c]["action"] != 0).mean()), 3)})

    # Spike robustness. The protocol's version leaves out the top 1% of half hours by absolute
    # price; the harsher one leaves out the top 1% of days by the oracle's P&L.
    spike = np.abs(book.realised) >= np.quantile(np.abs(book.realised), 0.99)
    no_spikes = pd.DataFrame({c: book.daily(np.where(spike, 0.0, sims[c]["pnl"])) for c in daily.columns})
    calm_days = daily[daily["one_oracle"].abs() <= daily["one_oracle"].abs().quantile(0.99)]

    # Eras: until February 2024 the stored prices are first prints; after, next-day revisions.
    first = daily.index < FIRST_PRINT_ERA_END
    preds_first = (book.rows["start_time"].dt.tz_localize(None) < FIRST_PRINT_ERA_END).to_numpy()
    eras = {}
    for era, days, rows in (("first prints, 2022-07 to 2024-01", first, preds_first),
                            ("revised prices, 2024-02 to 2026-06", ~first, ~preds_first)):
        scores = brier_table(book.rows[rows]).set_index("model")
        eras[era] = {"ours_minus_persistence_cal": scores.loc["persistence_cal", ["ours_minus", "ours_minus_lo", "ours_minus_hi"]].tolist(),
                     "chain_ours_gbp": round(daily.loc[days, "chain_ours"].mean(), 1),
                     "chain_tilt_gbp": round(daily.loc[days, "chain_tilt"].mean(), 1),
                     "gain": _edges(daily[days])["chain_ours"]}

    return {"brier": brier_table(book.rows).to_dict(orient="records"),
            "money": money,
            "gain_over_tilt": _edges(daily),
            "gain_without_spike_periods": _edges(no_spikes),
            "gain_without_top_1pct_days": _edges(calm_days),
            "by_era": eras,
            "by_year": daily.groupby(daily.index.year).mean().round(1).reset_index(names="year").to_dict(orient="records"),
            "skill_curve": {"one": skill_curve(book, "one"), "chain": skill_curve(book, "chain")}}


def run():
    """The whole decision study from the walk-forward forecasts: (book, sims, daily, results)."""
    preds = pd.read_parquet(OUT / "walkforward.parquet")
    f = pd.read_parquet(OUT / "features.parquet")
    book = Book.build(preds, f)
    sims = run_policies(book, f)
    daily = pd.DataFrame({name: book.daily(sim["pnl"]) for name, sim in sims.items()})
    return book, sims, daily, summarise(book, sims, daily)


def main() -> None:
    book, sims, daily, results = run()
    daily.to_parquet(OUT / "daily_pnl.parquet")
    (OUT / "results.json").write_text(json.dumps(results, indent=1))

    print(pd.DataFrame(results["brier"]).to_string(index=False), "\n")
    print(pd.DataFrame(results["money"]).to_string(index=False))
    for title, key in (("gain over the tilt", "gain_over_tilt"), ("without the top 1% of half hours by |price|", "gain_without_spike_periods"),
                       ("without the top 1% of days", "gain_without_top_1pct_days")):
        print(f"\n{title}: GBP/day, and share of the tilt-to-oracle gap")
        for name, g in results[key].items():
            print(f"  {name:18s} {g['gain_gbp']:+6.2f} [{g['gain_lo']:+6.2f}, {g['gain_hi']:+6.2f}]   "
                  f"{g['share']:6.1%} [{g['lo']:6.1%}, {g['hi']:6.1%}]")
    print("\nby era:")
    for era, e in results["by_era"].items():
        print(f"  {era}: ours minus persistence_cal Brier {e['ours_minus_persistence_cal']}, chain ours {e['chain_ours_gbp']} "
              f"vs tilt {e['chain_tilt_gbp']}, gap share {e['gain']['share']:.1%} [{e['gain']['lo']:.1%}, {e['gain']['hi']:.1%}]")
    for family, curve in results["skill_curve"].items():
        print(f"\nvalue of skill ({family}):", "  ".join(f"B{c['brier']:.3f}:£{c['gbp_per_day']:.0f}" for c in curve))


if __name__ == "__main__":
    main()
