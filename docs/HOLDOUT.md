# Holdout

Opened once, at 2026-10-24 20:19 UTC, by `python -m gclose.holdout`; do not edit by hand.
Holdout, 1 July to 23 October 2026, with the frozen recipe; 5,520 half hours. Intervals are 90%,
resampling whole calendar weeks (1,000 resamples); differences are resampled in pairs.

## Forecasts of P(short)

Lower is better for both scores. The last column is ours minus each model, so negative means ours is better.

| model | Brier [90% CI] | log loss | ours minus model, Brier |
| :--- | ---: | ---: | ---: |
| coin (long-run share short) | 0.2493 [0.2484, 0.2502] | 0.6918 | -0.0174 [-0.0237, -0.0115] |
| persistence, raw 0/1 | 0.3947 [0.3792, 0.4101] | 1.6185 | -0.1627 [-0.1738, -0.1517] |
| persistence, calibrated | 0.2417 [0.2383, 0.2449] | 0.6764 | -0.0097 [-0.0144, -0.0059] |
| NESO indicated imbalance | 0.2466 [0.2432, 0.2496] | 0.6864 | -0.0147 [-0.0197, -0.0100] |
| ours | 0.2319 [0.2249, 0.2384] | 0.6549 |  |

The same forecasts, taken apart. Log loss in bits: a coin flip is exactly 1 bit, so 1 minus the number is
the information a forecast extracts per half hour. Murphy's decomposition splits Brier into reliability
(calibration, lower is better) minus resolution (how well it sorts half hours, higher is better) plus the
base uncertainty (0.2492 for everyone). The Diebold-Mariano
statistic compares each model's squared errors with ours, with a Newey-West variance over one week of lags;
negative favours ours.

| model | log loss, bits | reliability | resolution | Diebold-Mariano vs ours |
| :--- | ---: | ---: | ---: | ---: |
| coin (long-run share short) | 0.9981 | 0.0002 | 0.0000 | -4.7 (p < 0.0001) |
| persistence, raw 0/1 | 2.3350 | 0.1532 | 0.0077 | -21.8 (p < 0.0001) |
| persistence, calibrated | 0.9758 | 0.0002 | 0.0077 | -3.8 (p = 0.0002) |
| NESO indicated imbalance | 0.9902 | 0.0010 | 0.0031 | -5.1 (p < 0.0001) |
| ours | 0.9448 | 0.0007 | 0.0171 |  |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="reliability_dark.svg">
  <img alt="Reliability diagram: on the diagonal, mostly between 0.3 and 0.7" src="reliability_light.svg">
</picture>

## Money: a 1 MW / 2 MWh battery, £ per day

One step: the forecast prices the next half hour only. Chain: it also shapes the next few half hours,
fading at the side's own persistence.

| forecast | one step [90% CI] | chain [90% CI] |
| :--- | ---: | ---: |
| no forecast, fixed schedule | 86.0 [64.4, 110.5] | 86.0 [64.4, 110.5] |
| ours, logistic | 69.9 [50.4, 91.7] | 71.9 [53.6, 92.4] |
| boosted classifier | 83.1 [62.6, 106.1] | 85.5 [65.2, 109.0] |
| calibrated persistence | 65.9 [41.3, 93.4] | 68.6 [43.9, 97.5] |
| NESO indicated imbalance | 49.8 [33.0, 67.3] | 57.6 [39.8, 75.4] |
| knowing the side an hour early | 156.0 [138.8, 174.8] | 155.7 [139.2, 173.1] |

Price forecasts (one step) and the two ceilings:

| policy | £ per day [90% CI] |
| :--- | ---: |
| price forecast, ridge | 60.6 [40.9, 77.4] |
| price forecast, boosted | 66.3 [49.8, 83.1] |
| last price seen | 49.4 [33.8, 65.9] |
| knowing the price an hour early | 140.2 [123.6, 159.4] |
| perfect hindsight, every price known | 325.2 [291.5, 358.8] |

## Gain over the fixed schedule, £ per day

"Share" is the share of the gap between the schedule and knowing the side an hour early. The protocol's
spike check leaves out the top 1% of half hours by absolute price; the harsher check leaves out the top 1% of days.

