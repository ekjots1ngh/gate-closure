# Gate Closure

**Forecasting the GB grid's imbalance one hour ahead, and pricing what that forecast is worth.**

Every half hour the GB electricity system is either short of power or long. Whoever is on the wrong side pays the imbalance price, which nobody knows until about twenty minutes after the half hour ends. One hour before each half hour, at gate closure, we forecast which side the grid will be on, using only data that was public at that moment. A simulated 1 MW / 2 MWh battery trades on the forecast.

Built in 24 hours at OxHack '26 (Oxford, 24 to 25 October 2026) for HRT's challenge: *best use of data for predictions and decision making*. The theme of the hack was time; this project is about the one hour between deciding and knowing.

## The answer

Walk-forward over four years (July 2022 to June 2026, refitted monthly, 70,120 half hours), with 90% intervals from resampling whole weeks:

- **The forecast is clearly better than the baselines.** Our probability of a short system scores Brier 0.2293. Calibrated persistence scores 0.2409 and NESO's own published imbalance forecast 0.2468. Paired over the same weeks, ours is better by 0.0117 [0.0106, 0.0127].
- **It is worth a little money, and we can say exactly how much.** The battery earns £42.9 a day on a fixed daily schedule and £48.3 with our forecast: a gain of £5.4 a day [1.0, 9.7]. Persistence and NESO's forecast both lose money against the schedule.
- **There is an exchange rate between accuracy and money.** Scale the forecast's errors up or down and the money moves almost linearly: £8 to £10 a day per 0.01 of Brier. The line crosses the no-forecast schedule at about Brier 0.235. Trading on a coin-flip-quality forecast loses £13 to £19 a day against simply not forecasting. So the first slice of skill only pays for the right to act on a forecast at all. That is why a clearly better forecast earns only £5 more. In the language of forecast verification, ours is almost perfectly calibrated but has low resolution: it rarely strays far from 50/50.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/value_of_skill_dark.svg">
  <img alt="Money per day against Brier score: a nearly straight line from coin-flip accuracy to perfect knowledge of the side, with ours, calibrated persistence and NESO's forecast sitting on it" src="docs/value_of_skill_light.svg">
</picture>

For scale, knowing the side of every half hour an hour early would earn £223 a day, and knowing every price in advance £345. A boosted-tree classifier beats our logistic model on Brier but not on money (£48.2 to £50.0 depending on the machine, against £48.3), so the simple model ships. Forecasting the price directly earns less than the fixed schedule.

Every table, interval and robustness check is in [docs/RESULTS.md](docs/RESULTS.md), generated from the pipeline's output.

## The maths, and what each piece does

| Concept | Where you meet it | What it does here | What it showed |
|:---|:---|:---|:---|
| Logistic regression, fitted by maximum likelihood | 2nd-year statistics | Turns 16 gate-safe features into P(short) | Brier 0.2293, against 0.2409 for persistence |
| Proper scoring rules: Brier score, log loss | 3rd-year statistics | Scores probabilities so that honest forecasting is the best strategy | A coin is 1 bit; ours is 0.9375, so it extracts 0.06 bits per half hour |
| Murphy's decomposition, reliability diagram | Forecast verification | Separates calibration from resolution | Calibration near perfect (0.0003); resolution 2.2 times persistence's, but only 8% of the uncertainty |
| Block bootstrap; Diebold-Mariano with Newey-West variance | Time series, econometrics | Honest uncertainty when errors are autocorrelated | Ours beats persistence by 0.0117 [0.0106, 0.0127]; Diebold-Mariano statistic -17 |
| Law of total expectation, certainty equivalence | Probability, optimal control | E[price] = p × (price when short) + (1 - p) × (price when long). Cash is linear in price and the battery is too small to move it, so for the half hour being traded this one number is all the optimiser needs | Why a calibrated probability is enough: it maps straight to the expected price |
| Dynamic programming: Bellman equation, backward induction | Algorithms, optimisation | Values every state of charge and re-plans each half hour (model predictive control) | Vectorised over 70,120 half hours: the whole study runs in seconds |
| Two-state Markov chain | 2nd-year probability | Carries the forecast forward, fading at the side's own persistence | Tested, and too simple: the grid's memory decays more slowly than geometric. Fixing it is worth about £1 a day |
| Expected value of information | Decision theory | Prices accuracy in pounds, with two ceilings | £8 to £10 a day per 0.01 of Brier; knowing the side £223 a day, hindsight £345 |
| Sharpe ratio, information ratio, drawdown | Finance | Risk-adjusted view of the gain over the schedule | Information ratio 0.51 a year: real, but noisy |
| Point-in-time as-of joins (a sorted merge), walk-forward testing | Algorithms, quant practice | No input is ever used before it was public | Poison check on a real week: 0 of 170 decisions change |
| Mutation testing | Software engineering | Proves the leak test can actually fail | 5 leaks planted, 5 caught |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/reliability_dark.svg">
  <img alt="Reliability diagram: our forecasts lie on the diagonal, but most sit between 0.3 and 0.7" src="docs/reliability_light.svg" width="420">
