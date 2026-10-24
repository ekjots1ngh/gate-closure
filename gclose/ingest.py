"""Elexon Insights client. Public API, no key.

Two shapes of data:
  * prices: one call per settlement date, 48 (or 46/50 on clock-change days) rows.
  * vintages (WINDFOR, NDF, IMBALNGC): queried by publish window, every row carries
    publish_time and start_time, so superseded forecasts are kept.

Data lands in one parquet file per dataset per month, data/raw/<dataset>/<YYYY-MM>.parquet,
so a slow or interrupted pull is resumable and every finished month is usable at once.

Run: python -m gclose.ingest check                          30-second smoke test, run this first
     python -m gclose.ingest pull 2025-07-01 2026-10-23     newest month first, resumable
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

_client = httpx.Client(timeout=90, headers={"User-Agent": "gate-closure-oxhack26"})
_stats = {"bytes": 0}

# IMBALNGC carries 18 boundaries (B1..B17, N); asking for N server-side cuts the download 18x.
SERVER_FILTER = {"IMBALNGC": {"boundary": "N"}}
VINTAGE_VALUE = {"WINDFOR": "generation", "NDF": "demand", "IMBALNGC": "imbalance"}
DATASETS = ("prices", "WINDFOR", "NDF", "IMBALNGC")


class BadRequest(Exception):
    """Elexon said 400, usually a publish window that is too long."""


def _get(path: str, params: dict | None = None, tries: int = 6) -> dict:
    """GET with backoff. Elexon returns {"data": [...]} for every endpoint used here."""
    for attempt in range(tries):
        try:
            r = _client.get(f"{BASE}{path}", params={**(params or {}), "format": "json"})
        except httpx.TransportError:
            time.sleep(min(2 ** attempt, 30))
            continue
        _stats["bytes"] += r.num_bytes_downloaded
        if r.status_code == 200:
            return r.json()
        if r.status_code == 400:
            raise BadRequest(f"400 on {path} {params}: {r.text[:200]}")
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 30))
            continue
        r.raise_for_status()
    raise RuntimeError(f"gave up on {path} {params}")


def _national(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Keep the national boundary 'N'. WINDFOR has no boundary field, so it is national already."""
    if df.empty or "boundary" not in df or df["boundary"].isna().all():
        return df.assign(boundary="N")
    b = df["boundary"].astype(str)
    if (b == "N").any():
        return df[b == "N"]
    print(f"warning: {dataset} has no boundary 'N'; seen {b.value_counts().head(8).to_dict()}", file=sys.stderr)
    return df


# ---------------------------------------------------------------- prices

def fetch_prices_day(d: date) -> pd.DataFrame:
    """System sell/buy price and net imbalance volume for one settlement date.

    From February 2024 the endpoint serves the value as refreshed the next day; before that,
    the first print (about 52 minutes after the period starts). created_at says when the
    served row was made; gclose.features.first_print_at turns it into a print time.
    """
    rows = _get(f"/balancing/settlement/system-prices/{d.isoformat()}").get("data", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "start_time": pd.to_datetime(df["startTime"], utc=True),
        "settlement_date": df["settlementDate"],
        "settlement_period": df["settlementPeriod"],
        "created_at": pd.to_datetime(df["createdDateTime"], utc=True),
        "ssp": df["systemSellPrice"].astype(float),
        "sbp": df["systemBuyPrice"].astype(float),
        "niv": df["netImbalanceVolume"].astype(float),
    })


def fetch_prices(start: date, end: date, workers: int = 8) -> pd.DataFrame:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as ex:
        frames = list(ex.map(fetch_prices_day, days))
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return df.drop_duplicates("start_time").sort_values("start_time").reset_index(drop=True)


# ---------------------------------------------------------------- vintages

def fetch_vintages_window(dataset: str, pub_from: datetime, pub_to: datetime) -> pd.DataFrame:
    """All rows of a forecast dataset published inside [pub_from, pub_to).

    If Elexon rejects the window as too long, split it in half and try again, down to 6 hours.
    """
    try:
        payload = _get(f"/datasets/{dataset}", {
            "publishDateTimeFrom": pub_from.strftime("%Y-%m-%dT%H:%MZ"),
            "publishDateTimeTo": pub_to.strftime("%Y-%m-%dT%H:%MZ"),
            **SERVER_FILTER.get(dataset, {}),
        })
    except BadRequest:
        if pub_to - pub_from <= timedelta(hours=6):
            raise
        mid = pub_from + (pub_to - pub_from) / 2
        halves = [fetch_vintages_window(dataset, pub_from, mid), fetch_vintages_window(dataset, mid, pub_to)]
        halves = [h for h in halves if not h.empty]
        return pd.concat(halves, ignore_index=True) if halves else pd.DataFrame()
    rows = payload.get("data", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "publish_time": pd.to_datetime(df["publishTime"], utc=True),
        "start_time": pd.to_datetime(df["startTime"], utc=True),
        "value": df[VINTAGE_VALUE[dataset]].astype(float),
        "boundary": df["boundary"].astype(str) if "boundary" in df else "N",
    })


