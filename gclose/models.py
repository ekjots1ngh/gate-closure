"""Forecasters of P(short): the baseline ladder fixed in PROTOCOL.md, and ours.

Every forecaster is linear or simpler on purpose. A linear model's mistakes are easy to read,
and gclose.price_models checks whether a boosted model would have been worth the opacity
(it is not: it scores better and earns the same).

Missing inputs are filled with the training window's medians, never the test window's, so a
month's forecasts depend only on data from before that month.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, Self

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES


class Forecaster(Protocol):
    def fit(self, train: pd.DataFrame) -> Self: ...

    def predict_proba(self, rows: pd.DataFrame) -> np.ndarray:
        """P(short) for each row."""
        ...


class Coin:
    """The long-run share of short periods: the floor every forecast must clear."""

    def fit(self, train: pd.DataFrame) -> Self:
        self.base_rate = train["short"].mean()
        return self

    def predict_proba(self, rows: pd.DataFrame) -> np.ndarray:
        return np.full(len(rows), self.base_rate)


class RawPersistence:
    """The protocol's persistence as written: short if the newest printed period was short.

    Reported because the protocol named it. Its 0/1 "probabilities" are overconfident by
    construction, which is why CalibratedPersistence exists (PROTOCOL.md amendment 2). They are
    clipped to [0.02, 0.98] only so that log loss stays finite.
    """

    def fit(self, train: pd.DataFrame) -> Self:
        return self

    def predict_proba(self, rows: pd.DataFrame) -> np.ndarray:
        return rows["short_newest"].fillna(0.5).clip(0.02, 0.98).to_numpy()


class _Logit:
    """Logistic regression on `columns`, fitted on rows where they are all present."""

    columns: ClassVar[list[str]]
    standardise: ClassVar[bool] = False

    def fit(self, train: pd.DataFrame) -> Self:
        complete = train.dropna(subset=self.columns)
        steps = [SimpleImputer(strategy="median")]  # medians of the training window
        steps += [StandardScaler()] if self.standardise else []
        self.model: Pipeline = make_pipeline(*steps, LogisticRegression(max_iter=500))
        self.model.fit(complete[self.columns], complete["short"])
        return self

    def predict_proba(self, rows: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(rows[self.columns])[:, 1]


class CalibratedPersistence(_Logit):
    """P(short_t | short at the newest printed period): persistence as an honest probability."""

    columns: ClassVar[list[str]] = ["short_newest"]


class IndicatedImbalance(_Logit):
    """NESO's own indicated imbalance for period t, latest version before the gate, recalibrated."""

    columns: ClassVar[list[str]] = ["indicated_latest"]


class AllFeatures(_Logit):
    """Ours: logistic regression on every gate-safe feature."""

    columns: ClassVar[list[str]] = FEATURES
    standardise: ClassVar[bool] = True


LADDER: dict[str, type[Forecaster]] = {
    "coin": Coin,
    "persistence_raw": RawPersistence,
    "persistence_cal": CalibratedPersistence,
    "indicated": IndicatedImbalance,
    "ours": AllFeatures,
}
