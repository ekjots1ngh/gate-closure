"""P(short) models and price quantiles. Keep them linear; PROTOCOL.md fixes the ladder.

Every model exposes fit(df) and predict_proba(df) -> np.ndarray of P(short).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, QuantileRegressor, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURES


class Coin:
    """Long-run short frequency. The floor."""
    def fit(self, df):
        self.p = df["short"].mean()
        return self

    def predict_proba(self, df):
        return np.full(len(df), self.p)


class Persistence:
    """Short if period t-4 was short, with a small shrink so Brier is finite."""
    def fit(self, df):
        return self

    def predict_proba(self, df):
        return df["short_lag4"].fillna(0.5).clip(0.02, 0.98).to_numpy()


class IndicatedImbalance:
    """NESO's own view, recalibrated by a one-feature logistic regression."""
    def fit(self, df):
        d = df.dropna(subset=["imbal_latest"])
        self.m = LogisticRegression().fit(d[["imbal_latest"]], d["short"])
        return self

    def predict_proba(self, df):
        x = df[["imbal_latest"]].fillna(0)
        return self.m.predict_proba(x)[:, 1]


class Ours:
    """Logistic regression on the full gate-safe feature list."""
    def fit(self, df):
        d = df.dropna(subset=FEATURES)
        self.m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=500))
        self.m.fit(d[FEATURES], d["short"])
        return self

    def predict_proba(self, df):
        x = df[FEATURES].fillna(df[FEATURES].median())
        return self.m.predict_proba(x)[:, 1]


LADDER = {"coin": Coin, "persistence": Persistence, "indicated": IndicatedImbalance, "ours": Ours}


class PriceQuantiles:
    """P10/P50/P90 of the system price given the same features plus the short probability.

    Fitted separately for short and long outcomes so the distribution-aware battery can
    use a price distribution per state.
    """
    def __init__(self, qs=(0.1, 0.5, 0.9)):
        self.qs = qs

    def fit(self, df):
        self.models = {}
        d = df.dropna(subset=FEATURES)
        for state in (0, 1):
            ds = d[d["short"] == state]
            for q in self.qs:
                m = make_pipeline(StandardScaler(), QuantileRegressor(quantile=q, alpha=0.001, solver="highs"))
                self.models[(state, q)] = m.fit(ds[FEATURES], ds["ssp"])
        return self

    def predict(self, df) -> dict[tuple[int, float], np.ndarray]:
        x = df[FEATURES].fillna(df[FEATURES].median())
        return {k: m.predict(x) for k, m in self.models.items()}


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))