</picture>

## One decision, in time

```
   T-150    T-120     T-90     T-60     T-30       T      T+30
     │  t-5   │  t-4   │  t-3   │  t-2   │  t-1   │   t    │
     └────────┴────────┴────────┼────────┴────────┴────────┘
                                ▲
                                gate closure: the decision for period t is made here

     t-4's price prints about 52 min after it starts (T-68)    used
     t-3's price prints about 52 min after it starts (T-38)    not yet public, never used
     wind, demand and NESO forecasts                           newest version published strictly before T-60
```

Everything in the project bends around this picture. A feature is either provably public at the gate or it does not exist.

## Architecture

```mermaid
flowchart LR
    subgraph elexon["Elexon Insights API, public"]
        prices["System prices and imbalance volume<br/>one row per half hour"]
        vintages["Forecast vintages: wind, demand,<br/>NESO indicated imbalance<br/>every version, keyed by publish time"]
    end
    prices --> ingest
    vintages --> ingest
    ingest["<b>ingest</b><br/>monthly parquet, resumable<br/>232 files committed"] --> features
    features["<b>features</b><br/>as-of joins strictly before the gate<br/>prices only once printed"] --> backtest
    backtest["<b>models + backtest</b><br/>P(short) ladder<br/>monthly walk-forward"] --> decide
    features --> price_models["<b>price_models</b><br/>would a fancier<br/>model have paid?"]
    price_models --> decide
    decide["<b>battery + decide</b><br/>one DP optimiser,<br/>many forecasts"] --> results[("results.json")]
    results --> report["<b>report</b><br/>docs and figures"]
    results --> export["<b>export</b><br/>demo replay"]
    poison{{"poison test<br/>five planted leaks"}} -.checks.-> features
    dp{{"DP tests<br/>vs scalar loop"}} -.checks.-> decide
```

### Design decisions

1. **One clock.** Every timing rule (the gate, the price lag, when prices print) is a named constant in [`gclose/__init__.py`](gclose/__init__.py), shared by the features, the training windows, the optimiser and the tests. There is no second definition to drift.
2. **Point-in-time by construction.** Forecast vintages join with a single `merge_asof` per dataset, matched to their own target period and strictly before the gate. Prices are used only once they have printed. Each monthly refit learns only from outcomes that were public at that month's first gate.
3. **One optimiser, many forecasts.** The battery's dynamic programme is fixed, and forecasts are swapped in. So a difference in money is the forecast's doing, not the optimiser's. Fed only the base rate, the forecast-driven policy takes exactly the schedule's actions on all 70,120 half hours, and a test pins that identity.
4. **Vectorise what does not depend on the path.** The value of each state of charge depends only on prices, so the Bellman step runs across every half hour at once in numpy. Only the battery's path, with its daily loss limit, is a loop. The feature build went from 123 s to 12 s and the whole decision study runs in 5 s, each checked to reproduce the slower version's output exactly.
5. **Uncertainty on every headline.** Intervals resample whole weeks, because a windy week is windy all week. Comparisons are resampled in pairs, so an interval describes the difference, not two independent noises.
6. **Tests that try to break it.** The poison test replaces everything published after a cutoff with noise, with a cutoff one minute before every publication, and checks that nothing decided earlier changes. To prove it can fail, it also plants five leaks (late prints ignored, a one-period price lag, gates at 45, 30 and 0 minutes) and requires each one to be caught.

## Honesty

