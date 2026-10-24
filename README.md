# Gate Closure

Every half hour, the GB electricity system is either short of power or has too much. Whoever is on the wrong side pays a price that nobody knows until it prints. We forecast that price one hour ahead, using only what the grid had published by then, and a simulated battery takes the other side.

Built at OxHack '26 (24 to 25 October 2026, Mathematical Institute, Oxford) for the HRT challenge: best use of data for predictions and decision making. Theme of the hack: time.

## Headline

Walk-forward, July 2022 to June 2026, refitted monthly, 70,120 half hours. The holdout (July to October 2026) is still sealed and opens once on Sunday morning.

**The forecast works.** Our P(short) scores Brier 0.2291 [0.2274, 0.2309] against 0.2407 for calibrated persistence and 0.2468 for NESO's own indicated imbalance. The 90% intervals do not overlap, which is the protocol's test.

**It is worth almost nothing to a battery.** A 1 MW / 2 MWh battery on a fixed daily schedule makes £43.8 a day. Knowing the side of every half hour an hour early would make £224. Our forecast, carried forward four hours by the chain policy, makes £48.4: 2.6% [0.2%, 4.9%] of that gap, and 1.2% once the wildest 1% of days are dropped. Persistence and NESO's indicated imbalance both lose money against the schedule.

**Why: the value of skill is convex.** Shrink our errors toward the truth and watch the money: Brier 0.229 earns £46 a day, 0.129 earns £131, 0.057 earns £193. Near the coin-flip end a better Brier buys very little, because a probability between 0.4 and 0.6 rarely moves the expected price past the cost of a round trip (15% lost in the battery plus £10/MWh of wear). The forecasting metric and the decision metric disagree, and the decision metric is the one that pays.

| policy, £ per day (90% interval) | one step | chain (forecast carried 4 hours) |
|---|---|---|
| fixed schedule, no forecast | 43.8 (35.5 to 52.9) | 43.8 (identical actions) |
| ours, logistic | 46.0 (37.9 to 54.0) | 48.4 (40.4 to 56.8) |
| boosted classifier (Brier 0.2258) | 46.3 (38.0 to 54.7) | 49.0 (41.1 to 57.2) |
| calibrated persistence | 36.4 (28.7 to 45.0) | 41.4 (33.3 to 50.6) |
| NESO indicated imbalance | 27.3 (20.0 to 35.7) | 32.1 (24.2 to 40.8) |
| knowing the side (oracle) | 224.1 (203.9 to 245.6) | 223.1 (203.1 to 244.6) |

Forecasting the price directly does worse than not forecasting at all: ridge £19.8, boosted £20.5, last seen price minus £9.8 a day. They are decent on average (ridge MAE £37.8, correlation 0.75) and wrong in exactly the periods the battery acts on. The boosted classifier ties the logistic model on money, so the logistic model is the one we ship. The boosted rows move by up to £1 a day between machines and scikit-learn versions (a second laptop gave 46.6, 48.9 and £21.5); every other number here reproduced to the decimal on both.

Reproduce every number here with `make reproduce`; the tables are written to `data/out/results.json`.

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
python -m gclose.ingest pull 2022-01-01 2026-10-23               # newest month first, resumable; Ctrl+C is safe
python -m gclose.backtest                                        # walk-forward P(short) ladder, Brier with intervals
python -m gclose.price_models                                    # boosted and ridge checks (about 3 minutes)
python -m gclose.decide                                          # battery P&L for every policy, value of skill
```

The pulled months are committed under `data/raw/<dataset>/<YYYY-MM>.parquet`, so everything after `pull` reproduces with no network.

With `make`: `make test`, `make data`, `make reproduce`.

## Data

Elexon Insights API (public, no key): `/balancing/settlement/system-prices/{date}` for prices and net imbalance volume; `/datasets/WINDFOR`, `/datasets/NDF`, `/datasets/IMBALNGC` queried by publish window for forecast vintages (IMBALNGC with `boundary=N`). Wind farm sites for the map from the Renewable Energy Planning Database.

Contains BMRS data © Elexon Limited copyright and database right 2026, used under the BMRS Data Licence.

## Prior work, declared

The RMT spurious-factor paper (github.com/ekjots1ngh/rmt-spurious-factors) and the systematic-trading repository are earlier work by the author, cited for context only; no code from either is used here. Nothing from Cabestan Quant Research is used.

## Layout

```
PROTOCOL.md              fixed before any result, with dated amendments
gclose/ingest.py         Elexon client, monthly parquet under data/raw/
gclose/store.sql         Tiger Data hypertables and the as-of join in SQL
gclose/features.py       gate-safe features via one merge_asof per dataset; poison()
gclose/models.py         the P(short) ladder: coin, persistence, calibrated persistence, NESO indicated, ours
gclose/backtest.py       monthly walk-forward of the ladder, Brier with intervals
gclose/price_models.py   the "would a fancier model help" check: ridge and boosted price, boosted P(short)
gclose/battery.py        1 MW / 2 MWh battery: vectorised dynamic programme, sequential path
gclose/decide.py         one optimiser, many forecasts: one-step and chain policies, money, value of skill
gclose/stats.py          week-block bootstrap, vectorised
gclose/export.py         web/public/replay.json for the demo
tests/                   poison test; DP checked against a scalar loop; loss limit and SoC bounds
```

Full pipeline from the committed raw data, about four minutes on a laptop (most of it the boosted models): `make reproduce`, or run the `python -m` lines in the Makefile in order.
