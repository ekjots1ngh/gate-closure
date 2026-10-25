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
3. Saturday 24 October 2026, about 16:00 BST, during a clean-up for speed and readability. No model, feature or parameter changed. Two leaks were found and fixed. (a) `Ours` filled missing test inputs with the test month's own medians; it now uses the training window's. No test row needed filling, so the predictions are unchanged (largest difference 1e-16). (b) The decision layer's trailing 90-day tables included the half hour starting 90 minutes before each month, whose price prints 15 minutes after that month's first gate. It is now excluded. This changes daily P&L on 3 to 18 of 1,461 days and no policy's average by more than GBP 0.2 a day. The distribution-aware DP (two-state chain) listed under Battery was run here for the first time, after the point-forecast DP results were known. Its form was written before its first run: P(short) decays to the slot's base rate at the lag-1 autocorrelation of the side, over the next 8 half hours. Both DPs are reported.
4. Saturday 24 October 2026, about 17:00 BST, after an independent code review and before the holdout was opened or the model frozen.
   (a) Price vintages. From February 2024 the system-prices endpoint serves each price as revised the next day; `created_at` is the revision time (median 24 hours 45 minutes after the period starts) and the first print is not kept. Before then `created_at` is the first print (median 52 minutes after the start; 474 rows later than an hour). Features now use a price only if it was first printed before the gate, taking `created_at` where it is the first print and the 52-minute median otherwise; where t-4 printed late, its lag features are missing. Values from February 2024 remain the revised ones, which were not public at the gate. This is a known limitation, and results are reported split by era. Training labels and the optimiser's tables use only rows whose stored value was created before the month's first gate, which generalises amendment 3(b).
   (b) The poison test takes publish times from the data rather than from the code, puts a cutoff one minute before every publication in a two-day window, checks every column `build()` returns, and must catch five planted leaks (late prints ignored; a price lag of 3; gates at 45, 30 and 0 minutes). The real-data check now also compares the battery's decisions, as the Receipts section requires.
   (c) The daily loss limit acts on the battery's cash up to t-4, the cash it could know at the gate, not on periods not yet settled.
   (d) Spike exclusion as written above: the top 1% of half hours by absolute price. The harsher top 1% of days is reported alongside.
   (e) A perfect-hindsight ceiling (every price known in advance) is added. The side oracle is not an upper bound.
   (f) The chain policy clips carried-forward probabilities to [0, 1]; this affected only the oracle.
   (g) Declared as not done or done differently: price quantiles (pinball loss, coverage) were replaced by point price forecasts (ridge and boosted) for lack of time. The tilt and timing split is reported as each forecast's gain over the tilt in GBP a day with a paired interval. The NESO baseline uses the indicated value recalibrated, not its sign; the sign version scores Brier 0.2480 against 0.2468, so the value is the stronger baseline. Log loss is now reported.
   Effect: ours Brier 0.2293 against 0.2409 for calibrated persistence (paired difference -0.0117 [-0.0127, -0.0106]); chain ours GBP 48.3 a day against 42.9 for the tilt.
5. Saturday 24 October 2026, about 18:00 BST, a refactor for readability after a second, code-quality review. Names only, no change to any number: every output was compared with a snapshot taken before the refactor and differs by exactly zero. The fixed daily cycle ("tilt") is now called the schedule; the raw and calibrated persistence baselines are `persistence_raw` and `persistence_cal` everywhere; NESO's baseline is `indicated` everywhere; the side oracle is `side_oracle`.
6. Saturday 24 October 2026, about 18:30 BST, analyses added after the results, for the write-up: Murphy's decomposition of the Brier score, the Diebold-Mariano test, Sharpe and information ratios with drawdown, and a check of the chain policy's Markov assumption. None changes a model, a policy or an existing number. The Markov check found that the side's memory decays more slowly than geometric; fading the forecast with the measured memory would have earned about GBP 1 a day more for ours. Because that was found after seeing results, it is reported and not adopted.
7. Saturday 24 October 2026, about 19:00 BST, before the freeze: how the live record works, where it differs in detail from the Receipts section. Each run decides the earliest period whose gate is still ahead, which is t+3 counted from the current half hour (the protocol's "t+2" would already be past its gate), about 28 minutes before that gate. The timestamp is GitHub's push time rather than a database insert time. The frozen model is fitted on everything public at the freeze, holdout months included; the holdout itself is scored only by gclose.holdout, with the walk-forward's monthly refits, so the frozen model is never scored on data it was fitted on.
8. Saturday 24 October 2026, about 18:05 BST, after the freeze (model 5b5614ce6646, unchanged): a bug in the live record, found by its own rehearsal, fixed openly. When the newest period had not printed yet, the live code gave it a placeholder row whose missing volume read as "long" (short = 0) and whose print time was assumed, so the model could see an invented input. Fixed: an unprinted period's features are missing, as in the backtest (the stored history has no such rows, so no backtest number changes; checked to the penny). Runs also move from 28 minutes to 6 minutes before each gate, so the newest price has normally printed, as the backtest assumed; deciding earlier would have left it missing in most runs. The ledger is never edited. Its first line (target 18:00 UTC) was decided after that period's inputs had all printed and is unaffected; any line decided between 18:00 and the restart is listed in the README. The live record is scored from the restart with the fixed code.
9. Sunday 25 October 2026, about 05:45 GMT. (a) The holdout was opened at 20:19 UTC on Saturday, not Sunday morning as written above: after the freeze (16:52 UTC), once, with the frozen recipe, and before any of its numbers were seen. The timing is the only departure. Its result is reported in full: the forecast passes the failure condition (ours minus calibrated persistence, Brier -0.0097 [-0.0144, -0.0059]); the battery does not beat the schedule (chain ours GBP 71.9 a day against 86.0, gain -14.1 [-25.7, -4.1]). (b) The laptop wrote docs/HOLDOUT.md in the Windows code page, so its pound signs were unreadable; it was re-encoded as UTF-8, not otherwise edited, and every file the pipeline writes is now written as UTF-8. (c) The live record counts only lines committed before their gate: overnight the laptop slept in the middle of the 23:00 UTC decision and committed it at 05:19 the next morning. Two processes' pushes collided once, so the 20:30 UTC line, committed at 19:24, reached GitHub at 19:41, after its gate; the README lists GitHub's push time for every line.
10. Sunday 25 October 2026, about 05:45 GMT, an analysis added after all results: what is an hour worth? gclose.latency reruns the four-year walk-forward and the battery with the decision 30, 60, 90 and 120 minutes before each half hour, moving the newest visible price with the gate, and passes the real-week poison check at every lead; the 60-minute run reproduces the headline to every digit. It changes no model, policy or reported number, and was never run on the holdout.
