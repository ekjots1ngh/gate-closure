"""Elexon Insights client. Public API, no key.

Two shapes of data:
  * prices: one call per settlement date, 48 (or 46/50 on clock-change days) rows.
  * vintages (WINDFOR, NDF, IMBALNGC): queried by publish window, every row carries
    publish_time and start_time, so superseded forecasts are kept.

Everything is written as parquet under data/raw/ keyed on UTC start_time.
Run: python -m gclose.ingest check                     (30-second smoke test, run this first)
     python -m gclose.ingest prices 2022-01-01 2026-10-23
     python -m gclose.ingest vintages WINDFOR 2022-01-01 2026-10-23
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

_client = httpx.Client(timeout=60, headers={"User-Agent": "gate-closure-oxhack26"})


class BadRequest(Exception):
    """Elexon said 400, usually a publish window that is too long."""


def _get(path: str, params: dict | None = None, tries: int = 5) -> dict:
    """GET with simple backoff. Elexon returns {"data": [...]} for every endpoint used here."""
    for attempt in range(tries):
        try:
            r = _client.get(f"{BASE}{path}", params={**(params or {}), "format": "json"})
        except httpx.TransportError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 400:
            raise BadRequest(f"400 on {path} {params}: {r.text[:200]}")
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    raise RuntimeError(f"gave up on {path} {params}")


def _national(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    """Keep the national boundary 'N'. WINDFOR has no boundary field, so it is national already.

    If 'N' is missing the dataset is kept whole and a warning names the boundaries seen,
    so features.build() fails loudly rather than joining on nothing.
    """
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

    The endpoint serves the refreshed (D+1) value, not the indicative one that printed
    15 minutes after the period. created_at tells you when the served row was made.
    """
    rows = _get(f"/balancing/settlement/system-prices/{d.isoformat()}").get("data", [])
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "start_time": pd.to_datetime(df["startTime"], utc=True),
        "settlement_date": df["settlementDate"],
        "settlement_period": df["settlementPeriod"],
        "created_at": pd.to_datetime(df["createdDateTime"], utc=True),
        "ssp": df["systemSellPrice"].astype(float),
        "sbp": df["systemBuyPrice"].astype(float),
        "niv": df["netImbalanceVolume"].astype(float),
    })
    return out


def fetch_prices(start: date, end: date, workers: int = 8) -> pd.DataFrame:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as ex:
        frames = list(ex.map(fetch_prices_day, days))
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    df = df.drop_duplicates("start_time").sort_values("start_time").reset_index(drop=True)
    return df


# ---------------------------------------------------------------- vintages

VINTAGE_VALUE = {"WINDFOR": "generation", "NDF": "demand", "IMBALNGC": "imbalance"}


def fetch_vintages_window(dataset: str, pub_from: datetime, pub_to: datetime) -> pd.DataFrame:
    """All rows of a forecast dataset published inside [pub_from, pub_to).

    If Elexon rejects the window as too long, split it in half and try again, down to 6 hours.
    """
    try:
        payload = _get(f"/datasets/{dataset}", {
            "publishDateTimeFrom": pub_from.strftime("%Y-%m-%dT%H:%MZ"),
            "publishDateTimeTo": pub_to.strftime("%Y-%m-%dT%H:%MZ"),
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
    out = pd.DataFrame({
        "dataset": dataset,
        "publish_time": pd.to_datetime(df["publishTime"], utc=True),
        "start_time": pd.to_datetime(df["startTime"], utc=True),
        "value": df[VINTAGE_VALUE[dataset]].astype(float),
        "boundary": df["boundary"] if "boundary" in df else "N",
    })
    return out


def fetch_vintages(dataset: str, start: date, end: date, days_per_call: int = 7, workers: int = 6) -> pd.DataFrame:
    t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    t1 = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
    windows = []
    t = t0
    while t < t1:
        windows.append((t, min(t + timedelta(days=days_per_call), t1)))
        t += timedelta(days=days_per_call)
    with ThreadPoolExecutor(workers) as ex:
        frames = list(ex.map(lambda w: fetch_vintages_window(dataset, *w), windows))
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    df = _national(df, dataset)
    df = df.drop_duplicates(["publish_time", "start_time", "boundary"]).sort_values(["start_time", "publish_time"])
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- cli

def check() -> None:
    """Thirty-second smoke test: one day of prices and of each vintage dataset."""
    d = date.today() - timedelta(days=3)
    p = fetch_prices_day(d)
    print(f"prices {d}: {len(p)} rows (expect 46, 48 or 50); niv non-null {p['niv'].notna().sum() if len(p) else 0}")
    t0 = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    for ds in VINTAGE_VALUE:
        v = fetch_vintages_window(ds, t0, t0 + timedelta(days=1))
        if v.empty:
            print(f"{ds}: NO ROWS")
            continue
        bounds = sorted(v["boundary"].astype(str).unique()) if "boundary" in v else ["(none)"]
        print(f"{ds}: {len(v)} rows, {v['publish_time'].nunique()} vintages, boundaries {bounds[:10]}")
    print("If IMBALNGC and NDF list 'N', the national filter will work. If not, tell Claude what they list.")


def main(argv: list[str]) -> None:
    kind = argv[0] if argv else "check"
    if kind == "check":
        check()
        return
    if kind == "prices":
        start, end = date.fromisoformat(argv[1]), date.fromisoformat(argv[2])
        df = fetch_prices(start, end)
        path = RAW / "prices.parquet"
    elif kind == "vintages":
        dataset, start, end = argv[1], date.fromisoformat(argv[2]), date.fromisoformat(argv[3])
        df = fetch_vintages(dataset, start, end)
        path = RAW / f"{dataset}.parquet"
    else:
        raise SystemExit("usage: python -m gclose.ingest prices START END | vintages DATASET START END")
    df.to_parquet(path, index=False)
    print(f"wrote {len(df):,} rows to {path} ({df['start_time'].min()} to {df['start_time'].max()})")
    if "publish_time" in df:
        print(f"  {df['publish_time'].nunique():,} distinct vintages")


if __name__ == "__main__":
    main(sys.argv[1:])
