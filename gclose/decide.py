"""Decision layer: one optimiser, many forecasts.

Every policy is the same dynamic programme over the battery's five state-of-charge levels.
Only the information fed into it changes, so any difference in money is the forecast's doing.

What the optimiser knows at the gate for period t (slot s = half hour of the UTC day):
  * Trailing 90-day tables, from periods whose price was public at the test month's first
    gate: the mean price by slot (`profile`), the mean price by slot when short and when long
    (`mu_short`, `mu_long`), the share of short periods by slot (`short_share`), and the lag-1
    autocorrelation of the side (`side_autocorr`). Note that, slot by slot,
    short_share * mu_short + (1 - short_share) * mu_long == profile.
  * A forecast: either P(short) for period t, turned into an expected price
    p * mu_short + (1 - p) * mu_long, or an expected price directly.

Two policy families:
  one     the forecast prices period t only; everything after it is valued on the profile.
  chain   the forecast also shapes the next CHAIN_STEPS - 1 periods, because the side persists:
          p(t+h) = short_share[s+h] + (p - short_share[s]) * side_autocorr ** h. The
          autocorrelation is about 0.5, so the forecast's pull halves every half hour. Fed the
          base rate (p = short_share), this is exactly the schedule. That geometric fade is a
          two-state Markov chain's; `markov_check` tests it against the side's measured memory.

Policies are named family/forecaster: one/ours, chain/schedule, price/ridge. Two reference
points: */side_oracle knows the side of period t in advance (not its price, nor anything
later), and `hindsight` knows every price in advance: the true ceiling.

Run: python -m gclose.decide   ->  data/out/results.json and data/out/daily_pnl.parquet
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import GATE_LEAD, OUT, PERIODS_PER_DAY, REVISED_PRICES_FROM, battery, slot_of, stats
from .backtest import FORECASTS, scores
from .battery import Trajectory
from .features import load_table
from .price_models import PRICE_FORECASTS

RESULTS = OUT / "results.json"
DAILY_PNL = OUT / "daily_pnl.parquet"
LOOKBACK = pd.Timedelta(days=90)
CHAIN_STEPS = 8
SPIKE_QUANTILE = 0.99  # robustness: leave out the top 1%
SKILL_SCALES = (0.0, 0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5)
SIDE_FORECASTERS = ("persistence_cal", "indicated", "ours", "boosted", "side_oracle")
FAMILIES = ("one", "chain")


@dataclass(frozen=True)
class Tables:
    """Trailing-window tables, one per test month: (months, 48) arrays unless noted."""

    profile: np.ndarray
    mu_short: np.ndarray
    mu_long: np.ndarray
    short_share: np.ndarray
    side_autocorr: np.ndarray  # (months,): lag-1 autocorrelation of the side
    side_memory: np.ndarray  # (months, CHAIN_STEPS - 1): measured autocorrelation at lags 1, 2, ...
    value: np.ndarray  # (months, 48, K): value of each SoC level at the start of each slot

    @classmethod
    def build(cls, table: pd.DataFrame, starts: list[pd.Timestamp]) -> Tables:
        """One set of tables per start: the LOOKBACK days whose price was public by the first gate after it."""
        slots = pd.Index(range(PERIODS_PER_DAY))
        columns: dict[str, list] = {
            name: [] for name in ("profile", "mu_short", "mu_long", "short_share", "side_autocorr", "side_memory")
        }
        for start in starts:
            history = table[(table["start_time"] >= start - LOOKBACK) & (table["created_at"] < start - GATE_LEAD)]
            slot = slot_of(history["start_time"])
            profile = history.groupby(slot)["ssp"].mean().reindex(slots).interpolate().bfill().ffill()
            by_side = history.groupby([slot, history["short"]])["ssp"].mean().unstack().reindex(slots)
            side = history["short"].to_numpy()
            columns["profile"].append(profile.to_numpy())
            columns["mu_short"].append(by_side[1].fillna(profile).to_numpy())
            columns["mu_long"].append(by_side[0].fillna(profile).to_numpy())
            columns["short_share"].append(history.groupby(slot)["short"].mean().reindex(slots).fillna(0.5).to_numpy())
            columns["side_autocorr"].append(np.clip(np.corrcoef(side[1:], side[:-1])[0, 1], 0.0, 0.99))
            columns["side_memory"].append(stats.autocorrelation(side, CHAIN_STEPS - 1))
        arrays = {name: np.array(values) for name, values in columns.items()}
        value = np.stack([battery.value_tables(profile) for profile in arrays["profile"]])
        return cls(value=value, **arrays)


@dataclass(frozen=True)
class TestPeriods:
    """The test half hours in time order, with every forecast and everything the policies index by."""

    rows: pd.DataFrame
    tables: Tables
    month_idx: np.ndarray  # index into the tables
    slot: np.ndarray
    day: np.ndarray  # UTC day number, for the loss limit and daily P&L
    realised: np.ndarray  # settled price: decides cash, never actions

    @classmethod
    def build(cls, table: pd.DataFrame, forecasts: pd.DataFrame, price_forecasts: pd.DataFrame) -> TestPeriods:
        """Test periods from walk-forward forecasts; the tables are rebuilt as of each month's start."""
        price_forecasts = price_forecasts.drop(columns=["short", "ssp"])
        rows = (
            forecasts.merge(price_forecasts, on="start_time", how="left", validate="one_to_one")
            .merge(table[["start_time", "price_newest"]], on="start_time", how="left", validate="one_to_one")
            .sort_values("start_time")
            .reset_index(drop=True)
        )
        utc = rows["start_time"].dt.tz_convert("UTC").dt.tz_localize(None)
        month = utc.dt.to_period("M").astype(str)
        months = sorted(month.unique())
        return cls(
            rows=rows,
            tables=Tables.build(table, [pd.Timestamp(f"{m}-01", tz="UTC") for m in months]),
            month_idx=month.map({m: i for i, m in enumerate(months)}).to_numpy(),
            slot=slot_of(rows["start_time"]),
            day=(utc.dt.normalize() - pd.Timestamp("1970-01-01")).dt.days.to_numpy(),
            realised=rows["ssp"].to_numpy(),
        )

    def subset(self, idx: np.ndarray) -> TestPeriods:
        """The same periods restricted to some rows; the tables are unchanged."""
        return TestPeriods(
            self.rows.iloc[idx].reset_index(drop=True),
            self.tables,
            self.month_idx[idx],
            self.slot[idx],
            self.day[idx],
            self.realised[idx],
        )

    def table_at(self, name: str, ahead: int = 0) -> np.ndarray:
        """A slot table read for each row, `ahead` periods after the row's own slot."""
        return getattr(self.tables, name)[self.month_idx, (self.slot + ahead) % PERIODS_PER_DAY]

    def expected_price(self, p_short: np.ndarray, ahead: int = 0) -> np.ndarray:
        """Expected price `ahead` periods after each row, given P(short) for that period."""
        return p_short * self.table_at("mu_short", ahead) + (1 - p_short) * self.table_at("mu_long", ahead)

    def one_step(self, price_now: np.ndarray) -> np.ndarray:
        """Q-values when the forecast informs period t only."""
        return battery.q_values(self.table_at("value", ahead=1), price_now)

    def chain(self, p_short: np.ndarray, memory: str = "geometric") -> np.ndarray:
        """Q-values when P(short) also shapes the next CHAIN_STEPS - 1 periods, fading to the base rate.

        memory="geometric" fades by side_autocorr ** h, as a two-state Markov chain would (the
        protocol's policy); memory="measured" fades by the side's measured autocorrelation at lag h.
        """
        v = self.table_at("value", ahead=CHAIN_STEPS)
        base_rate = self.table_at("short_share")
        for h in range(CHAIN_STEPS - 1, 0, -1):
            if memory == "geometric":
                fade = self.tables.side_autocorr[self.month_idx] ** h
            else:
                fade = self.tables.side_memory[self.month_idx, h - 1]
            p_ahead = np.clip(self.table_at("short_share", h) + (p_short - base_rate) * fade, 0, 1)
            v = battery.bellman(v, self.expected_price(p_ahead, ahead=h))
        return battery.q_values(v, self.expected_price(p_short))

    def trade(self, q: np.ndarray) -> Trajectory:
        return battery.simulate(q, self.realised, self.day)

    def daily(self, pnl: np.ndarray) -> pd.Series:
        """GBP per UTC day."""
        days, idx = np.unique(self.day, return_inverse=True)
        return pd.Series(np.bincount(idx, weights=pnl), index=pd.to_datetime(days, unit="D"))

    def side_forecasts(self) -> dict[str, np.ndarray]:
        """P(short) per period from every forecaster the policies use, the oracle included."""
        probs = {name: self.rows[f"p_{name}"].to_numpy() for name in SIDE_FORECASTERS if name != "side_oracle"}
        probs["side_oracle"] = self.rows["short"].to_numpy(dtype=float)
        return probs


