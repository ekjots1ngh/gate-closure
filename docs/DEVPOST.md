# Devpost write-up

Pasted into the submission form on Sunday.

## Inspiration

Every half hour the GB electricity system is either short of power or long, and whoever is on the wrong side pays the imbalance price. Nobody knows that price until about twenty minutes after the half hour ends, but the decision has to be made an hour before it starts, at gate closure. The hack's theme was time, and this is a project about one hour of it: the hour between deciding and knowing. HRT's challenge asked for the best use of data for predictions and decision making, so we built both halves and, more importantly, measured how much the prediction is worth to the decision.

## What it does

One hour before each half hour, Gate Closure forecasts whether the grid will be short or long, using only data that was public at that moment: the four-period-old price, and the newest wind, demand and NESO imbalance forecasts published strictly before the gate. A simulated 1 MW / 2 MWh battery then trades on the forecast through a dynamic programme. Everything is scored against a ladder of baselines (a coin, persistence, NESO's own forecast) and against two ceilings (knowing the side an hour early, knowing every price in advance), with intervals that resample whole weeks.

The demo is live at https://ekjots1ngh.github.io/gate-closure/. The top panel is the frozen model making a real call every half hour, committed to GitHub before its gate, with the three inputs that moved it most (exact, since the model is a logistic regression) and the recent calls against what then printed. Below it, a week from June is replayed as the control room saw it, and pressing P poisons the future to show no earlier call moves.

Over four years of walk-forward testing (July 2022 to June 2026, refitted monthly, 70,120 half hours) the forecast scores Brier 0.2294 against 0.2412 for calibrated persistence and 0.2468 for NESO's forecast. The battery earns £48.4 a day with it against £42.9 on a fixed schedule, a gain of £5.5 a day [1.2, 9.8]. The number we are proudest of is the exchange rate: each 0.01 of Brier is worth £8 to £10 a day to this battery, and a coin-flip-quality forecast loses £13 to £19 a day against not forecasting at all. The first slice of skill only pays for the right to act.

The theme was time, so we also asked what an hour is worth. Rerunning the whole four-year test with the decision made 30 minutes before each half hour instead of 60, the forecast sharpens to Brier 0.220 and the battery earns £58.2 a day instead of £48.4: deciding half an hour later is worth £9.8 a day [7.1, 12.8]. NESO's 2026 consultation on balancing reform recorded calls to move gate closure to 30 minutes, so this is a measured input to a live policy question.

## How we built it

Python, pandas, numpy and scikit-learn, with React and d3 for the demo. Elexon's public Insights API supplies prices, imbalance volumes and every forecast vintage; the raw data is committed as 232 monthly parquet files so every number rebuilds offline in about three minutes. Features are built with one point-in-time as-of join per dataset, strictly before the gate, and prices are used only once they have printed. The forecast is a logistic regression on 16 inputs, refitted monthly on outcomes that were public at that month's first gate. The battery is a Bellman dynamic programme over state of charge, vectorised across all 70,120 half hours, with the same optimiser used for every forecast and for the ceilings, so a difference in money is the forecast's doing.

The maths is second- and third-year material used where it earns its place: proper scoring rules, Murphy's decomposition, a week-block bootstrap with paired intervals, the Diebold-Mariano test with Newey-West variance, the law of total expectation and certainty equivalence, backward induction, a two-state Markov chain to carry the forecast forward, the expected value of information, and Sharpe and information ratios. Each one has a number next to it in the README.

## Challenges we ran into

Elexon changed what it serves in February 2024: prices now come as revised the next day, and the first print is not kept. We found this through an independent code review mid-hack, documented it as a known limitation, and report every result split by era. The same review found that the daily loss limit was acting on cash the battery could not yet know, and that the first version of the poison test could not fail. We fixed each in the open, as dated amendments to the pre-registration.

The live record found its own bug in rehearsal: when the newest half hour had not printed, a placeholder row read as "long". We fixed it, added a test, moved the live decisions to six minutes before each gate so the newest price has normally printed, and left the affected ledger lines in place, listed and unscored. The ledger is never edited.

## Accomplishments that we're proud of

A pre-registration written before the first result, with eleven dated amendments. A poison test that replaces everything published after a cutoff with noise, with a cutoff one minute before every publication, and five planted leaks it must catch. A sealed holdout (July to October 2026), opened once after the freeze and reported in full: the forecast held (Brier 0.232 against 0.242 for persistence and 0.247 for NESO, passing the pre-registered test), but the money did not. Record price spreads made the fixed schedule earn £86 a day, and against a schedule that strong our own value-of-skill curve says a forecast needs Brier about 0.21 to pay. And a frozen model, plain JSON with a SHA-256, making a call every half hour from a laptop and pushing it to GitHub before the gate. Running it overnight found three real operational failures (a stale second process, a push collision, a laptop asleep mid-decision); each is listed line by line in the README and handled in code.

## What we learned

Calibration is not the same as being useful. Our forecast is almost perfectly calibrated (reliability 0.0003) but rarely strays far from 50/50, and resolution is what the battery pays for. Also: the limit was the information, not the estimator. Boosted trees beat the logistic model on Brier and not on money, and the side oracle, £223 a day, shows the size of the gap nobody at the gate can see.

## What's next

Archive first prints ourselves, because the revised-price era costs £7.3 a day of measurable edge. Adopt the measured memory in the chain policy, pre-registered this time, for about £1 a day. Look for inputs that move P(short) away from 50/50, such as interconnector and plant outage notices. And keep the ledger running: the live record is the experiment that never ends.

## Built with

Python, pandas, numpy, scikit-learn, pytest, ruff, React, TypeScript, d3, Vite, Elexon Insights API.
