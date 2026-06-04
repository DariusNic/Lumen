"""Label generation for the XGBoost signal model.

Labeling rules (locked):
  - **Labeling must be forward-looking.** The label at row t is computed
    from `close[t+5] / close[t] - 1`.
  - **The last 5 rows of every ticker have no label** (the future is
    not yet observed) and must be dropped before training.

Class assignment (locked, signed off):
    BUY  if forward_return > +0.02     (rises more than 2% in 5 trading days)
    SELL if forward_return < -0.02     (falls more than 2% in 5 trading days)
    HOLD otherwise

Class balance on US large-caps over 2019-2024 comes out roughly 30/40/30,
which is fine for `class_weight="balanced"` in XGBoost.

Horizon-tuning history: a 20-day / ±4% variant was tested and produced
36.6% test accuracy against a 42.8% always-HOLD baseline — slightly worse
than the 5-day variant on every metric except a marginal Sharpe
improvement (−0.14 vs −0.16). Technical-indicator-only direction
prediction on individual US large-caps does not improve with longer
horizons at the ternary BUY/HOLD/SELL granularity.
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

# --- Locked thresholds (change only with sign-off) ------
HORIZON_DAYS: int = 5
BUY_THRESHOLD: float = 0.02   # > +2% over 5 days → BUY
SELL_THRESHOLD: float = -0.02 # < -2% over 5 days → SELL

LABEL_BUY = "BUY"
LABEL_HOLD = "HOLD"
LABEL_SELL = "SELL"

# Numeric encoding used by XGBoost. The order is fixed so `predict_proba`
# columns line up consistently between train and serve time.
LABEL_TO_INT: dict[str, int] = {LABEL_SELL: 0, LABEL_HOLD: 1, LABEL_BUY: 2}
INT_TO_LABEL: dict[int, str] = {v: k for k, v in LABEL_TO_INT.items()}


def forward_returns(close: pd.Series, horizon: int = HORIZON_DAYS) -> pd.Series:
    """`close[t+horizon] / close[t] - 1` aligned to row t.

    The last `horizon` values are NaN (no future data yet).
    """
    if not close.index.is_monotonic_increasing:
        raise ValueError("forward_returns expects an ascending-sorted index")
    # `shift(-horizon)` brings close[t+horizon] to row t.
    future = close.shift(-horizon)
    return future / close - 1.0


def label_from_return(ret: float) -> Optional[str]:
    """Apply the BUY / HOLD / SELL thresholds. NaN returns map to None
    (the caller drops them)."""
    if ret is None or ret != ret:  # NaN check; ret != ret is True only for NaN
        return None
    if ret > BUY_THRESHOLD:
        return LABEL_BUY
    if ret < SELL_THRESHOLD:
        return LABEL_SELL
    return LABEL_HOLD


def label_series(close: pd.Series, horizon: int = HORIZON_DAYS) -> pd.Series:
    """Vectorized BUY/HOLD/SELL labels aligned to row t (last `horizon` are NaN)."""
    ret = forward_returns(close, horizon=horizon)
    labels = np.where(
        ret.isna(), None,
        np.where(ret > BUY_THRESHOLD, LABEL_BUY,
        np.where(ret < SELL_THRESHOLD, LABEL_SELL, LABEL_HOLD)),
    )
    return pd.Series(labels, index=close.index, dtype="object")


def attach_labels(
    df: pd.DataFrame,
    *,
    close_col: str = "close",
    ticker_col: str = "ticker",
    horizon: int = HORIZON_DAYS,
) -> pd.DataFrame:
    """Add `forward_return` + `label` columns to a feature frame.

    The caller is responsible for grouping by ticker before invoking — we
    do that here with `groupby(ticker_col).apply` so a roll into the next
    ticker's prices can never happen. **The last `horizon` rows of every
    ticker are dropped** (their labels are unknown).

    Returns a DataFrame with the same columns plus `forward_return` and
    `label`, missing the last `horizon` rows per ticker.
    """
    if df.empty:
        out = df.copy()
        out["forward_return"] = []
        out["label"] = []
        return out

    pieces: list[pd.DataFrame] = []
    for ticker, group in df.groupby(ticker_col, sort=False):
        g = group.copy()
        ret = forward_returns(g[close_col], horizon=horizon)
        g["forward_return"] = ret
        g["label"] = label_series(g[close_col], horizon=horizon)
        # Drop the last `horizon` rows where the label is unknown.
        g = g.dropna(subset=["label"])
        pieces.append(g)
    if not pieces:
        return df.iloc[0:0].assign(forward_return=[], label=[])
    return pd.concat(pieces, axis=0)


def label_distribution(labels: Iterable[str]) -> dict[str, int]:
    """Return a {label: count} dict — used by the training script when
    writing `metrics.json`."""
    out = {LABEL_BUY: 0, LABEL_HOLD: 0, LABEL_SELL: 0}
    for lab in labels:
        if lab in out:
            out[lab] += 1
    return out