def policies(periods: TestPeriods) -> dict[str, np.ndarray]:
    """Q-values for every policy in the study, by name."""
    profile = periods.table_at("profile")
    q = {"one/schedule": periods.one_step(profile), "chain/schedule": periods.chain(periods.table_at("short_share"))}
    for name, p_short in periods.side_forecasts().items():
        q[f"one/{name}"] = periods.one_step(periods.expected_price(p_short))
        q[f"chain/{name}"] = periods.chain(p_short)
    rows = periods.rows
    for name, column in (("ridge", "price_ridge"), ("boosted", "price_boosted"), ("last_seen", "price_newest")):
        q[f"price/{name}"] = periods.one_step(rows[column].fillna(pd.Series(profile)).to_numpy())
    q["price/oracle"] = periods.one_step(periods.realised)
    q["hindsight"] = battery.hindsight_q(periods.realised)
    return q


# ---------------------------------------------------------------- summaries


def money(daily: pd.DataFrame, trajectories: dict[str, Trajectory]) -> dict[str, dict]:
    """GBP per day for every policy, with its interval and how often it trades."""
    boot = stats.resampled_means(daily.to_numpy(), stats.week_index(daily.index))
    return {
        name: {
            **stats.estimate(daily[name].mean(), boot[:, j]),
            "active_share": float((trajectories[name].action != 0).mean()),
        }
        for j, name in enumerate(daily.columns)
    }


