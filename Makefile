START=2025-07-01
END=2026-10-23

.PHONY: test check data backtest reproduce

test:
	python -m pytest -q tests

check:
	python -m gclose.ingest check

data:
	python -m gclose.ingest pull $(START) $(END)

backtest:
	python -m gclose.backtest

reproduce: test backtest
