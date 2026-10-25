"""The live record: from the freeze onwards, every half hour, a forecast and a trade written down
and pushed to GitHub before the half hour it is about.

    python -m gclose.live check           rehearsal: fetch from Elexon and decide once, writing and pushing nothing
    python -m gclose.live freeze          fit the model on everything public now, save it as JSON, commit and push
    python -m gclose.live run             every half hour: fetch the last three days from Elexon, decide the
                                          next period whose gate is still ahead, append it to the ledger, push
    python -m gclose.live score           once prices have printed, score every decision in the ledger
    python -m gclose.live replay WHEN     the same decision code as of a past moment, on the stored data, no git

`check`, `freeze` and `run` need a machine that can reach Elexon; `replay` works anywhere. The frozen
model is plain JSON (feature medians, scaling, 16 weights and an intercept, plus the optimiser's
tables) with a SHA-256 of its contents, so anyone can recompute any decision in the ledger.

What the record proves: each ledger line names the period it is about, the moment it was
decided, and the model's hash, and is pushed before that period's gate. GitHub's timestamps
are the receipt. The frozen model is fitted on everything public at the freeze, holdout months
included; the holdout itself is scored by gclose.holdout with the walk-forward's monthly refits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import timedelta
from functools import cache

import numpy as np
import pandas as pd

from . import GATE_LEAD, RAW, ROOT, battery, slot_of
from .decide import Tables, TestPeriods
from .features import FEATURES, build, first_print_at, load_table
from .ingest import DATASETS, fetch_prices, fetch_vintages_between, load
from .models import AllFeatures

LEDGER = ROOT / "ledger"
MODEL = LEDGER / "model.json"
DECISIONS = LEDGER / "decisions.jsonl"
SCORE = LEDGER / "score.json"
OUTCOMES = LEDGER / "outcomes.json"  # what each called half hour turned out to be, as its price prints
RECENT = timedelta(days=3)  # raw data fetched each run: enough for every lag and rolling window
RUN_AT_MINUTES = (24, 54)  # six minutes before each gate: late enough for t-4's price to have printed
WAKE_TOLERANCE = pd.Timedelta(minutes=2)  # a run that wakes later than this after its moment is skipped
HALF_HOUR = pd.Timedelta(minutes=30)
ONE_DAY = pd.Timedelta(days=1)


def pre_fix(entries: pd.DataFrame) -> pd.Series:
    """True for each ledger line written by the code from before PROTOCOL amendment 8.

    The first live process kept running that code for a while after the fixed one had started.
    Its bug has a signature: a side (short_newest) for the newest period although that period's
    volume (niv_newest) had not printed. The ledger is append-only, so these lines stay; they are
    listed in the README and left out of the score.
    """
    inputs = pd.DataFrame(entries["inputs"].tolist(), index=entries.index)
    return inputs["short_newest"].notna() & inputs["niv_newest"].isna()


def committed_at(entries: pd.DataFrame) -> pd.Series:
    """When each ledger line was committed, from git's own log; NaT for a line not yet committed.

    A line only counts as a receipt if it was committed, and so pushable, before its gate: once
    a laptop slept mid-decision and committed the line hours after the gate. Git's author date is
    the original commit time; the committer date moves whenever a pull rebases the commit.
    """
    log = _git("log", "--format=%aI%x09%s", "--", str(DECISIONS.relative_to(ROOT)))
    times = {}
    for line in log.splitlines():
        stamp, _, subject = line.partition("\t")
        if subject.startswith("ledger: ") and " decided at " in subject:
            target, decided = subject.removeprefix("ledger: ").split(" decided at ")
            times.setdefault((target, decided), pd.Timestamp(stamp).tz_convert("UTC"))
    keys = zip(entries["target_start"], entries["decided_at"], strict=True)
    return pd.Series([times.get(key, pd.NaT) for key in keys], index=entries.index, dtype="datetime64[ns, UTC]")


# ---------------------------------------------------------------- the frozen model


@dataclass(frozen=True)
class Frozen:
    """Everything a live decision needs, in plain numbers."""

    frozen_at: str
    git_commit: str
    trained_rows: int
    features: list[str]
    medians: list[float]
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    tables: dict[str, list]

    def p_short(self, row: pd.Series) -> float:
        """The logistic model by hand: fill, standardise, weigh, squash."""
        x = row[self.features].to_numpy(dtype=float)
        x = np.where(np.isnan(x), self.medians, x)
        z = (x - np.asarray(self.mean)) / np.asarray(self.scale)
        return float(1 / (1 + np.exp(-(z @ np.asarray(self.coef) + self.intercept))))

    def optimiser_tables(self) -> Tables:
        return Tables(**{name: np.asarray(values) for name, values in self.tables.items()})

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def save(self) -> None:
        LEDGER.mkdir(exist_ok=True)
        MODEL.write_text(json.dumps({**asdict(self), "sha256": self.sha256()}, indent=1), encoding="utf-8")

    @classmethod
    def load(cls) -> Frozen:
        stored = json.loads(MODEL.read_text(encoding="utf-8"))
        claimed = stored.pop("sha256")
        frozen = cls(**stored)
        if frozen.sha256() != claimed:
            raise SystemExit(f"{MODEL} does not match its own hash; it was changed after the freeze")
        return frozen


def freeze(table: pd.DataFrame, now: pd.Timestamp) -> Frozen:
    """Fit ours on every outcome public at `now` and capture the optimiser's tables as of `now`."""
    train = table[table["created_at"] < now]
    model = AllFeatures().fit(train).model
    imputer, scaler, logit = model.steps[0][1], model.steps[1][1], model.steps[2][1]
    tables = Tables.build(table, [now + GATE_LEAD])  # history public by `now`
    return Frozen(
        frozen_at=now.isoformat(),
        git_commit=_git("rev-parse", "HEAD").strip(),
        trained_rows=len(train.dropna(subset=FEATURES)),
        features=FEATURES,
        medians=imputer.statistics_.tolist(),
        mean=scaler.mean_.tolist(),
        scale=scaler.scale_.tolist(),
        coef=logit.coef_[0].tolist(),
        intercept=float(logit.intercept_[0]),
        tables={name: np.asarray(values).tolist() for name, values in asdict(tables).items()},
    )


