"""Elexon Insights client and the raw data store. Public API, no key.

Two shapes of data:
  * prices: one call per settlement date, 48 rows (46 or 50 on clock-change days).
  * vintages (WINDFOR, NDF, IMBALNGC): queried by publish window. Every row carries its
    publish_time and target start_time, so superseded forecasts are kept, not overwritten.

Data lands in one parquet file per dataset per month, data/raw/<dataset>/<YYYY-MM>.parquet,
so an interrupted pull resumes where it stopped and every finished month is usable at once.

Run: python -m gclose.ingest check                          30-second smoke test, run this first
     python -m gclose.ingest pull 2022-01-01 2026-10-23     newest month first, resumable
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from functools import cache

import httpx
import pandas as pd

from . import RAW

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
RETRYABLE = {429, 500, 502, 503, 504}
SHORTEST_WINDOW = timedelta(hours=6)  # a rejected publish window is halved down to this

VINTAGE_VALUE = {"WINDFOR": "generation", "NDF": "demand", "IMBALNGC": "imbalance"}
VINTAGE_KEY = ["publish_time", "start_time", "boundary"]
# IMBALNGC carries 18 boundaries (B1 to B17, and N); asking for N server-side cuts the download 18x.
SERVER_FILTER = {"IMBALNGC": {"boundary": "N"}}
DATASETS = ("prices", "WINDFOR", "NDF", "IMBALNGC")

_downloaded = {"bytes": 0}  # for the speed readout


class BadRequestError(Exception):
    """Elexon answered 400, usually because a publish window was too long."""


@cache
def _client() -> httpx.Client:
    return httpx.Client(timeout=90, headers={"User-Agent": "gate-closure-oxhack26"})


def _get(path: str, params: dict | None = None, tries: int = 6) -> dict:
    """GET with exponential backoff. Every endpoint used here answers {"data": [...]}."""
    for attempt in range(tries):
        try:
            r = _client().get(f"{BASE}{path}", params={**(params or {}), "format": "json"})
        except httpx.TransportError:
            time.sleep(min(2**attempt, 30))
            continue
        _downloaded["bytes"] += r.num_bytes_downloaded
        if r.status_code == httpx.codes.OK:
            return r.json()
        if r.status_code == httpx.codes.BAD_REQUEST:
            raise BadRequestError(f"400 on {path} {params}: {r.text[:200]}")
        if r.status_code in RETRYABLE:
            time.sleep(min(2**attempt, 30))
            continue
        r.raise_for_status()
    raise RuntimeError(f"gave up on {path} {params}")


def _national_rows(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Keep the national boundary at download time. WINDFOR has no boundary field: it is national.

    Lenient on purpose, so a surprise in Elexon's data is stored and visible rather than lost;
    gclose.features refuses to build from a dataset with no national rows.
    """
    if df.empty or "boundary" not in df or df["boundary"].isna().all():
        return df.assign(boundary="N")
    national = df["boundary"].astype(str) == "N"
    if national.any():
        return df[national]
    print(
        f"warning: {dataset} has no boundary 'N'; saw {df['boundary'].value_counts().head(8).to_dict()}",
        file=sys.stderr,
    )
    return df


