# Every target is a thin alias for a `python -m` command; see the README.
START = 2022-01-01
END = 2026-10-23

.PHONY: test lint check data features backtest price_models decide report export reproduce live-check freeze live score holdout

test:
	python -m pytest -q

lint:
	ruff check gclose tests && ruff format --check gclose tests

check:
	python -m gclose.ingest check

data:
	python -m gclose.ingest pull $(START) $(END)

features:
	python -m gclose.features

backtest: features
	python -m gclose.backtest

price_models: features
	python -m gclose.price_models

decide: backtest price_models
	python -m gclose.decide

report: decide
	python -m gclose.report

export: decide
	python -m gclose.export

reproduce: test report export

# The live record and the holdout (need Elexon; see README)
live-check:
	python -m gclose.live check

freeze:
	python -m gclose.live freeze

live:
	python -m gclose.live run

score:
	python -m gclose.live score

holdout:
	python -m gclose.holdout