| forecast | gain [90% CI] | share of gap | without spike half hours | without top 1% of days |
| :--- | ---: | ---: | ---: | ---: |
| calibrated persistence (one step) | -20.08 [-32.86, -9.16] | -28.7 [-52.0, -12.8]% | -12.76 [-20.06, -4.72] | -19.42 [-32.59, -7.42] |
| NESO indicated imbalance (one step) | -36.18 [-51.45, -23.33] | -51.6 [-89.0, -30.8]% | -26.49 [-37.67, -15.61] | -35.28 [-50.86, -22.40] |
| ours, logistic (one step) | -16.08 [-26.94, -6.16] | -22.9 [-41.2, -9.1]% | -13.97 [-23.13, -5.63] | -15.01 [-25.41, -5.45] |
| boosted classifier (one step) | -2.84 [-12.15, +5.21] | -4.1 [-17.7, 7.8]% | -1.49 [-9.00, +5.49] | -2.57 [-12.11, +5.65] |
| calibrated persistence (chain) | -17.32 [-30.21, -5.56] | -24.9 [-47.4, -8.3]% | -8.57 [-16.90, +0.27] | -16.97 [-30.49, -4.64] |
| NESO indicated imbalance (chain) | -28.36 [-43.29, -15.39] | -40.7 [-74.8, -20.2]% | -20.70 [-30.93, -10.56] | -27.52 [-42.30, -14.84] |
| ours, logistic (chain) | -14.09 [-25.68, -4.12] | -20.2 [-41.2, -5.5]% | -12.13 [-20.25, -4.80] | -12.68 [-23.55, -3.69] |
| boosted classifier (chain) | -0.52 [-8.58, +6.39] | -0.7 [-12.4, 9.6]% | +1.13 [-6.01, +7.84] | -0.20 [-8.35, +6.90] |

## By era

Until February 2024 the stored prices are first prints; after it, Elexon's next-day revisions (PROTOCOL.md amendment 4).

| era | ours minus calibrated persistence, Brier | chain ours | schedule | gain |
| :--- | ---: | ---: | ---: | ---: |
| revised prices, 2024-02 to 2026-06 | -0.0097 [-0.0144, -0.0059] | 71.9 | 86.0 | -14.09 [-25.68, -4.12] |

## Risk

Annualised Sharpe ratio of daily P&L, and the largest fall from a running peak in cumulative £. The last
row is the forecast's gain over the schedule, so its Sharpe ratio is an information ratio.

| series | Sharpe ratio | max drawdown, £ |
| :--- | ---: | ---: |
| chain/schedule | 11.87 | 397 |
| chain/ours | 10.15 | 499 |
| chain/ours minus chain/schedule | -5.04 | 1,923 |

## Is the side a Markov chain?

The chain policy fades the forecast as a two-state Markov chain would: autocorrelation at lag h equal to
the lag-1 value to the power h. The side's measured autocorrelation decays much more slowly, so the grid
has longer memory than that. Fading with the measured memory instead earns
£73.63 a day against £71.88. The
simplification costs about a pound a day, so we report it and keep the protocol's policy rather than
change it after seeing the results.

| lag, half hours | measured autocorrelation | geometric (Markov) |
| :--- | ---: | ---: |
| 1 | 0.488 | 0.488 |
| 2 | 0.348 | 0.238 |
| 3 | 0.248 | 0.117 |
| 4 | 0.176 | 0.057 |
| 5 | 0.144 | 0.028 |
| 6 | 0.112 | 0.014 |
| 7 | 0.099 | 0.007 |

## By year, £ per day

| year | schedule | ours (chain) | persistence (chain) | NESO (chain) | knowing the side | hindsight |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026 | 86.0 | 71.9 | 68.6 | 57.6 | 155.7 | 325.2 |

## Value of skill

Our forecast errors scaled by k: k = 0 knows the side, k = 1 is our forecast, k above 1 is worse.

| k | Brier | one step, £/day | chain, £/day |
| :--- | ---: | ---: | ---: |
| 0.00 | 0.0000 | 156.0 | 155.7 |
| 0.25 | 0.0145 | 158.4 | 153.7 |
| 0.50 | 0.0580 | 152.7 | 150.1 |
| 0.75 | 0.1305 | 131.0 | 127.0 |
| 0.90 | 0.1879 | 99.6 | 98.4 |
| 1.00 | 0.2319 | 69.9 | 71.9 |
| 1.10 | 0.2806 | 48.5 | 50.4 |
| 1.25 | 0.3619 | 9.0 | 23.0 |
| 1.50 | 0.5083 | -71.6 | -32.4 |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="value_of_skill_dark.svg">
  <img alt="Money per day against Brier score" src="value_of_skill_light.svg">
</picture>
