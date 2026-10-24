# Gate Closure

Every half hour, the GB electricity system is either short of power or has too much. Whoever is on the wrong side pays a price that nobody knows until it prints. We forecast that price one hour ahead, using only what the grid had published by then, and a simulated battery takes the other side.

Built at OxHack '26 (24 to 25 October 2026, Mathematical Institute, Oxford) for the HRT challenge: best use of data for predictions and decision making. Theme of the hack: time.

## Headline

(filled in on Sunday morning from `data/out/walkforward.csv`; the protocol was fixed before any result, see `PROTOCOL.md`)

## Why this is honest

- Every forecast input is an Elexon vintage keyed by `publish_time`, joined as-of one hour before each period. See `asof_features()` in `gclose/store.sql` and its pandas twin in `gclose/features.py`.
- The newest price the model can see is four periods old: period t-3 ends exactly at gate closure and its indicative price prints 15 minutes later.
- `tests/test_poison.py` overwrites everything published after each decision time with noise and asserts no feature changes. Press P in the demo to run it on the real cache.
- From midnight on Saturday the frozen model writes its forecast and action for period t+2 to an append-only ledger with a server timestamp, and pushes a JSON line here before the period starts (`gclose/live.py`, `ledger/`).
- The clocks went back at 02:00 on Sunday 25 October 2026, so that day has 50 settlement periods. Everything is keyed on UTC `start_time`; `settlementPeriod` is never used for arithmetic.

## Run it

Works the same on Windows, macOS and Linux; `make` is optional.

```
git clone https://github.com/ekjots1ngh/gate-closure
cd gate-closure
pip install -r requirements.txt
python -m pytest -q tests                                        # poison test on synthetic data, no network
python -m gclose.ingest check                                    # 30-second Elexon smoke test, prints kB/s
python -m gclose.ingest pull 2025-07-01 2026-10-23               # newest month first, resumable; Ctrl+C is safe
python -m gclose.backtest                                        # walk-forward ladder + battery table with intervals
```

The pulled months are committed under `data/raw/<dataset>/<YYYY-MM>.parquet`, so `python -m gclose.backtest` reproduces the headline with no network.
```

With `make`: `make test`, `make data`, `make backtest`, `make reproduce`.

## Data

Elexon Insights API (public, no key): `/balancing/settlement/system-prices/{date}` for prices and net imbalance volume; `/datasets/WINDFOR`, `/datasets/NDF`, `/datasets/IMBALNGC` queried by publish window for forecast vintages (IMBALNGC with `boundary=N`). Wind farm sites for the map from the Renewable Energy Planning Database.

Contains BMRS data © Elexon Limited copyright and database right 2026, used under the BMRS Data Licence.

## Prior work, declared

The RMT spurious-factor paper (github.com/ekjots1ngh/rmt-spurious-factors) and the systematic-trading repository are earlier work by the author, cited for context only; no code from either is used here. Nothing from Cabestan Quant Research is used.

## Layout

```
PROTOCOL.md          fixed before any result
gclose/ingest.py     Elexon client, parquet under data/raw/
gclose/store.sql     Tiger Data hypertables and the as-of join
gclose/features.py   gate-safe features, poison()
gclose/models.py     coin, persistence, NESO indicated, ours; price quantiles
gclose/battery.py    1 MW / 2 MWh battery, policies
gclose/backtest.py   walk-forward, week-block bootstrap, headline tables
tests/               poison test
web/                 Next.js replay UI (tape, dial, map)
```
