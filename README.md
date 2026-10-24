# Gate Closure

Every half hour, the GB electricity system is either short of power or has too much. Whoever is on the wrong side pays a price that nobody knows until it prints. We forecast which side the grid will be on, one hour ahead, using only what had been published by then, and a simulated battery trades on the forecast.

Built at OxHack '26 (24 to 25 October 2026, Mathematical Institute, Oxford) for the HRT challenge: best use of data for predictions and decision making. Theme of the hack: time.

## Headline

Walk-forward, July 2022 to June 2026, refitted monthly, 70,120 half hours. The holdout (July to October 2026) is still sealed and opens once on Sunday morning. All intervals are 90%, resampling whole weeks.

**The forecast works.** Our P(short) scores Brier 0.2293 against 0.2409 for calibrated persistence and 0.2468 for NESO's own indicated imbalance. Paired over the same weeks, ours is better by 0.0117 [0.0106, 0.0127] and 0.0175 [0.0159, 0.0191]. Log loss agrees (0.650 against 0.675 and 0.687).

**It makes a little money, and we can say how much.** A 1 MW / 2 MWh battery on a fixed daily schedule makes £42.9 a day. With our forecast carried forward (the chain policy) it makes £48.3, a gain of £5.4 a day [£1.0, £9.7]. For scale: knowing the side of each half hour an hour early would make £223, and knowing every price in advance £345. Persistence and NESO's indicated imbalance both lose money against the schedule.

**The exchange rate between accuracy and money.** Scale our errors toward the truth or away from it and the money moves in a nearly straight line: about £8 to £10 a day for every 0.01 of Brier, all the way from a coin flip down to Brier 0.06. That prices our 0.0117 edge over persistence at about £10 a day; we measure £8.4. The line has an intercept that matters. A forecast with coin-flip accuracy that still trades makes £24 to £30 a day, less than the schedule's £42.9, because acting on noise costs money. So the first 0.02 of Brier only pays for the right to act on a forecast at all. That is roughly where we are, which is why a clearly better forecast earns only £5 a day more.

| policy, £ per day (90% interval) | one step | chain (forecast carried forward) |
|---|---|---|
| fixed schedule, no forecast | 42.9 (34.5 to 51.8) | 42.9 (identical actions) |
| ours, logistic | 46.0 (38.0 to 53.9) | 48.3 (40.2 to 56.4) |
| boosted classifier (Brier 0.2259) | 46.3 (38.2 to 54.9) | 50.0 (41.8 to 58.7) |
| calibrated persistence | 35.6 (28.1 to 44.1) | 39.9 (31.8 to 49.0) |
| NESO indicated imbalance | 27.0 (19.7 to 35.4) | 31.8 (24.0 to 40.5) |
| knowing the side an hour early | 224.2 (204.2 to 245.9) | 223.1 (203.1 to 244.7) |
| perfect hindsight, every price known | 344.7 (319.2 to 371.0) | |

**How robust the £5.4 is.** Leaving out the top 1% of half hours by absolute price, as the protocol specifies: £5.0 [£0.4, £9.8]. Leaving out the top 1% of days, a harsher cut: £2.1 [-£4.1, £7.5], which we cannot tell apart from zero. By era: in the clean first-print era (to January 2024) ours beats the schedule by £9.4 a day and persistence by 0.0127 Brier; after it, by £2.7 and 0.0110.

The boosted classifier beats the logistic model on Brier but not clearly on money (£1.7 a day [-£1.8, £5.0] in the chain), so the logistic model is the one we ship. Its rows can move by about £1 a day between scikit-learn versions; every other number reproduces to the decimal across machines.

Forecasting the price directly earns less than the schedule: ridge £19.7, boosted £23.6, last price seen minus £8.8 a day. Ridge is decent on average (MAE £37.8, correlation 0.75) but too optimistic exactly when it acts: when it sells it expected £129 on average and got £113.

Every number here comes from `make reproduce` and is written to `data/out/results.json`.

## Why this is honest, and what is not

