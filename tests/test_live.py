"""The live record: the frozen JSON model must be the fitted model, and every decision must beat its gate."""

import json

import numpy as np
import pandas as pd
import pytest

from gclose import GATE_LEAD, live
from gclose.features import build
from gclose.models import AllFeatures

from .test_poison import _synthetic

NOW = pd.Timestamp("2026-03-05 12:02", tz="UTC")


@pytest.fixture(scope="module")
def table() -> pd.DataFrame:
    return build(*_synthetic())


def test_the_frozen_json_model_reproduces_the_fitted_model(table):
    frozen = live.freeze(table, NOW)
    fitted = AllFeatures().fit(table[table["created_at"] < NOW])
    rows = table.iloc[200:260]
    by_hand = np.array([frozen.p_short(row) for _, row in rows.iterrows()])
    np.testing.assert_allclose(by_hand, fitted.predict_proba(rows), atol=1e-12)


@pytest.mark.parametrize("minute", [0, 1, 2, 29, 30, 31, 32, 59])
def test_every_target_gate_is_strictly_after_the_decision(minute):
    now = pd.Timestamp("2026-10-25 03:00", tz="UTC") + pd.Timedelta(minutes=minute, seconds=30)
    gate = live.target_for(now) - GATE_LEAD
    assert now < gate <= now + pd.Timedelta(minutes=30)


def test_a_changed_model_file_is_refused(table, tmp_path, monkeypatch):
    monkeypatch.setattr(live, "LEDGER", tmp_path)
    monkeypatch.setattr(live, "MODEL", tmp_path / "model.json")
    live.freeze(table, NOW).save()
    stored = json.loads((tmp_path / "model.json").read_text())
    stored["intercept"] += 0.01
    (tmp_path / "model.json").write_text(json.dumps(stored))
    with pytest.raises(SystemExit):
        live.Frozen.load()


def test_a_period_that_has_not_printed_is_unknown_not_long():
    """Live, the newest periods have no price yet; their features must be missing, never invented."""
    prices, *vintages = _synthetic(days=3)
    target = prices["start_time"].iloc[-1]
    not_yet_printed = prices.iloc[:-5]  # t-4 to t have no price at decision time
    row = build(live._with_future_rows(not_yet_printed, target), *vintages).iloc[-1]
    assert row["start_time"] == target
    assert np.isnan(row["short_newest"]) and np.isnan(row["niv_newest"]) and np.isnan(row["price_newest"])
    assert row["short_prev1"] in (0.0, 1.0)  # t-5 did print, so it is known