# ---------------------------------------------------------------- one decision


def target_for(now: pd.Timestamp) -> pd.Timestamp:
    """The earliest period whose gate is strictly after `now`."""
    return now.floor("30min") + HALF_HOUR + GATE_LEAD


def fetch_recent(now: pd.Timestamp) -> list[pd.DataFrame]:
    """The last RECENT of every dataset, straight from Elexon: by definition, all of it is public now.

    Prices are fetched by settlement date, which is UK local time: in summer the half hours from
    23:00 UTC belong to the next day's date, so the range runs one day past today's UTC date.
    """
    prices = fetch_prices((now - RECENT).date(), (now + ONE_DAY).date())
    return [prices, *(fetch_vintages_between(name, now - RECENT, now) for name in DATASETS[1:])]


@cache
def _stored() -> tuple[pd.DataFrame, ...]:
    return tuple(load(name) for name in DATASETS)


def stored_as_of(now: pd.Timestamp) -> list[pd.DataFrame]:
    """The same window from data/raw, keeping only what was public at `now` (for replay)."""
    prices, *vintages = _stored()
    prices = prices[(prices["start_time"] >= now - RECENT) & (first_print_at(prices) < now)]
    vintages = [v[(v["publish_time"] >= now - RECENT) & (v["publish_time"] < now)] for v in vintages]
    return [prices, *vintages]


def _with_future_rows(prices: pd.DataFrame, target: pd.Timestamp) -> pd.DataFrame:
    """Placeholder rows up to the target: periods with no price yet, so features have somewhere to land."""
    last = prices["start_time"].max()
    future = pd.date_range(last + HALF_HOUR, target, freq="30min")
    placeholders = pd.DataFrame(
        {"start_time": future, "created_at": pd.NaT, "ssp": np.nan, "sbp": np.nan, "niv": np.nan}
    )
    return pd.concat([prices, placeholders], ignore_index=True)


def _settled_pnl_today(entries: list[dict], prices: pd.DataFrame, target: pd.Timestamp, now: pd.Timestamp) -> float:
    """Our cash so far on the target's UTC day, counting only periods whose price has printed by `now`."""
    printed = prices[first_print_at(prices) < now].set_index("start_time")["ssp"]
    total = 0.0
    for entry in entries:
        start = pd.Timestamp(entry["target_start"])
        if start.date() == target.date() and start < target and start in printed.index:
            label = battery.LABEL.tolist().index(entry["action"])
            total += float(battery.cash(printed[start])[label])
    return total