- Forecast inputs (wind, demand, NESO's indicated imbalance) are Elexon vintages keyed by `publish_time`, joined as-of strictly before each gate, one hour before the period.
- A price is used only if it had printed before the gate. Prices usually print about 52 minutes after their period starts, so the newest one visible is normally four periods old; when that one printed late, its features are left missing.
- **Known limitation.** From February 2024 Elexon serves each price as revised the next day and the first print is not kept, so in that era our price-based inputs use revised values that were not public at the gate (the timing rule is still enforced, assuming the usual 52-minute print). Results are reported for both eras above; the edge holds in the clean one. PROTOCOL.md amendment 4 has the details.
- Models are refitted each month on outcomes that were public at that month's first gate, and fill gaps with the training window's medians.
- `tests/test_poison.py` replaces everything published after a cutoff with noise, with a cutoff one minute before every publication in a two-day window, and asserts that nothing decided before each cutoff changes. It also plants five leaks (late prints ignored, a one-period price lag, gates at 45, 30 and 0 minutes) and checks each one is caught. On a real week, `python -m gclose.export` runs the same check end to end: 0 of 170 inputs, forecasts and battery decisions change.
- The battery's daily loss limit only sees its own cash once the prices behind it have printed.
- The clocks went back at 02:00 on Sunday 25 October 2026, so that day has 50 settlement periods. Everything is keyed on UTC `start_time`; `settlementPeriod` is never used for arithmetic.
- Not built yet: the live ledger from the model freeze (each forecast and action written down before its half hour) and the demo screen.

## Run it

Works the same on Windows, macOS and Linux; `make` is optional.

```
git clone https://github.com/ekjots1ngh/gate-closure
cd gate-closure
pip install -r requirements.txt
python -m pytest -q tests                                        # about 45 seconds, no network
python -m gclose.ingest check                                    # 30-second Elexon smoke test, prints kB/s
python -m gclose.ingest pull 2022-01-01 2026-10-23               # newest month first, resumable; Ctrl+C is safe
python -m gclose.backtest                                        # walk-forward P(short) ladder, Brier with intervals
python -m gclose.price_models                                    # boosted and ridge checks (about 1.5 minutes)
python -m gclose.decide                                          # battery P&L for every policy, value of skill
```

The pulled months are committed under `data/raw/<dataset>/<YYYY-MM>.parquet`, so everything after `pull` reproduces with no network.

With `make`: `make test`, `make data`, `make reproduce`.

## Data

Elexon Insights API (public, no key): `/balancing/settlement/system-prices/{date}` for prices and net imbalance volume; `/datasets/WINDFOR`, `/datasets/NDF`, `/datasets/IMBALNGC` queried by publish window for forecast vintages (IMBALNGC with `boundary=N`).

Contains BMRS data © Elexon Limited copyright and database right 2026, used under the BMRS Data Licence.

## Prior work, declared

The RMT spurious-factor paper (github.com/ekjots1ngh/rmt-spurious-factors) and the systematic-trading repository are earlier work by the author, cited for context only; no code from either is used here. Nothing from Cabestan Quant Research is used.

## Layout

```
PROTOCOL.md              fixed before any result, with dated amendments
gclose/ingest.py         Elexon client, monthly parquet under data/raw/
gclose/store.sql         schema and as-of join for the Tiger Data track (not used by the pipeline, not yet run)
gclose/features.py       gate-safe features: one merge_asof per forecast dataset, print-time checks for prices
gclose/models.py         the P(short) ladder: coin, persistence, calibrated persistence, NESO indicated, ours
gclose/backtest.py       monthly walk-forward of the ladder, Brier with intervals
gclose/price_models.py   the "would a fancier model help" check: ridge and boosted price, boosted P(short)
gclose/battery.py        1 MW / 2 MWh battery: vectorised dynamic programme, sequential path
gclose/decide.py         one optimiser, many forecasts: one-step and chain policies, ceilings, robustness, value of skill
gclose/stats.py          week-block bootstrap, vectorised
gclose/export.py         web/public/replay.json for the demo
tests/                   poison test with planted leaks; DP against a scalar loop; physics, cash and loss limit
```

Full pipeline from the committed raw data, about four minutes on a laptop (most of it the boosted models): `make reproduce`, or run the `python -m` lines in the Makefile in order.
