"""Forecasts of P(short): the baseline ladder fixed in PROTOCOL.md, plus ours.

Every model has fit(train) and predict_proba(test) -> P(short) per row. All are linear or
simpler on purpose: HRT's own guidance is to ship the linear model when it ties a fancier
one, and gclose.price_models checks whether a boosted model would have been worth it.

Missing inputs are filled with the training window's medians, never the test window's,
so a model's predictions for a month depend only on data from before that month.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES


class Coin:
    """The long-run share of short periods. The floor every forecast must clear."""

    def fit(self, train: pd.DataFrame):
        self.p = train["short"].mean()
        return self

    def predict_proba(self, test: pd.DataFrame) -> np.ndarray:
        return np.full(len(test), self.p)


class Persistence:
    """The protocol's raw persistence: short if t-4 was short, as a 0/1 'probability'.

    Kept because the protocol named it; it is overconfident by construction, which is why
    PersistenceCalibrated exists (PROTOCOL.md amendment 2).
    """

    def fit(self, train: pd.DataFrame):
        return self

    def predict_proba(self, test: pd.DataFrame) -> np.ndarray:
        return test["short_lag4"].fillna(0.5).clip(0.02, 0.98).to_numpy()


class _OneFeatureLogit:
    """Logistic regression on a single column: a baseline recalibrated into a probability."""

    column: str

    def fit(self, train: pd.DataFrame):
        d = train.dropna(subset=[self.column])
        self.fill = d[self.column].median()
        self.m = LogisticRegression().fit(d[[self.column]], d["short"])
        return self

    def predict_proba(self, test: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(test[[self.column]].fillna(self.fill))[:, 1]


class PersistenceCalibrated(_OneFeatureLogit):
    """P(short_t | short_{t-4}): persistence as an honest probability."""
    column = "short_lag4"


class IndicatedImbalance(_OneFeatureLogit):
    """NESO's own indicated imbalance for period t (latest vintage before the gate), recalibrated."""
    column = "imbal_latest"


class Ours:
    """Logistic regression on every gate-safe feature."""

    def fit(self, train: pd.DataFrame):
        d = train.dropna(subset=FEATURES)
        self.fill = d[FEATURES].median()
        self.m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(d[FEATURES], d["short"])
        return self

    def predict_proba(self, test: pd.DataFrame) -> np.ndarray:
        return self.m.predict_proba(test[FEATURES].fillna(self.fill))[:, 1]


LADDER = {
    "coin": Coin,
    "persistence": Persistence,
    "persistence_cal": PersistenceCalibrated,
    "indicated": IndicatedImbalance,
    "ours": Ours,
}