def decide(now: pd.Timestamp, raw: list[pd.DataFrame], frozen: Frozen, entries: list[dict]) -> dict:
    """The decision for the next period whose gate is ahead: the backtest's optimiser, one row at a time."""
    target = target_for(now)
    prices, *vintages = raw
    # Only what had printed by `now`: a fetch that runs long, or a laptop that sleeps mid-fetch,
    # can bring back prices published after the decision's own timestamp.
    prices = prices[first_print_at(prices) < now]
    vintages = [v[v["publish_time"] < now] for v in vintages]
    table = build(_with_future_rows(prices, target), *vintages)
    row = table[table["start_time"] == target].iloc[0]
    p_short = frozen.p_short(row)

    one = TestPeriods(
        rows=pd.DataFrame({"start_time": [target]}),
        tables=frozen.optimiser_tables(),
        month_idx=np.array([0]),
        slot=slot_of(pd.Series([target])),
        day=np.array([0]),
        realised=np.array([np.nan]),
    )
    q = one.chain(np.array([p_short]))[0]  # (K, 3): value of each action at each SoC level
    soc_before = entries[-1]["soc_after"] if entries else 0.0
    level = round(soc_before / battery.STEP)
    halted = _settled_pnl_today(entries, prices, target, now) < -battery.DAILY_LOSS_LIMIT
    action = battery.HOLD if halted else q[level].argmax()
    return {
        "target_start": target.isoformat(),
        "gate": (target - GATE_LEAD).isoformat(),
        "decided_at": now.isoformat(),
        "p_short": round(p_short, 4),
        "expected_price": round(float(one.expected_price(np.array([p_short]))[0]), 2),
        "action": int(battery.LABEL[action]),
        "soc_before": soc_before,
        "soc_after": float(battery.SOC[level + battery.MOVE[action]]),
        "halted_by_loss_limit": bool(halted),
        "model_sha256": frozen.sha256(),
        "inputs": {name: (None if pd.isna(row[name]) else round(float(row[name]), 4)) for name in FEATURES},
    }


# ---------------------------------------------------------------- the ledger and git


def outcomes(entries: list[dict], prices: pd.DataFrame, now: pd.Timestamp) -> list[dict]:
    """The printed price and side for every called half hour whose price is public at `now`.

    Written whole on every run from the prices just fetched, so the demo can show each call
    against what happened without asking Elexon itself.
    """
    printed = prices[first_print_at(prices) < now].dropna(subset=["ssp", "niv"]).drop_duplicates("start_time")
    by_start = printed.set_index("start_time")
    labels = battery.LABEL.tolist()
    out = []
    for start in sorted({entry["target_start"] for entry in entries}):
        stamp = pd.Timestamp(start)
        if stamp not in by_start.index:
            continue
        price, niv = float(by_start.at[stamp, "ssp"]), float(by_start.at[stamp, "niv"])
        calls = [entry for entry in entries if entry["target_start"] == start]
        latest = calls[-1]
        out.append(
            {
                "target_start": start,
                "price": round(price, 2),
                "short": niv > 0,
                "printed_at": first_print_at(printed[printed["start_time"] == stamp]).iloc[0].isoformat(),
                "pnl": round(float(battery.cash(np.array([price]))[0, labels.index(latest["action"])]), 2),
            }
        )
    return out


def read_ledger() -> list[dict]:
    if not DECISIONS.exists():
        return []
    return [json.loads(line) for line in DECISIONS.read_text(encoding="utf-8").splitlines() if line.strip()]


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        print(f"git {' '.join(args)} failed: {done.stderr.strip()}", file=sys.stderr)
    return done.stdout


def publish(paths: list[str], message: str) -> None:
    """Commit the given files, and only them, and push; a failed push is retried by the next run's push."""
    _git("add", *paths)
    _git("commit", "-q", "-m", message, "--", *paths)
    _git("pull", "-q", "--rebase", "--autostash")
    _git("push", "-q")


def _next_run(now: pd.Timestamp) -> pd.Timestamp:
    hour = now.floor("h")
    candidates = [hour + pd.Timedelta(minutes=m) for m in RUN_AT_MINUTES]
    candidates += [c + pd.Timedelta(hours=1) for c in candidates]
    return min(c for c in candidates if c > now)


