"""What is an hour worth? The walk-forward rerun with the decision made 30, 60, 90 and 120 minutes ahead.

Gate closure is fixed at 60 minutes by the market's rules, but every timing rule in the pipeline
follows from the constants in gclose/__init__.py. Here the gate moves and everything else stays
as protocolled: the features, the monthly refits, the optimiser and the battery. Each lead gets
its own feature table, refits, battery and poison check on a real week.

The newest price moves with the gate. Period t-k starts 30k minutes before T and first prints
about FIRST_PRINT_DELAY (52 minutes) later, so it is public at a gate L minutes before T only if
30k > 52 + L. The price lag is the smallest such k: 3 at 30 minutes, 4 at 60 (the protocol's
PRICE_LAG_PERIODS), 5 at 90 and 6 at 120. The features still check every price's own print time,
and the battery's daily loss limit counts its cash up to the same period.

Only the side forecasts and the chain policies are rerun; the price models are not, so price/*
policies are not part of this. The 60-minute run must reproduce data/out/results.json to every
digit it keeps, or no other lead is reported.

Run: python -m gclose.latency   ->  data/out/latency.json and docs/value_of_time_{light,dark}.svg (2 to 3 minutes)
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from unittest import mock

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import gclose

from . import DOCS, FIRST_PRINT_DELAY, OUT, REVISED_PRICES_FROM, backtest, decide, features, receipts, stats
from .export import replay_week
from .figures import THEMES, _style
from .ingest import DATASETS, load

LATENCY = OUT / "latency.json"
PROTOCOL_MINUTES = gclose.GATE_LEAD // timedelta(minutes=1)
LEADS = (PROTOCOL_MINUTES, 30, 90, 120)  # minutes before the half hour; the protocol's gate first, as the check
HALF_HOUR = timedelta(minutes=30)
SIDE = ("ours", "persistence_cal", "indicated")  # the side forecasters traded at every lead


def price_lag(lead: timedelta, delay: timedelta = FIRST_PRINT_DELAY) -> int:
    """Rows back to the newest price normally public at a gate `lead` before the half hour starts.

    Period t-k starts 30k minutes before T and prints `delay` after it starts, so it is public at
    T - lead only if 30k > delay + lead. This is the smallest such k.
    """
    return (delay + lead) // HALF_HOUR + 1


def _set_everywhere(values: dict[str, object]) -> None:
    """Set each constant in every loaded gclose module that holds its own copy of it."""
    for name, module in list(sys.modules.items()):
        if name == "gclose" or name.startswith("gclose."):
            for constant, value in values.items():
                if constant in getattr(module, "__dict__", {}):
                    setattr(module, constant, value)


@contextmanager
def gate_lead(minutes: int) -> Iterator[None]:
    """Decide `minutes` before each half hour, with the price lag that follows, in every module.

    The modules import the constants by name, so each holds its own copy: the package, features,
    backtest, decide, battery, receipts and live. Every copy is set, and every copy is put back on
    the way out, even in a module first imported inside the block, so nothing leaks.
    """
    lead = timedelta(minutes=minutes)
    timing = {"GATE_LEAD": lead, "PRICE_LAG_PERIODS": price_lag(lead)}
    before = {name: getattr(gclose, name) for name in timing}
    _set_everywhere(timing)
    try:
        yield
    finally:
        _set_everywhere(before)


@dataclass(frozen=True)
class Run:
    """One lead's results, and what comparing it with the protocol's gate needs."""

    summary: dict
    squared_error: pd.Series  # ours, per test half hour
    daily: pd.Series  # chain/ours, GBP per UTC day


def run(minutes: int, raw: list[pd.DataFrame]) -> Run:
    """The protocol's walk-forward, battery and real-week poison check, with the gate `minutes` ahead."""
    started = time.perf_counter()
    with gate_lead(minutes):
        table = features.build(*raw)
        forecasts = backtest.walk_forward(table, backtest.ladder)
        # No price forecasts were made at this lead, so the merge adds nothing and price/* is never run.
        periods = decide.TestPeriods.build(table, forecasts, forecasts[["start_time", "short", "ssp"]])
        q = {"chain/schedule": periods.chain(periods.table_at("short_share"))}
        q |= {f"chain/{name}": periods.chain(periods.rows[f"p_{name}"].to_numpy()) for name in SIDE}
        trajectories = {policy: periods.trade(values) for policy, values in q.items()}
        week = pd.Timestamp(replay_week(periods).start_time, tz="UTC")  # the demo's week, chosen by price range
        with mock.patch.object(receipts, "load_table", lambda: table):  # this lead's features, not those on disk
            poison = receipts.real_week(periods, week)

    daily = pd.DataFrame({policy: periods.daily(t.pnl) for policy, t in trajectories.items()})
    boot = pd.DataFrame(stats.resampled_means(daily.to_numpy(), stats.week_index(daily.index)), columns=daily.columns)
    gain = daily["chain/ours"] - daily["chain/schedule"]
    # From February 2024 a price's print time is the 52-minute median, not its own (PROTOCOL amendment 4a).
    # The margin before the gate shrinks as the gate nears, so the era with true print times is the clean check.
    first_prints = np.asarray(daily.index < REVISED_PRICES_FROM.tz_localize(None))
    scores = {s["model"]: s for s in backtest.scores(forecasts)}
    tested = table["start_time"].isin(forecasts["start_time"])
    summary = {
        "minutes": minutes,
        "price_lag_periods": price_lag(timedelta(minutes=minutes)),
        "newest_price_missing": float(table.loc[tested, "price_newest"].isna().mean()),
        "brier": {name: s["brier"] for name, s in scores.items()},
        "ours_minus": {name: s["ours_minus"] for name, s in scores.items() if name != "ours"},
        "money": decide.money(daily, trajectories),
        "gain": stats.estimate(gain.mean(), boot["chain/ours"] - boot["chain/schedule"]),
        "gain_by_era": {
            era: stats.estimate(
                gain[mask].mean(),
                stats.resampled_means(gain[mask].to_numpy(), stats.week_index(gain.index[mask]))[:, 0],
            )
            for era, mask in (("first prints, to 2024-01", first_prints), ("revised, from 2024-02", ~first_prints))
        },
        "poison": {
            **poison,
            "passed": poison["features_changed"] == poison["forecasts_changed"] == poison["decisions_changed"] == 0
            and poison["later_rows_poisoned"] > 0,
        },
        "seconds": round(time.perf_counter() - started, 1),
    }
    squared_error = (forecasts["p_ours"] - forecasts["short"]) ** 2
    return Run(summary, squared_error.set_axis(forecasts["start_time"]), daily["chain/ours"])