def fetch_vintages(dataset: str, start: date, end: date, days_per_call: int = 7, workers: int = 6) -> pd.DataFrame:
    t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    t1 = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
    windows, t = [], t0
    while t < t1:
        windows.append((t, min(t + timedelta(days=days_per_call), t1)))
        t += timedelta(days=days_per_call)
    with ThreadPoolExecutor(workers) as ex:
        frames = list(ex.map(lambda w: fetch_vintages_window(dataset, *w), windows))
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    df = _national(pd.concat(frames, ignore_index=True), dataset)
    df = df.drop_duplicates(["publish_time", "start_time", "boundary"]).sort_values(["start_time", "publish_time"])
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- monthly, resumable pull

def _months(start: date, end: date):
    m = date(start.year, start.month, 1)
    while m <= end:
        nxt = date(m.year + m.month // 12, m.month % 12 + 1, 1)
        yield max(m, start), min(nxt - timedelta(days=1), end), f"{m:%Y-%m}"
        m = nxt


def pull(start: date, end: date, datasets=DATASETS) -> None:
    """Newest month first; each month completes every dataset before the next month starts,
    so the newest N months are always a usable contiguous block. Finished months are skipped
    on a rerun, except the month containing `end`, which is always refreshed."""
    months = list(_months(start, end))[::-1]
    t_start = time.time()
    for m0, m1, tag in months:
        for ds in datasets:
            path = RAW / ds / f"{tag}.parquet"
            if path.exists() and not (m0 <= end <= m1):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            b0, t0 = _stats["bytes"], time.time()
            df = fetch_prices(m0, m1) if ds == "prices" else fetch_vintages(ds, m0, m1)
            if df.empty:
                print(f"{tag} {ds:9s} NO ROWS")
                continue
            df.to_parquet(path, index=False)
            mb, secs = (_stats["bytes"] - b0) / 1e6, time.time() - t0
            print(f"{tag} {ds:9s} {len(df):>8,} rows  {mb:6.1f} MB  {secs:5.0f}s  {mb * 1000 / max(secs, 1):6.0f} kB/s"
                  f"   total {(_stats['bytes']) / 1e6:.0f} MB in {(time.time() - t_start) / 60:.1f} min", flush=True)


def load(dataset: str) -> pd.DataFrame:
    """Every month pulled so far for one dataset, deduplicated and sorted."""
    files = sorted((RAW / dataset).glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no data for {dataset} under {RAW / dataset}; run `python -m gclose.ingest pull ...`")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    if dataset == "prices":
        return df.drop_duplicates("start_time").sort_values("start_time").reset_index(drop=True)
    return df.drop_duplicates(["publish_time", "start_time", "boundary"]).sort_values(["start_time", "publish_time"]).reset_index(drop=True)


# ---------------------------------------------------------------- cli

def check() -> None:
    """Thirty-second smoke test: one day of prices and of each vintage dataset."""
    d = date.today() - timedelta(days=3)
    t0w = time.time()
    p = fetch_prices_day(d)
    print(f"prices {d}: {len(p)} rows (expect 46, 48 or 50); niv non-null {p['niv'].notna().sum() if len(p) else 0}")
    t0 = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    for ds in VINTAGE_VALUE:
        v = _national(fetch_vintages_window(ds, t0, t0 + timedelta(days=1)), ds)
        if v.empty:
            print(f"{ds}: NO ROWS")
            continue
        has_n = (v["boundary"].astype(str) == "N").all()
        print(f"{ds}: {len(v)} national rows, {v['publish_time'].nunique()} vintages, all boundary N: {has_n}")
    secs = time.time() - t0w
    print(f"downloaded {_stats['bytes'] / 1e6:.2f} MB in {secs:.1f}s ({_stats['bytes'] / 1e3 / max(secs, 0.1):.0f} kB/s)")
    print(f"one full day of all four datasets is about {_stats['bytes'] / 1e6:.2f} MB, so a year is about "
          f"{_stats['bytes'] * 365 / 1e6:.0f} MB at this rate of compression")


def main(argv: list[str]) -> None:
    kind = argv[0] if argv else "check"
    if kind == "check":
        check()
    elif kind == "pull":
        start, end = date.fromisoformat(argv[1]), date.fromisoformat(argv[2])
        datasets = tuple(argv[3].split(",")) if len(argv) > 3 else DATASETS
        pull(start, end, datasets)
    else:
        raise SystemExit("usage: python -m gclose.ingest check | pull START END [prices,WINDFOR,NDF,IMBALNGC]")


if __name__ == "__main__":
    main(sys.argv[1:])