def _sleep_until(moment: pd.Timestamp) -> None:
    """Sleep until `moment`, checking the clock again on waking: a laptop coming out of suspend
    can end a sleep early, and a decision then would be off schedule."""
    print(f"  next decision at {moment:%H:%M} UTC, for the period starting {target_for(moment):%H:%M} UTC", flush=True)
    while (remaining := (moment - pd.Timestamp.now(tz="UTC")).total_seconds()) > 0:
        time.sleep(min(remaining, 60))


def on_schedule(moment: pd.Timestamp, now: pd.Timestamp) -> bool:
    """Is it still the scheduled moment? A laptop waking from sleep long after it must not decide
    then: the lead to the gate and the prices that have printed would both be off schedule."""
    return pd.Timedelta(0) <= now - moment <= WAKE_TOLERANCE


def before_gate(entry: dict, now: pd.Timestamp) -> bool:
    """Was the decision finished before its gate? One that ends after it (a laptop asleep mid-fetch) is no receipt."""
    return now < pd.Timestamp(entry["gate"])


def run_forever() -> None:
    """Decide, record and push at :24 and :54 UTC until stopped with Ctrl+C.

    It always waits for the next scheduled moment first, so a restart never decides early,
    before the newest price has had its usual time to print. A moment slept through is skipped,
    and a decision that only finishes after its gate is not recorded.
    """
    frozen = Frozen.load()
    print(f"live with model {frozen.sha256()[:12]}, frozen at {frozen.frozen_at}")
    while True:
        moment = _next_run(pd.Timestamp.now(tz="UTC"))
        _sleep_until(moment)
        now = pd.Timestamp.now(tz="UTC")
        if not on_schedule(moment, now):
            print(f"{now:%H:%M} woke after the {moment:%H:%M} run was due; skipped it rather than decide off schedule")
            continue
        entries = read_ledger()
        if any(entry["target_start"] == target_for(now).isoformat() for entry in entries):
            continue
        try:
            raw = fetch_recent(now)
            entry = decide(now, raw, frozen, entries)
            if not before_gate(entry, pd.Timestamp.now(tz="UTC")):
                print(f"the call for {entry['target_start'][11:16]} finished after its gate; not recorded")
                continue
            with DECISIONS.open("a", encoding="utf-8") as ledger:
                ledger.write(json.dumps(entry) + "\n")
            OUTCOMES.write_text(json.dumps(outcomes(entries, raw[0], now), indent=1), encoding="utf-8")
            publish(
                [str(DECISIONS.relative_to(ROOT)), str(OUTCOMES.relative_to(ROOT))],
                f"ledger: {entry['target_start']} decided at {entry['decided_at']}",
            )
            missing = [name for name, value in entry["inputs"].items() if value is None]
            print(
                f"{entry['decided_at'][:16]}  {entry['target_start'][:16]}  p_short {entry['p_short']:.3f}  "
                f"action {entry['action']:+d}  soc {entry['soc_after']:.1f}"
                + (f"  missing {missing}" if missing else "")
            )
        except Exception as error:
            print(f"{now:%H:%M} run failed, will retry next half hour: {error!r}", file=sys.stderr)


# ---------------------------------------------------------------- scoring