def _gain(d: pd.DataFrame | pd.Series, policy: str, schedule: str) -> pd.Series | float:
    return d[policy] - d[schedule]


def _share(d: pd.DataFrame | pd.Series, policy: str, schedule: str, oracle: str) -> pd.Series | float:
    return _gain(d, policy, schedule) / (d[oracle] - d[schedule])


def gains(daily: pd.DataFrame) -> dict[str, dict]:
    """Each forecast's gain over the schedule in GBP per day, and as a share of the gap to the side oracle."""
    boot = pd.DataFrame(stats.resampled_means(daily.to_numpy(), stats.week_index(daily.index)), columns=daily.columns)
    means = daily.mean()
    out = {}
    for family in FAMILIES:
        schedule, oracle = f"{family}/schedule", f"{family}/side_oracle"
        for name in SIDE_FORECASTERS[:-1]:
            policy = f"{family}/{name}"
            out[policy] = {
                "gbp": stats.estimate(_gain(means, policy, schedule), _gain(boot, policy, schedule)),
                "share": stats.estimate(
                    _share(means, policy, schedule, oracle), _share(boot, policy, schedule, oracle)
                ),
            }
    return out


def risk(daily: pd.DataFrame) -> dict[str, dict]:
    """Sharpe ratio and drawdown of the schedule, of ours, and of ours' gain over the schedule.

    The last is an information ratio: the reward per unit of risk for trusting the forecast
    over the benchmark.
    """
    return {
        "chain/schedule": stats.risk(daily["chain/schedule"]),
        "chain/ours": stats.risk(daily["chain/ours"]),
        "chain/ours minus chain/schedule": stats.risk(daily["chain/ours"] - daily["chain/schedule"]),
    }


def markov_check(periods: TestPeriods) -> dict:
    """Does the side fade like a two-state Markov chain? And does it matter for money?

    Compares the side's measured autocorrelation over the test period with the geometric decay
    the chain policy assumes, then reruns chain/ours with the measured memory instead.
    """
    observed = stats.autocorrelation(periods.rows["short"].to_numpy(), CHAIN_STEPS - 1)
    lags = np.arange(1, CHAIN_STEPS)
    p_ours = periods.side_forecasts()["ours"]
    gbp = {
        memory: float(periods.daily(periods.trade(periods.chain(p_ours, memory)).pnl).mean())
        for memory in ("geometric", "measured")
    }
    return {
        "lags": lags.tolist(),
        "observed": observed.tolist(),
        "geometric": (observed[0] ** lags).tolist(),
        "chain_ours_gbp": gbp,
    }


def without_spike_half_hours(periods: TestPeriods, trajectories: dict[str, Trajectory]) -> pd.DataFrame:
    """Daily P&L leaving out the top 1% of half hours by absolute price (the protocol's spike check)."""
    size = np.abs(periods.realised)
    spike = size >= np.quantile(size, SPIKE_QUANTILE)
    return pd.DataFrame({name: periods.daily(np.where(spike, 0.0, t.pnl)) for name, t in trajectories.items()})


def without_top_days(daily: pd.DataFrame) -> pd.DataFrame:
    """Daily P&L leaving out the top 1% of days by the side oracle's absolute P&L (a harsher check)."""
    size = daily["one/side_oracle"].abs()
    return daily[size <= size.quantile(SPIKE_QUANTILE)]