def versus_protocol(this: Run, protocol: Run) -> dict:
    """This lead minus the protocol's gate, for ours: Brier and GBP per day, resampled in pairs by week."""
    out = {}
    for key, difference in (
        ("brier", this.squared_error - protocol.squared_error),
        ("gbp", this.daily - protocol.daily),
    ):
        boot = stats.resampled_means(difference.to_numpy(), stats.week_index(difference.index))[:, 0]
        out[key] = stats.estimate(difference.mean(), boot)
    return out


def reproduces(summary: dict, results: dict) -> bool:
    """Does the protocol's gate give results.json's numbers, to every digit results.json keeps?"""
    ours = decide.rounded({key: summary[key] for key in ("brier", "money", "gain")})
    return (
        ours["brier"] == {s["model"]: s["brier"] for s in results["forecasts"]}
        and all(ours["money"][policy] == results["money"][policy] for policy in ours["money"])
        and ours["gain"] == results["gain"]["chain/ours"]["gbp"]
    )


# ---------------------------------------------------------------- the figure


def value_of_time(latency: dict, theme: str) -> plt.Figure:
    """Our forecast's Brier score and the battery's money against minutes before the half hour.

    Bands are 90% intervals from resampling whole weeks. On the right the band is the gain over
    the schedule, resampled in pairs, drawn around ours: where it clears the dashed schedule
    line, the forecast beats not forecasting at that lead.
    """
    colors = THEMES[theme]
    leads = latency["leads"]
    minutes = [lead["minutes"] for lead in leads]
    end = minutes.index(min(minutes))  # direct labels sit by the last point, nearest the half hour

    def column(get: Callable[[dict], dict]) -> dict[str, np.ndarray]:
        return {key: np.array([get(lead)[key] for lead in leads]) for key in ("value", "lo", "hi")}

    ours = column(lambda lead: lead["brier"]["ours"])
    schedule = column(lambda lead: lead["money"]["chain/schedule"])["value"]
    money = column(lambda lead: lead["money"]["chain/ours"])["value"]
    gain = column(lambda lead: lead["gain"])

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["DejaVu Sans"], "svg.fonttype": "none"})
    fig, (skill, cash) = plt.subplots(1, 2, figsize=(10, 3.9))
    fig.patch.set_alpha(0)
    for ax in (skill, cash):
        _style(ax, colors)
        ax.patch.set_alpha(0)
        ax.axvline(PROTOCOL_MINUTES, color=colors["grid"], linewidth=1, zorder=1)
        ax.set_xticks(minutes)
        ax.set_xlim(130, 20)  # time runs left to right, towards the half hour
        ax.set_xlabel("minutes before the half hour starts", color=colors["muted"], fontsize=9)

    for name, label, style in (
        ("persistence_cal", "calibrated persistence", "-"),
        ("indicated", "NESO's forecast", (0, (4, 3))),
    ):
        brier = [lead["brier"][name]["value"] for lead in leads]
        skill.plot(minutes, brier, color=colors["muted"], linewidth=1, linestyle=style, zorder=2)
        skill.text(28, brier[end], label, color=colors["muted"], fontsize=9, va="center")
    skill.fill_between(minutes, ours["lo"], ours["hi"], color=colors["series"], alpha=0.15, linewidth=0, zorder=2)
    skill.plot(minutes, ours["value"], color=colors["series"], linewidth=2, marker="o", markersize=5, zorder=3)
    skill.text(28, ours["value"][end], "ours", color=colors["ink"], fontsize=9, va="center")
    skill.invert_yaxis()  # lower Brier is better, so better is up in both panels
    skill.set_ylabel("Brier score  (better ↑)", color=colors["muted"], fontsize=9)
    skill.set_title("Waiting sharpens the forecast", loc="left", color=colors["ink"], fontsize=11, pad=10)

    cash.fill_between(
        minutes, schedule + gain["lo"], schedule + gain["hi"], color=colors["series"], alpha=0.15, linewidth=0
    )
    cash.plot(minutes, money, color=colors["series"], linewidth=2, marker="o", markersize=5, zorder=3)
    cash.plot(minutes, schedule, color=colors["muted"], linewidth=1, linestyle=(0, (4, 3)), zorder=2)
    cash.text(28, money[end], "ours", color=colors["ink"], fontsize=9, va="center")
    cash.text(28, schedule[end], "no-forecast\nschedule", color=colors["muted"], fontsize=9, va="center")
    cash.set_ylabel("£ per day", color=colors["muted"], fontsize=9)
    cash.set_title("…and the battery earns more", loc="left", color=colors["ink"], fontsize=11, pad=10)
    for ax in (skill, cash):
        ax.text(PROTOCOL_MINUTES - 1.5, 0.98, "gate closure", transform=ax.get_xaxis_transform(), color=colors["muted"])

    fig.tight_layout(w_pad=3)
    return fig


