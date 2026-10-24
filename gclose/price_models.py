"""The "would a fancier model have helped" check, walk-forward like everything else.

Two questions, each answered with the same monthly refit as gclose.backtest:
  1. Does forecasting the price directly beat forecasting the side? Ridge (linear, on
     standardised features plus a one-hot half-hour slot) and a gradient-boosted regressor.
  2. Does a gradient-boosted classifier beat our logistic P(short)? `p_hgb`.

The boosted models take NaN natively, so they see the raw features. Ridge fills gaps with
the training window's medians, as gclose.models does.

Run: python -m gclose.price_models   ->  data/out/price_preds.parquet  (about 3 minutes)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .backtest import OUT, TRAIN_END, load_features, test_months
from .features import FEATURES

BOOST = dict(max_iter=200, learning_rate=0.05, random_state=0)


def _slot(df: pd.DataFrame) -> np.ndarray:
    return (df["start_time"].dt.hour * 2 + df["start_time"].dt.minute // 30).to_numpy()


def _with_slot_dummies(X: pd.DataFrame, slot: np.ndarray) -> np.ndarray:
    """Features plus 48 one-hot slot columns, for the linear model."""
    return np.hstack([X.to_numpy(), np.eye(48)[slot]])


def walk_forward(f: pd.DataFrame) -> pd.DataFrame:
    f = f[f["start_time"] < TRAIN_END]
    blocks = []
    for month, train, test in test_months(f):
        tr = f[train].dropna(subset=["ssp"])
        te = f[test]
        fill = tr[FEATURES].median()

        ridge = make_pipeline(StandardScaler(), Ridge(alpha=10.0))
        ridge.fit(_with_slot_dummies(tr[FEATURES].fillna(fill), _slot(tr)), tr["ssp"])
        tree_X = lambda d: np.column_stack([d[FEATURES].to_numpy(), _slot(d)])   # slot as one integer
        hgb = HistGradientBoostingRegressor(**BOOST).fit(tree_X(tr), tr["ssp"])
        cls = HistGradientBoostingClassifier(**BOOST).fit(tree_X(tr), tr["short"])

        block = te[["start_time", "ssp", "short"]].copy()
        block["price_ridge"] = ridge.predict(_with_slot_dummies(te[FEATURES].fillna(fill), _slot(te)))
        block["price_hgb"] = hgb.predict(tree_X(te))
        block["p_hgb"] = cls.predict_proba(tree_X(te))[:, 1]
        blocks.append(block)
        print(month, end=" ", flush=True)
    print()
    return pd.concat(blocks, ignore_index=True)


def main() -> None:
    P = walk_forward(load_features())
    P.to_parquet(OUT / "price_preds.parquet", index=False)
    for c in ("price_ridge", "price_hgb"):
        print(f"{c:12s} MAE {np.mean(np.abs(P[c] - P['ssp'])):6.1f}  corr {np.corrcoef(P[c], P['ssp'])[0, 1]:.3f}")
    print(f"p_hgb        Brier {np.mean((P['p_hgb'] - P['short']) ** 2):.4f}")


if __name__ == "__main__":
    main()