def score(prices: pd.DataFrame) -> dict:
    """Ours against the no-forecast schedule over every ledger period whose price has printed,
    leaving out the pre-fix lines and any line not committed before its gate."""
    ledger = pd.DataFrame(read_ledger())
    if ledger.empty:
        raise SystemExit("the ledger is empty")
    late = ~(committed_at(ledger) < pd.to_datetime(ledger["gate"]))
    entries = (
        ledger[~pre_fix(ledger) & ~late]
        .drop_duplicates("target_start")  # two processes once decided the same period in the same second
        .assign(target_start=lambda e: pd.to_datetime(e["target_start"], utc=True))
    )
    if entries.empty:
        raise SystemExit("every ledger line so far is from the pre-fix process")
    prices = prices.dropna(subset=["ssp", "niv"]).drop_duplicates("start_time").sort_values("start_time")
    settled = entries.merge(prices[["start_time", "ssp", "niv"]], left_on="target_start", right_on="start_time")
    if settled.empty:
        raise SystemExit("no ledger period has printed yet")
    short = (settled["niv"] > 0).astype(float).to_numpy()
    price = settled["ssp"].to_numpy()
    labels = battery.LABEL.tolist()
    ours = battery.cash(price)[np.arange(len(settled)), [labels.index(a) for a in settled["action"]]]

    # The schedule's battery runs over every half hour in the span, as a real one would, and is
    # counted on the same half hours as ours.
    timeline = prices[prices["start_time"].between(settled["start_time"].min(), settled["start_time"].max())]
    timeline = timeline.reset_index(drop=True)
    frozen = Frozen.load()
    periods = TestPeriods(
        rows=timeline[["start_time"]],
        tables=frozen.optimiser_tables(),
        month_idx=np.zeros(len(timeline), dtype=int),
        slot=slot_of(timeline["start_time"]),
        day=(timeline["start_time"].dt.normalize() - pd.Timestamp("1970-01-01", tz="UTC")).dt.days.to_numpy(),
        realised=timeline["ssp"].to_numpy(),
    )
    schedule = periods.trade(periods.one_step(periods.table_at("profile")))
    scored = timeline["start_time"].isin(settled["start_time"]).to_numpy()
    return {
        "periods_scored": len(settled),
        "first": settled["start_time"].min().isoformat(),
        "last": settled["start_time"].max().isoformat(),
        "brier": float(np.mean((settled["p_short"].to_numpy() - short) ** 2)),
        "ours_gbp": float(ours.sum()),
        "schedule_gbp": float(schedule.pnl[scored].sum()),
        "left_out_pre_fix": ledger.loc[pre_fix(ledger), "target_start"].tolist(),
        "left_out_committed_after_the_gate": ledger.loc[late & ~pre_fix(ledger), "target_start"].tolist(),
        "every_line_decided_before_its_gate": bool(
            (pd.to_datetime(ledger["decided_at"]) < pd.to_datetime(ledger["gate"])).all()
        ),
    }


# ---------------------------------------------------------------- commands


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m gclose.live", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="rehearse one live decision from Elexon; writes and pushes nothing")
    commands.add_parser("freeze", help="fit and save the frozen model, then commit and push it")
    commands.add_parser("run", help="decide every half hour and push each decision")
    score_cmd = commands.add_parser("score", help="score the ledger once prices have printed")
    score_cmd.add_argument("--offline", action="store_true", help="use data/raw instead of Elexon")
    replay = commands.add_parser("replay", help="dry run as of a past moment, on the stored data")
    replay.add_argument("when", type=pd.Timestamp)
    replay.add_argument("--steps", type=int, default=4, help="consecutive half hours to decide")
    args = parser.parse_args()

    if args.command == "check":
        now = pd.Timestamp.now(tz="UTC")
        entry = decide(now, fetch_recent(now), freeze(load_table(), now), [])
        print(json.dumps({k: v for k, v in entry.items() if k != "inputs"}, indent=1))
        missing = [name for name, value in entry["inputs"].items() if value is None]
        print(
            f"inputs present: {len(FEATURES) - len(missing)} of {len(FEATURES)}"
            + (f"; missing {missing}" if missing else "")
        )
    elif args.command == "freeze":
        frozen = freeze(load_table(), pd.Timestamp.now(tz="UTC"))
        frozen.save()
        publish([str(MODEL.relative_to(ROOT)), str(RAW.relative_to(ROOT))], f"freeze: model {frozen.sha256()[:12]}")
        print(f"frozen at {frozen.frozen_at}: {frozen.trained_rows:,} training rows, sha256 {frozen.sha256()}")
    elif args.command == "run":
        run_forever()
    elif args.command == "score":
        days = pd.to_datetime([e["target_start"] for e in read_ledger()], utc=True)
        prices = load("prices") if args.offline else fetch_prices(days.min().date(), (days.max() + ONE_DAY).date())
        result = score(prices)
        SCORE.write_text(json.dumps(result, indent=1), encoding="utf-8")
        publish([str(SCORE.relative_to(ROOT))], f"ledger: scored {result['periods_scored']} periods")
        print(json.dumps(result, indent=1))
    else:
        when = args.when.tz_localize("UTC") if args.when.tz is None else args.when
        frozen = freeze(load_table(), when)
        entries: list[dict] = []
        for step in range(args.steps):
            now = when + step * HALF_HOUR
            entries.append(decide(now, stored_as_of(now), frozen, entries))
            e = entries[-1]
            print(
                f"decided {e['decided_at'][:16]} for {e['target_start'][:16]} (gate {e['gate'][11:16]}): "
                f"p_short {e['p_short']:.3f}, expected price {e['expected_price']:.1f}, action {e['action']:+d}, "
                f"soc {e['soc_before']:.1f} -> {e['soc_after']:.1f}"
            )


if __name__ == "__main__":
    main()
