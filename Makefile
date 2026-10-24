START=2022-01-01
END=2026-10-23

.PHONY: test check data features backtest prices decide export reproduce

test:
	python -m pytest -q tests

check:
	python -m gclose.ingest check

data:
	python -m gclose.ingest pull $(START) $(END)

features:
	python scripts/build_features.py

backtest:
	python -m gclose.backtest

prices:
	python -m gclose.price_models

decide:
	python -m gclose.decide

export:
	python -m gclose.export

reproduce: test features backtest prices decide export