def write_figures(latency: dict) -> None:
    for theme in THEMES:
        fig = value_of_time(latency, theme)
        fig.savefig(DOCS / f"value_of_time_{theme}.svg", transparent=True, metadata={"Date": None})
        plt.close(fig)


# ---------------------------------------------------------------- the study


def main() -> None:
    if not decide.RESULTS.exists():
        raise SystemExit(
            f"{decide.RESULTS} is missing; run `python -m gclose.decide` first, the 60-minute check needs it"
        )
    raw = [load(name) for name in DATASETS]
    runs: dict[int, Run] = {}
    for minutes in LEADS:
        runs[minutes] = run(minutes, raw)
        s = runs[minutes].summary
        print(
            f"{minutes:4d} min  lag {s['price_lag_periods']}  Brier ours {s['brier']['ours']['value']:.4f}  "
            f"chain/ours GBP {s['money']['chain/ours']['value']:.2f}  "
            f"schedule {s['money']['chain/schedule']['value']:.2f}"
            f"  poison {'passed' if s['poison']['passed'] else 'FAILED'}  {s['seconds']:.0f}s",
            flush=True,
        )
        if minutes == PROTOCOL_MINUTES and not reproduces(s, json.loads(decide.RESULTS.read_text(encoding="utf-8"))):
            raise SystemExit("the 60-minute run does not reproduce results.json; find out why before any other lead")

    protocol = runs[PROTOCOL_MINUTES]
    latency = {
        "protocol_minutes": PROTOCOL_MINUTES,
        "reproduces_results_json": True,
        "leads": [{**r.summary, "versus_protocol": versus_protocol(r, protocol)} for _, r in sorted(runs.items())],
    }
    LATENCY.write_text(json.dumps(decide.rounded(latency), indent=1), encoding="utf-8")
    write_figures(latency)
    print("ours at each lead minus ours at the gate [90% interval]")
    for lead in latency["leads"]:
        b, g = lead["versus_protocol"]["brier"], lead["versus_protocol"]["gbp"]
        print(
            f"  {lead['minutes']:4d} min  Brier {b['value']:+.4f} [{b['lo']:+.4f}, {b['hi']:+.4f}]   "
            f"GBP per day {g['value']:+.2f} [{g['lo']:+.2f}, {g['hi']:+.2f}]"
        )
    print(f"wrote {LATENCY} and docs/value_of_time_*.svg")


if __name__ == "__main__":
    main()