def fetch_prices_day(d: date) -> pd.DataFrame:
    """System sell/buy price and net imbalance volume for one settlement date.

    From February 2024 the endpoint serves each value as refreshed the next day; before that,
    the first print. created_at says when the served row was made, and
    gclose.features.first_print_at turns it into a print time.
    """
    rows = _get(f"/balancing/settlement/system-prices/{d.isoformat()}").get("data", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return pd.DataFrame(
        {
            "start_time": pd.to_datetime(df["startTime"], utc=True),
            "settlement_date": df["settlementDate"],
            "settlement_period": df["settlementPeriod"],
            "created_at": pd.to_datetime(df["createdDateTime"], utc=True),
            "ssp": df["systemSellPrice"].astype(float),
            "sbp": df["systemBuyPrice"].astype(float),
            "niv": df["netImbalanceVolume"].astype(float),
        }
    )


def fetch_prices(start: date, end: date, workers: int = 8) -> pd.DataFrame:
    """Prices for every settlement date from start to end inclusive, one row per period."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as pool:
        frames = [f for f in pool.map(fetch_prices_day, days) if not f.empty]
    if not frames:
        return pd.DataFrame()
    return _tidy(pd.concat(frames, ignore_index=True), "prices")


def fetch_vintages_window(dataset: str, pub_from: datetime, pub_to: datetime) -> pd.DataFrame:
    """Every row of a forecast dataset published inside [pub_from, pub_to).

    If Elexon rejects the window as too long, it is split in half and retried, down to
    SHORTEST_WINDOW.
    """
    try:
        payload = _get(
            f"/datasets/{dataset}",
            {
                "publishDateTimeFrom": pub_from.strftime("%Y-%m-%dT%H:%MZ"),
                "publishDateTimeTo": pub_to.strftime("%Y-%m-%dT%H:%MZ"),
                **SERVER_FILTER.get(dataset, {}),
            },
        )
    except BadRequestError:
        if pub_to - pub_from <= SHORTEST_WINDOW:
            raise
        mid = pub_from + (pub_to - pub_from) / 2
        halves = [fetch_vintages_window(dataset, pub_from, mid), fetch_vintages_window(dataset, mid, pub_to)]
        halves = [h for h in halves if not h.empty]
        return pd.concat(halves, ignore_index=True) if halves else pd.DataFrame()
    rows = payload.get("data", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return pd.DataFrame(
        {
            "publish_time": pd.to_datetime(df["publishTime"], utc=True),
            "start_time": pd.to_datetime(df["startTime"], utc=True),
            "value": df[VINTAGE_VALUE[dataset]].astype(float),
            "boundary": df["boundary"].astype(str) if "boundary" in df else "N",
        }
    )


def fetch_vintages(dataset: str, start: date, end: date, days_per_call: int = 7, workers: int = 6) -> pd.DataFrame:
    """Every national vintage of a forecast dataset published from start to end inclusive."""
    t0 = datetime(start.year, start.month, start.day, tzinfo=UTC)
    t1 = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    return fetch_vintages_between(dataset, t0, t1, days_per_call, workers)


def fetch_vintages_between(
    dataset: str, t0: datetime, t1: datetime, days_per_call: int = 7, workers: int = 6
) -> pd.DataFrame:
    """Every national vintage of a forecast dataset published in [t0, t1), in parallel windows."""
    step = timedelta(days=days_per_call)
    windows = [(t, min(t + step, t1)) for t in pd.date_range(t0, t1, freq=step, inclusive="left")]
    with ThreadPoolExecutor(workers) as pool:
        frames = [f for f in pool.map(lambda w: fetch_vintages_window(dataset, *w), windows) if not f.empty]
    if not frames:
        return pd.DataFrame()
    return _tidy(_national_rows(pd.concat(frames, ignore_index=True), dataset), dataset)


def _tidy(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Drop repeated rows and sort, the same way for freshly fetched and stored data."""
    if dataset == "prices":
        df = df.drop_duplicates("start_time").sort_values("start_time")
    else:
        df = df.drop_duplicates(VINTAGE_KEY).sort_values(["start_time", "publish_time"])
    return df.reset_index(drop=True)


def _months(start: date, end: date) -> Iterator[tuple[date, date, str]]:
    """(first day, last day, "YYYY-MM") for each calendar month touching [start, end], clipped to it."""
    month = date(start.year, start.month, 1)
    while month <= end:
        following = date(month.year + month.month // 12, month.month % 12 + 1, 1)
        yield max(month, start), min(following - timedelta(days=1), end), f"{month:%Y-%m}"
        month = following


def pull(start: date, end: date, datasets: tuple[str, ...] = DATASETS) -> None:
    """Pull newest month first, every dataset for a month before the next month starts.

    The newest N months are therefore always a usable contiguous block. Finished months are
    skipped on a rerun, except the month containing `end`, which is always refreshed.
    """
    started = time.time()
    for first, last, tag in reversed(list(_months(start, end))):
        for name in datasets:
            path = RAW / name / f"{tag}.parquet"
            if path.exists() and not (first <= end <= last):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            bytes_before, t0 = _downloaded["bytes"], time.time()
            df = fetch_prices(first, last) if name == "prices" else fetch_vintages(name, first, last)
            if df.empty:
                print(f"{tag} {name:9s} NO ROWS")
                continue
            df.to_parquet(path, index=False)
            mb, secs = (_downloaded["bytes"] - bytes_before) / 1e6, time.time() - t0
            print(
                f"{tag} {name:9s} {len(df):>8,} rows  {mb:6.1f} MB  {secs:5.0f}s  {mb * 1000 / max(secs, 1):6.0f} kB/s"
                f"   total {_downloaded['bytes'] / 1e6:.0f} MB in {(time.time() - started) / 60:.1f} min",
                flush=True,
            )


def load(dataset: str) -> pd.DataFrame:
    """Every month pulled so far for one dataset, deduplicated and sorted."""
    files = sorted((RAW / dataset).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no data for {dataset} under {RAW / dataset}; run `python -m gclose.ingest pull ...`")
    return _tidy(pd.concat([pd.read_parquet(f) for f in files], ignore_index=True), dataset)


def check() -> None:
    """Thirty-second smoke test: one day of prices and of each forecast dataset."""
    day = date.today() - timedelta(days=3)
    started = time.time()
    prices = fetch_prices_day(day)
    print(
        f"prices {day}: {len(prices)} rows (expect 46, 48 or 50); niv present on "
        f"{prices['niv'].notna().sum() if len(prices) else 0}"
    )
    t0 = datetime(day.year, day.month, day.day, tzinfo=UTC)
    for name in VINTAGE_VALUE:
        rows = _national_rows(fetch_vintages_window(name, t0, t0 + timedelta(days=1)), name)
        print(f"{name}: {len(rows)} national rows, {rows['publish_time'].nunique() if len(rows) else 0} vintages")
    secs = time.time() - started
    mb = _downloaded["bytes"] / 1e6
    print(
        f"downloaded {mb:.2f} MB in {secs:.1f}s ({mb * 1000 / max(secs, 0.1):.0f} kB/s); "
        f"a year of all four datasets is about {mb * 365:.0f} MB"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m gclose.ingest", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="thirty-second smoke test against the live API")
    pull_cmd = commands.add_parser("pull", help="pull months into data/raw, newest first")
    pull_cmd.add_argument("start", type=date.fromisoformat)
    pull_cmd.add_argument("end", type=date.fromisoformat)
    pull_cmd.add_argument("--datasets", default=",".join(DATASETS), help="comma-separated subset")
    args = parser.parse_args()
    if args.command == "check":
        check()
    else:
        pull(args.start, args.end, tuple(args.datasets.split(",")))


if __name__ == "__main__":
    main()
