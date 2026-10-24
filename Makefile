START=2022-01-01
END=2026-10-23

.PHONY: test data backtest reproduce

test:
	python -m pytest -q tests

data:
	python -m gclose.ingest prices $(START) $(END)
	python -m gclose.ingest vintages WINDFOR $(START) $(END)
	python -m gclose.ingest vintages NDF $(START) $(END)
	python -m gclose.ingest vintages IMBALNGC $(START) $(END)

backtest:
	python -m gclose.backtest

reproduce: test backtest