- **Pre-registered.** [`PROTOCOL.md`](PROTOCOL.md) fixed the question, baselines, battery, metrics and failure condition before any result existed. Every later change is a dated amendment saying what changed, why, and its effect, including the ones found by an independent code review.
- **Held out.** July to 23 October 2026 is sealed. `python -m gclose.holdout` opens it once, after the freeze, with the walk-forward's own recipe, and refuses to run a second time.
- **Live.** From the freeze, `python -m gclose.live run` decides every half hour and pushes each decision to [`ledger/decisions.jsonl`](ledger/) six minutes before that half hour's gate, once the newest price has normally printed. The frozen model is [plain JSON](ledger/model.json) with a SHA-256 of its contents, and every line carries that hash, so anyone can recompute any decision. GitHub's timestamps are the receipt. One line came from old code: the half hour from 18:30 UTC on 24 October was decided at 17:02 UTC by the first process, still running beside the fixed one ([amendment 8](PROTOCOL.md#amendments)), and it read the unprinted 17:00 period as long. The ledger is append-only, so the line stays; `python -m gclose.live score` leaves it out and says so.
- **Known limitation.** From February 2024 Elexon serves each price as revised the next day, and the first print is not kept. In that era our price-based inputs use revised values that were not public at the gate (the timing rule itself is still enforced). We report both eras: before the switch, with clean first prints, ours beats the schedule by £9.4 a day and persistence by 0.0127 Brier; after it, by £2.7 and 0.0110.
- **Reproducible.** The raw data is committed, so every number rebuilds offline. Two machines agree to the decimal on everything except the boosted model, which moves by up to £2 a day with floating-point differences in tree building.

## Demo

[`web/dist/index.html`](web/dist/index.html) is the whole demo in one file, data and fonts included: download it and open it in a browser, no install and no network needed. It replays one week of 2026 (the week with the widest range of prices, chosen without looking at the money) as the control room would have seen it. Prices print about 52 minutes after each half hour starts, the forecast's lamps light at each gate, the battery trades, and the wind map shows the forecast revisions the model saw. **Poison the future** (key P) replaces everything published after a cutoff with noise and shows that no decision before it moves. Below the replay, a slider scales the forecast's errors to show what skill is worth, and the live record is read straight from this repository.

To rebuild it: `python -m gclose.export`, then `cd web && npm install && npm run build`.

## Reproduce

Python 3.11 or later, any OS. About three minutes from a clean clone, with no network: the raw data is in the repo.

```
pip install -e ".[dev]"            # or: pip install -r requirements.txt
make reproduce                     # or run the lines below in order

python -m pytest -q                # 28 tests, about 15 s
python -m gclose.features          # gate-safe feature table from data/raw (12 s)
python -m gclose.backtest          # walk-forward forecasts, Brier and log loss
python -m gclose.price_models      # the boosted and ridge checks (1.5 min)
python -m gclose.decide            # the battery under every forecast, with intervals
python -m gclose.report            # docs/RESULTS.md and the figures
python -m gclose.export            # demo data, and the poison check on a real week
```

`make lint` runs ruff's linter and formatter check. To refresh the data from Elexon (public API, no key):
`python -m gclose.ingest check`, then `python -m gclose.ingest pull 2022-01-01 2026-10-23`.

## Repository

```
PROTOCOL.md              the pre-registration and its dated amendments
gclose/__init__.py       everything the protocol fixes: paths, timing rules, test windows
gclose/ingest.py         Elexon client and raw store: monthly parquet under data/raw/, resumable
gclose/features.py       gate-safe features: as-of joins for forecasts, print times for prices
gclose/models.py         the P(short) ladder: coin, persistence, NESO's forecast, ours
gclose/backtest.py       the walk-forward driver, and forecast scores
gclose/price_models.py   would a fancier model have paid? ridge and boosted, same driver
gclose/battery.py        the battery: vectorised dynamic programme, sequential path
gclose/decide.py         one optimiser, many forecasts: money, ceilings, robustness, value of skill
gclose/stats.py          bootstrap, scoring rules, Murphy's decomposition, Diebold-Mariano, risk
gclose/receipts.py       the poison check end to end on a real week
gclose/report.py         docs/RESULTS.md and the figures, rendered from results.json
gclose/figures.py        README figures in light and dark
gclose/live.py           the frozen model and the live record: check, freeze, run, score, replay
gclose/holdout.py        opens the holdout, once
gclose/export.py         replay data for the demo
gclose/store.sql         a TimescaleDB sketch for the Tiger Data track (not used by the pipeline)
tests/                   the poison test with planted leaks; the optimiser against a scalar loop
data/raw/                Elexon data, January 2022 to October 2026
ledger/                  the frozen model and every live decision, as pushed
web/                     the demo: a replay at gate closure; dist/index.html is the built page
```

## Data

Elexon Insights API: `/balancing/settlement/system-prices/{date}` for prices and net imbalance volume, and `/datasets/WINDFOR`, `/datasets/NDF` and `/datasets/IMBALNGC` queried by publish window for forecast vintages. Contains BMRS data © Elexon Limited copyright and database right 2026, used under the BMRS Data Licence.

Prior work by the author (an RMT spurious-factor paper, a systematic-trading repository) is cited for context only; no code from it is used. Nothing from Cabestan Quant Research is used.
