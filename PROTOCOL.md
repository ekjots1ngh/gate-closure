# PROTOCOL.md

Committed before any result. Changes to this file after results exist are listed at the bottom with a reason.

## Question

Every half hour, the GB electricity system is either short (NESO had to buy energy, net imbalance volume > 0) or long. The system price for that half hour is not known until it prints, about 15 minutes after the period ends. Can a forecast made one hour before the period, using only data published by then, improve the decisions of a small battery that trades that price?

## Decision time

For settlement period t starting at T (UTC), the decision is made at T minus 60 minutes (gate closure). A feature may use a row only if its `publish_time` (Elexon) or `created_at` (prices) is strictly before T minus 60 minutes. The newest price known at decision time is for period t-4.

## Data

Elexon Insights API, public, no key. Datasets: system prices (DISEBSP via `/balancing/settlement/system-prices/{date}`), WINDFOR, NDF, IMBALNGC. All keyed on `start_time` in UTC. `settlementPeriod` is never used for arithmetic (Sunday 25 Oct 2026 has 50 periods).

Training window: 2022-01-01 to 2026-06-30 (see Amendment 1). Holdout: 2026-07-01 to 2026-10-23, opened once, Sunday morning, after the model is frozen. Nothing is tuned on the holdout.

## Targets

1. `short_t`: 1 if net imbalance volume for period t > 0, else 0.
2. `price_t`: system sell price for period t (single price regime, so sell = buy almost always).

## Baselines, fixed now, every one reported beside ours

1. Coin: long-run frequency of short.
2. Persistence: `short_{t-4}`.
3. NESO indicated imbalance: sign of the latest IMBALNGC vintage for t, recalibrated by a one-feature logistic regression.
4. Ours: logistic regression on the feature list in `gclose/features.py`; ridge and quantile regression (P10, P50, P90) for price given state.
5. Oracle: realised outcome.

## Battery

1 MW, 2 MWh, 0.5 MWh per half hour, 85% round-trip efficiency, 5 GBP per MWh throughput wear, state of charge in [0, 2]. Daily loss limit 500 GBP: after that, hold until midnight UTC.

Policies: fixed daily cycle (tilt), persistence rule, point-forecast DP, distribution-aware DP (two-state chain), oracle DP.

## Metrics

- P(short): Brier score, log loss.
- Price quantiles: pinball loss, 80% interval coverage.
- Battery: GBP per day by policy; share of the oracle gap over the fixed cycle closed; by year; excluding the top 1% of periods by absolute price; tilt and timing split.
- Every headline carries a week-block bootstrap 90% interval (1,000 resamples).

## Evaluation

Walk-forward: retrain at the start of each calendar month on all data before it, test on that month, January 2023 to June 2026. Holdout as above.

## Receipts

- Poison test (`tests/test_poison.py`): overwrite every row with `publish_time` after each decision time with noise; decisions must be identical.
- Live ledger from the model freeze: every 30 minutes, forecast and action for period t+2 appended with server insert time and pushed to GitHub before the period starts.

## Pivot rule

At 18:00 on Saturday 24 October 2026, if prices and vintages are not in the store, or the as-of join does not run, or the fixed-cycle and persistence batteries do not print a P&L with an interval, the project pivots to Charge Desk (see the plan). No pivot after 18:00.

## What would make us say it does not work

If ours does not beat persistence on Brier score outside the 90% interval in walk-forward, the headline is that null, and the decision results are reported as a value-of-skill curve only.

## Prior work, declared

The RMT spurious-factor paper and the systematic-trading repository are earlier work by Ekjot Singh. They are cited for context only. No code from either is used here. No data or results from Cabestan Quant Research are used here.

## Amendments

1. Saturday 24 October 2026, about 15:15 BST, before any result existed. The venue connection measured around 30 kB/s, which rules out pulling 2022 to 2026 before the 18:00 gate. Data is now pulled newest month first into monthly files. The training window starts at the earliest month fully pulled by 17:30 on Saturday (target 2025-07-01); that start month is written here, beside this amendment, before the walk-forward is run, and older months pulled later are not added to the headline. Walk-forward test months begin six months after the training start. The holdout is unchanged. IMBALNGC is requested with `boundary=N` server side; this changes download size only, not content.
   Recorded 15:30 BST Saturday, before any model was fitted or any backtest run: the measured speed was about 1 MB/s from Elexon (the slow speed was pip only), and the full range 2022-01 to 2026-10 was pulled in 3.4 minutes. Training start is therefore 2022-01-01, as originally protocolled. Walk-forward tests 2022-07 to 2026-06.
2. Saturday 24 October 2026, about 15:45 BST, after the first walk-forward. The persistence baseline as written outputs hard 0/1 probabilities (clipped to 0.02/0.98), so its Brier score (0.3875) is a strawman. We keep reporting it and add `persistence_cal`, P(short_t | short_{t-4}) fitted by one-feature logistic regression on the training window, the same treatment the NESO baseline already gets. This change was made after seeing results, and it can only make our headline harder: it strengthens a baseline and changes nothing about our model.
