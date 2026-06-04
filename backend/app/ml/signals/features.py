"""Feature engineering for the XGBoost stock-signal model.

Time-series rules (locked):
  - **No future data leakage.** Every feature at row t uses only data
    from rows ≤ t. We never call rolling with `center=True`. pandas-ta
    indicators are causal by construction.
  - **Per-ticker integrity.** Features are computed *within* each ticker
    group, then concatenated. We never let a rolling window cross
    ticker boundaries.
  - **Adjusted prices.** The data fetcher uses `auto_adjust=True`, so
    `close` already accounts for splits and dividends. No raw prices
    in the feature space — we work with relative quantities (returns,
    ratios, z-scores) so the model isn't anchored to nominal price levels.

Feature set (19 columns + ticker + date, all from pandas-ta-classic):

  Returns      ret_1d, ret_5d, ret_21d
  Momentum     rsi_14, stoch_k_14, stoch_d_14
  Trend        macd, macd_signal, macd_hist,
               ema_10_ratio, ema_21_ratio, ema_50_ratio
  Volatility   atr_14_pct, bb_pctb_20, bb_bandwidth_20
  Volume       volume_z_21, obv_change_5
  Calendar     dow, month
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import pandas_ta_classic as ta

from app.services import stock_data_service

log = logging.getLogger(__name__)

# Column order is part of the model contract — exposed as a constant so the
# training script and the inference path read it from one place.
FEATURE_COLUMNS: tuple[str, ...] = (
    "ret_1d", "ret_5d", "ret_21d",
    "rsi_14", "stoch_k_14", "stoch_d_14",
    "macd", "macd_signal", "macd_hist",
    "ema_10_ratio", "ema_21_ratio", "ema_50_ratio",
    "atr_14_pct", "bb_pctb_20", "bb_bandwidth_20",
    "volume_z_21", "obv_change_5",
    "dow", "month",
)


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the full feature set for ONE ticker's history.

    Input: a DataFrame with `open / high / low / close / volume` columns
    indexed by date, sorted ascending. The frame `stock_data_service.get_history`
    returns is already in this shape.

    Output: a DataFrame indexed by date with `FEATURE_COLUMNS` plus the
    closing price (`close` is kept for label computation downstream).

    Rows where any feature is NaN (typical for the first ~50 rows of a
    ticker until all indicator warm-up windows fill) are returned as-is —
    the caller's `dropna` call decides where to trim.
    """
    if df.empty:
        return pd.DataFrame(columns=list(FEATURE_COLUMNS) + ["close"])
    if not df.index.is_monotonic_increasing:
        raise ValueError("compute_features expects an ascending-sorted date index")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    out = pd.DataFrame(index=df.index)
    nan_series = pd.Series(np.nan, index=df.index)

    # pandas-ta returns `None` (not a DataFrame) when the input is shorter
    # than the indicator's window. We coerce to NaN-filled placeholders so
    # the column contract is preserved — the dropna pass downstream removes
    # the warmup rows uniformly.
    def _col(value, key: str | None = None) -> pd.Series:
        if value is None:
            return nan_series
        if isinstance(value, pd.DataFrame):
            return value[key] if key in value.columns else nan_series
        return value

    # --- Returns ------------------------------------------------------------
    # `pct_change(n)` = close[t]/close[t-n] - 1, point-in-time by definition.
    out["ret_1d"] = close.pct_change(1)
    out["ret_5d"] = close.pct_change(5)
    out["ret_21d"] = close.pct_change(21)

    # --- Momentum -----------------------------------------------------------
    out["rsi_14"] = _col(ta.rsi(close, length=14))
    stoch = ta.stoch(high, low, close, k=14, d=3)
    out["stoch_k_14"] = _col(stoch, "STOCHk_14_3_3")
    out["stoch_d_14"] = _col(stoch, "STOCHd_14_3_3")

    # --- Trend --------------------------------------------------------------
    macd = ta.macd(close, fast=12, slow=26, signal=9)
    out["macd"] = _col(macd, "MACD_12_26_9")
    out["macd_signal"] = _col(macd, "MACDs_12_26_9")
    out["macd_hist"] = _col(macd, "MACDh_12_26_9")
    ema_10 = _col(ta.ema(close, length=10))
    ema_21 = _col(ta.ema(close, length=21))
    ema_50 = _col(ta.ema(close, length=50))
    out["ema_10_ratio"] = close / ema_10 - 1.0
    out["ema_21_ratio"] = close / ema_21 - 1.0
    out["ema_50_ratio"] = close / ema_50 - 1.0

    # --- Volatility ---------------------------------------------------------
    out["atr_14_pct"] = _col(ta.atr(high, low, close, length=14)) / close
    bb = ta.bbands(close, length=20, std=2)
    out["bb_pctb_20"] = _col(bb, "BBP_20_2.0")
    bbu = _col(bb, "BBU_20_2.0")
    bbl = _col(bb, "BBL_20_2.0")
    # Bollinger bandwidth normalized to close (% of price) — comparable across tickers.
    out["bb_bandwidth_20"] = (bbu - bbl) / close

    # --- Volume -------------------------------------------------------------
    vol_mean_21 = volume.rolling(window=21, min_periods=21).mean()
    vol_std_21 = volume.rolling(window=21, min_periods=21).std()
    out["volume_z_21"] = (volume - vol_mean_21) / vol_std_21
    obv = ta.obv(close, volume)
    out["obv_change_5"] = obv.pct_change(5)

    # --- Calendar -----------------------------------------------------------
    # 0 = Monday, 4 = Friday. Captures weekly seasonality (e.g. Friday close
    # patterns) without us having to invent a holiday calendar.
    out["dow"] = df.index.dayofweek
    out["month"] = df.index.month

    out["close"] = close

    # Replace +/-inf with NaN so the dropna pass downstream removes them
    # instead of polluting XGBoost.
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    return out


def compute_features_for(
    ticker: str,
    *,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Convenience: fetch a ticker's history from `stock_data` and run
    `compute_features` on it. Adds `ticker` as a column so multi-ticker
    concatenation is unambiguous."""
    history = stock_data_service.get_history(ticker, start=start, end=end)
    if history.empty:
        return pd.DataFrame(columns=["ticker", *FEATURE_COLUMNS, "close"])
    feats = compute_features(history)
    feats.insert(0, "ticker", ticker)
    return feats


def compute_features_universe(
    tickers: Iterable[str],
    *,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
    drop_warmup: bool = True,
) -> pd.DataFrame:
    """Compute features for every ticker in `tickers`, concatenate, and
    return one long DataFrame. **Each ticker's features are computed in
    isolation** — rolling windows never cross ticker boundaries.

    `drop_warmup=True` (default): drop rows where any feature is NaN. This
    typically clips the first ~50 bars per ticker (longest indicator
    warm-up is the 50-day EMA).
    """
    frames: list[pd.DataFrame] = []
    for t in tickers:
        f = compute_features_for(t, start=start, end=end)
        if not f.empty:
            frames.append(f)
    if not frames:
        return pd.DataFrame(columns=["ticker", *FEATURE_COLUMNS, "close"])
    combined = pd.concat(frames, axis=0)
    if drop_warmup:
        combined = combined.dropna(subset=list(FEATURE_COLUMNS))
    return combined
