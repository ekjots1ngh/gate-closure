# Every target is a thin alias for a `python -m` command; see the README.
START = 2022-01-01
END = 2026-10-23

.PHONY: test lint check data features backtest price_models decide report export reproduce

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
