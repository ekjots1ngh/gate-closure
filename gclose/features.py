"""Point-in-time feature table: one row per half hour, built only from what was public at its gate.

The rule: the decision for period t (starting at T) is made at the gate, T - 60 min. A forecast
row may be used only if its publish_time is strictly before the gate, and a price only if it
was first printed strictly before the gate. Prices usually print about 52 minutes after their
period starts, so the newest price visible at the gate is normally t-4's; when that one printed
late, its features are left missing rather than borrowed from the future.

Known limitation: from February 2024 the stored price values are Elexon's next-day revisions,
not the first prints (PROTOCOL.md amendment 4). The timing rule is enforced exactly; the values
in that era may differ slightly from what was printed.

Lags are taken by row on the time-sorted table. Where Elexon is missing a period (a handful of
days have 45 or 47), a lag reaches slightly further back: staler, never later.

Run: python -m gclose.features   ->  data/out/features.parquet (about 12 seconds)
"""

from __future__ import annotations

import time

import pandas as pd

from . import FIRST_PRINT_DELAY, GATE_LEAD, OUT, PERIODS_PER_DAY, PRICE_LAG_PERIODS, REFRESHED_AFTER
from .ingest import DATASETS, load

TS = "datetime64[ns, UTC]"  # one timestamp dtype everywhere: merge_asof refuses mixed resolutions
TABLE = OUT / "features.parquet"

FEATURES = [
    # The system's recent state: the newest printed periods (normally t-4, t-5, t-6).
    "short_newest",
    "short_prev1",
    "short_prev2",
    "niv_newest",
    "niv_prev1",
    "price_newest",
    "price_day_mean",
    "price_day_std",
    "short_run_length",
    # Forecasts as they stood at the gate.
    "wind_latest",
    "wind_revision",
    "demand_latest",
    "demand_revision",
    "indicated_latest",
    # The clock, in UTC.
    "hour",
    "weekday",
]


def first_print_at(prices: pd.DataFrame) -> pd.Series:
    """When each price was first public: created_at if that is the first print, else the median delay.

    A row with no created_at has not printed at all (the live record's placeholders for periods
    still to come), so it stays NaT and is never treated as public.
    """
    start, created = prices["start_time"].astype(TS), prices["created_at"].astype(TS)
    refreshed = created - start >= REFRESHED_AFTER
    return created.where(~refreshed, start + FIRST_PRINT_DELAY)


def _latest_before(keys: pd.Series, at: pd.Series, vintages: pd.DataFrame) -> pd.DataFrame:
    """Newest vintage for each row: start_time == keys[i] and publish_time strictly before at[i].

    One merge_asof does this for every row at once: rows are sorted by `at`, vintages by
    publish_time, and `by` keeps each forecast matched to its own target period.
    Returns `value` and `publish_time`, aligned to the input index (NaN where none exists).
    """
    left = pd.DataFrame({"start_time": keys.astype(TS), "at": at.astype(TS)}, index=keys.index)
    left = left.dropna().reset_index().sort_values("at")
    right = vintages[["start_time", "publish_time", "value"]].astype({"start_time": TS, "publish_time": TS})
    matched = pd.merge_asof(
        left,
        right.sort_values("publish_time"),
        left_on="at",
        right_on="publish_time",
        by="start_time",
        direction="backward",
        allow_exact_matches=False,
    )
    return matched.set_index("index")[["value", "publish_time"]].reindex(keys.index)


def _latest_and_previous(keys: pd.Series, gate: pd.Series, vintages: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """The newest vintage before the gate, and the one before that (for revision features)."""
    latest = _latest_before(keys, gate, vintages)
    previous = _latest_before(keys, latest["publish_time"], vintages)
    return latest["value"], previous["value"]


def _require_national(vintages: pd.DataFrame, name: str) -> pd.DataFrame:
    """National rows only. Fails loudly: a silent empty join would make a baseline meaningless."""
    if "boundary" in vintages:
        vintages = vintages[vintages["boundary"].astype(str) == "N"]
    if vintages.empty:
        raise ValueError(f"{name}: no national (boundary 'N') rows; run `python -m gclose.ingest check`")
    return vintages


def build(prices: pd.DataFrame, windfor: pd.DataFrame, ndf: pd.DataFrame, imbalngc: pd.DataFrame) -> pd.DataFrame:
    """Targets and gate-safe features, one row per settlement period, sorted by start_time."""
    p = prices[["start_time", "created_at", "ssp", "niv"]].sort_values("start_time").reset_index(drop=True)
    p = p.astype({"start_time": TS, "created_at": TS})
    p["gate"] = p["start_time"] - GATE_LEAD
    p["short"] = (p["niv"] > 0).astype(float).where(p["niv"].notna())  # unknown until the volume prints
    printed = first_print_at(p)

    def printed_by_gate(column: str, rows_back: int) -> pd.Series:
        """`column` of the period `rows_back` rows earlier, or NaN if its price had not printed by this gate."""
        return p[column].shift(rows_back).where(printed.shift(rows_back) < p["gate"])

    # The rolling statistics run over `price_newest`, whose every value was public at its own
    # row's gate, and so at every later gate too.
    newest = PRICE_LAG_PERIODS
    p["short_newest"] = printed_by_gate("short", newest)
    p["short_prev1"] = printed_by_gate("short", newest + 1)
    p["short_prev2"] = printed_by_gate("short", newest + 2)
    p["niv_newest"] = printed_by_gate("niv", newest)
    p["niv_prev1"] = printed_by_gate("niv", newest + 1)
    p["price_newest"] = printed_by_gate("ssp", newest)
    day = p["price_newest"].rolling(PERIODS_PER_DAY, min_periods=PERIODS_PER_DAY // 2)
    p["price_day_mean"], p["price_day_std"] = day.mean(), day.std()
    side = p["short_newest"]
    p["short_run_length"] = side.groupby((side != side.shift()).cumsum()).cumcount() + 1

    # A late cut to the wind forecast is the mechanism behind a short system, so the revision
    # (latest minus previous vintage) is the feature with a physical story. WINDFOR is hourly,
    # so it is matched on the hour.
    p["wind_latest"], wind_previous = _latest_and_previous(p["start_time"].dt.floor("h"), p["gate"], windfor)
    p["wind_revision"] = p["wind_latest"] - wind_previous
    ndf = _require_national(ndf, "NDF")
    p["demand_latest"], demand_previous = _latest_and_previous(p["start_time"], p["gate"], ndf)
    p["demand_revision"] = p["demand_latest"] - demand_previous
    indicated = _require_national(imbalngc, "IMBALNGC")
    p["indicated_latest"] = _latest_before(p["start_time"], p["gate"], indicated)["value"]

    p["hour"] = p["start_time"].dt.hour
    p["weekday"] = p["start_time"].dt.weekday
    return p


def load_table() -> pd.DataFrame:
    """The feature table written by `python -m gclose.features`."""
    if not TABLE.exists():
        raise FileNotFoundError(f"{TABLE} is missing; run `python -m gclose.features` first")
    return pd.read_parquet(TABLE)


def main() -> None:
    started = time.time()
    table = build(*(load(name) for name in DATASETS))
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(TABLE, index=False)
    print(f"{len(table):,} half hours in {time.time() - started:.0f}s; share missing per feature:")
    print(table[FEATURES].isna().mean().round(3).to_string())


if __name__ == "__main__":
    main()
