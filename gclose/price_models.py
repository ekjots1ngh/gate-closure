"""Would a fancier model have paid? The boosted and ridge checks, walk-forward like everything else.

Two questions, both answered with the same monthly refit as gclose.backtest:
  1. Does forecasting the price directly beat forecasting the side? A ridge regression (on
     standardised features plus a one-hot half-hour slot) and a gradient-boosted regressor.
  2. Does a gradient-boosted classifier beat our logistic P(short)?

The boosted models take missing values natively, so they see the raw features. Ridge fills
gaps with the training window's medians, as gclose.models does.

Run: python -m gclose.price_models   ->  data/out/price_forecasts.parquet (about 1.5 minutes)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from . import OUT, PERIODS_PER_DAY, slot_of
from .backtest import walk_forward
from .features import FEATURES, load_table

PRICE_FORECASTS = OUT / "price_forecasts.parquet"
BOOSTING = {"max_iter": 200, "learning_rate": 0.05, "random_state": 0}
RIDGE_ALPHA = 10.0


def _inputs(rows: pd.DataFrame) -> pd.DataFrame:
    """The gate-safe features plus the half-hour slot."""
    return rows[FEATURES].assign(slot=slot_of(rows["start_time"]))


def _ridge() -> object:
    """Median-filled features and a one-hot slot, standardised together, then ridge."""
    columns = ColumnTransformer(
        [
            ("features", SimpleImputer(strategy="median"), FEATURES),
            ("slot", OneHotEncoder(categories=[list(range(PERIODS_PER_DAY))], sparse_output=False), ["slot"]),
        ]
    )
    return make_pipeline(columns, StandardScaler(), Ridge(alpha=RIDGE_ALPHA))


def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    """Price forecasts from ridge and boosting, and a boosted P(short), for one month."""
    train = train.dropna(subset=["ssp"])
    x_train, x_test = _inputs(train), _inputs(test)
    price_ridge = _ridge().fit(x_train, train["ssp"])
    price_boosted = HistGradientBoostingRegressor(**BOOSTING).fit(x_train, train["ssp"])
    side_boosted = HistGradientBoostingClassifier(**BOOSTING).fit(x_train, train["short"])
    return {
        "price_ridge": price_ridge.predict(x_test),
        "price_boosted": price_boosted.predict(x_test),
        "p_boosted": side_boosted.predict_proba(x_test)[:, 1],
    }


def main() -> None:
    forecasts = walk_forward(load_table(), fit_predict)
    forecasts.to_parquet(PRICE_FORECASTS, index=False)
    for name in ("price_ridge", "price_boosted"):
        error = forecasts[name] - forecasts["ssp"]
        print(f"{name:14s} MAE {error.abs().mean():6.1f}  correlation {forecasts[name].corr(forecasts['ssp']):.3f}")
    print(f"p_boosted      Brier {((forecasts['p_boosted'] - forecasts['short']) ** 2).mean():.4f}")


if __name__ == "__main__":
    main()