def by_era(periods: TestPeriods, daily: pd.DataFrame) -> dict[str, dict]:
    """The headline split at the month Elexon began revising prices (PROTOCOL.md amendment 4)."""
    eras = {
        "first prints, 2022-07 to 2024-01": (
            daily.index < REVISED_PRICES_FROM.tz_localize(None),
            (periods.rows["start_time"] < REVISED_PRICES_FROM).to_numpy(),
        )
    }
    eras["revised prices, 2024-02 to 2026-06"] = tuple(~mask for mask in eras["first prints, 2022-07 to 2024-01"])
    out = {}
    for era, (days, rows) in eras.items():
        if not rows.any():
            continue
        forecast_scores = {s["model"]: s for s in scores(periods.rows[rows])}
        out[era] = {
            "ours_minus_persistence_cal": forecast_scores["persistence_cal"]["ours_minus"],
            "schedule": float(daily.loc[days, "chain/schedule"].mean()),
            "chain_ours": float(daily.loc[days, "chain/ours"].mean()),
            "gain": gains(daily[days])["chain/ours"],
        }
    return out


def by_year(daily: pd.DataFrame) -> list[dict]:
    return daily.groupby(daily.index.year).mean().reset_index(names="year").to_dict(orient="records")


def value_of_skill(periods: TestPeriods) -> dict[str, list[dict]]:
    """Money against forecast error: our errors scaled by k (0 knows the side, 1 is ours, above 1 is worse)."""
    short = periods.rows["short"].to_numpy(dtype=float)
    ours = periods.rows["p_ours"].to_numpy()
    out: dict[str, list[dict]] = {family: [] for family in FAMILIES}
    for k in SKILL_SCALES:
        p_short = np.clip(short + k * (ours - short), 0, 1)
        q = {"one": periods.one_step(periods.expected_price(p_short)), "chain": periods.chain(p_short)}
        for family in FAMILIES:
            gbp = periods.daily(periods.trade(q[family]).pnl).mean()
            out[family].append({"k": k, "brier": float(np.mean((p_short - short) ** 2)), "gbp": float(gbp)})
    return out


# ---------------------------------------------------------------- the study


@dataclass(frozen=True)
class Study:
    periods: TestPeriods
    trajectories: dict[str, Trajectory]
    daily: pd.DataFrame  # GBP per UTC day, one column per policy
    results: dict


def run_study() -> Study:
    """Every policy over the walk-forward test, and every summary the docs report."""
    table = load_table()
    periods = TestPeriods.build(table, pd.read_parquet(FORECASTS), pd.read_parquet(PRICE_FORECASTS))
    return study(periods)


def study(periods: TestPeriods) -> Study:
    """Every policy and every summary, for any set of test periods (the walk-forward or the holdout)."""
    trajectories = {name: periods.trade(q) for name, q in policies(periods).items()}
    daily = pd.DataFrame({name: periods.daily(t.pnl) for name, t in trajectories.items()})
    results = {
        "forecasts": scores(periods.rows),
        "money": money(daily, trajectories),
        "gain": gains(daily),
        "gain_without_spike_half_hours": gains(without_spike_half_hours(periods, trajectories)),
        "gain_without_top_days": gains(without_top_days(daily)),
        "by_era": by_era(periods, daily),
        "by_year": by_year(daily),
        "value_of_skill": value_of_skill(periods),
        "risk": risk(daily),
        "markov_check": markov_check(periods),
    }
    return Study(periods, trajectories, daily, results)


def rounded(obj: object, digits: int = 4) -> object:
    """Round every float in a nested structure, once, at the point of writing it out."""
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, dict):
        return {key: rounded(value, digits) for key, value in obj.items()}
    if isinstance(obj, list):
        return [rounded(value, digits) for value in obj]
    return obj


def main() -> None:
    study = run_study()
    study.daily.to_parquet(DAILY_PNL)
    RESULTS.write_text(json.dumps(rounded(study.results), indent=1))
    print("GBP per day [90% interval]")
    for name, m in study.results["money"].items():
        print(f"  {name:24s} {m['value']:7.1f} [{m['lo']:6.1f}, {m['hi']:6.1f}]   trades in {m['active_share']:.0%}")
    print("gain over the schedule, GBP per day [90% interval]")
    for name, g in study.results["gain"].items():
        print(f"  {name:24s} {g['gbp']['value']:+6.2f} [{g['gbp']['lo']:+6.2f}, {g['gbp']['hi']:+6.2f}]")
    print(f"wrote {RESULTS}")


if __name__ == "__main__":
    main()
