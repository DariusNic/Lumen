"""Feature engineering tests — the most important guarantees:

1. **No future leakage**: features at row t depend only on rows ≤ t.
   We verify by computing features twice — once on the full series, and
   once on the series truncated at row t — and asserting the value at
   row t is identical between the two.
2. **Per-ticker integrity**: when we concatenate two tickers' frames,
   the second ticker's features must NOT be influenced by the first
   ticker's prices. We verify by computing features on the second
   ticker alone vs in-universe and asserting they're identical.
3. **Column contract**: the `FEATURE_COLUMNS` tuple is the model
   contract — adding/removing without a coordinated retrain is a bug.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.signals.features import (
    FEATURE_COLUMNS,
    compute_features,
    compute_features_for,
    compute_features_universe,
)


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------

def _synthetic_history(n_days: int = 200, seed: int = 0, base: float = 100.0) -> pd.DataFrame:
    """Build a deterministic OHLCV frame with `n_days` rows. Random walk for
    close, OHLV derived consistently. Index is daily timestamps."""
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.standard_normal(n_days) * 0.8)
    high = close + np.abs(rng.standard_normal(n_days) * 0.5)
    low = close - np.abs(rng.standard_normal(n_days) * 0.5)
    opens = close + rng.standard_normal(n_days) * 0.3
    volume = rng.integers(1_000_000, 5_000_000, n_days).astype(float)
    idx = pd.date_range("2024-01-02", periods=n_days, freq="B")
    return pd.DataFrame(
        {"open": opens, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


# ---------------------------------------------------------------------------
# Column contract
# ---------------------------------------------------------------------------

def test_feature_columns_count():
    """The contract is 19 features (17 numeric indicators + dow + month);
    bumping this needs a coordinated retrain."""
    assert len(FEATURE_COLUMNS) == 19


def test_compute_features_returns_expected_columns():
    df = _synthetic_history()
    feats = compute_features(df)
    expected = set(FEATURE_COLUMNS) | {"close"}
    assert set(feats.columns) == expected


def test_compute_features_preserves_index():
    df = _synthetic_history()
    feats = compute_features(df)
    assert feats.index.equals(df.index)


def test_compute_features_empty_frame_returns_empty():
    feats = compute_features(pd.DataFrame())
    assert feats.empty
    assert set(feats.columns) == set(FEATURE_COLUMNS) | {"close"}


def test_compute_features_rejects_unsorted_index():
    df = _synthetic_history()
    df = df.iloc[::-1]  # descending
    with pytest.raises(ValueError, match="ascending-sorted"):
        compute_features(df)


# ---------------------------------------------------------------------------
# No-leakage guarantees (the headline test)
# ---------------------------------------------------------------------------

def test_no_future_leakage_in_any_feature():
    """For a chosen mid-series row t, compute features on the full series and
    on the series truncated at t. Every feature value at t must be identical
    between the two — otherwise the feature peeked at future data."""
    df = _synthetic_history(n_days=200, seed=42)
    feats_full = compute_features(df).iloc[100]    # row 100
    feats_trunc = compute_features(df.iloc[:101]).iloc[-1]   # same row, but the future doesn't exist

    for col in FEATURE_COLUMNS:
        a = feats_full[col]
        b = feats_trunc[col]
        # NaN compares False to itself; treat both-NaN as equal.
        if pd.isna(a) and pd.isna(b):
            continue
        assert a == pytest.approx(b, rel=1e-9), (
            f"feature {col!r} leaks future data: full={a} vs trunc={b}"
        )


def test_returns_use_only_past_data():
    """`ret_5d` at row t = close[t]/close[t-5] - 1, no future."""
    df = _synthetic_history(n_days=50, seed=1)
    feats = compute_features(df)
    expected = df["close"].iloc[20] / df["close"].iloc[15] - 1.0
    assert feats["ret_5d"].iloc[20] == pytest.approx(expected, rel=1e-9)


def test_warmup_rows_have_nans():
    """The first ~50 rows can't have all features (50-day EMA needs 50 days
    of history). Verify the warm-up zone is NaN, the post-warmup zone isn't."""
    df = _synthetic_history(n_days=200)
    feats = compute_features(df)
    # First 5 rows have at least some NaNs (most indicators not yet warm).
    assert feats.iloc[:5][list(FEATURE_COLUMNS)].isna().any().any()
    # Late-series rows are fully populated.
    assert not feats.iloc[-1][list(FEATURE_COLUMNS)].isna().any()


# ---------------------------------------------------------------------------
# Per-ticker integrity
# ---------------------------------------------------------------------------

def test_per_ticker_features_dont_leak_across_tickers(client):
    """Compute features for AAPL alone vs (AAPL + MSFT) in the universe.
    The AAPL rows in both runs must match — MSFT's prices must never have
    influenced AAPL's rolling windows."""
    from app.services import stock_data_service
    from unittest.mock import patch

    aapl = _synthetic_history(n_days=200, seed=10, base=180)
    msft = _synthetic_history(n_days=200, seed=20, base=370)

    # Patch the data layer so compute_features_for / _universe pull the
    # synthetic frames instead of touching Mongo.
    def fake_get_history(ticker, **kw):
        if ticker == "AAPL":
            return aapl
        if ticker == "MSFT":
            return msft
        return pd.DataFrame()

    with patch.object(stock_data_service, "get_history", side_effect=fake_get_history):
        solo = compute_features_universe(["AAPL"])
        combo = compute_features_universe(["AAPL", "MSFT"])

    aapl_solo = solo[solo["ticker"] == "AAPL"][list(FEATURE_COLUMNS)].reset_index(drop=True)
    aapl_combo = combo[combo["ticker"] == "AAPL"][list(FEATURE_COLUMNS)].reset_index(drop=True)
    pd.testing.assert_frame_equal(aapl_solo, aapl_combo, check_exact=False, rtol=1e-9)


def test_universe_drops_warmup_when_requested(client):
    from app.services import stock_data_service
    from unittest.mock import patch

    df = _synthetic_history(n_days=200)
    with patch.object(stock_data_service, "get_history", return_value=df):
        with_warmup = compute_features_universe(["X"], drop_warmup=False)
        no_warmup = compute_features_universe(["X"], drop_warmup=True)

    assert len(with_warmup) > len(no_warmup)
    # The kept slice has no NaN features anywhere.
    assert not no_warmup[list(FEATURE_COLUMNS)].isna().any().any()


def test_universe_with_no_data_returns_empty_frame(client):
    """Tickers that yfinance never delivered (or got skipped) just produce
    no rows — they shouldn't crash the pipeline."""
    from app.services import stock_data_service
    from unittest.mock import patch

    with patch.object(stock_data_service, "get_history", return_value=pd.DataFrame()):
        out = compute_features_universe(["NOPE", "ALSO_NOPE"])
    assert out.empty
    assert "ticker" in out.columns


# ---------------------------------------------------------------------------
# Smoke test against the real `stock_data` collection (when present)
# ---------------------------------------------------------------------------

def test_compute_features_for_returns_empty_when_no_data(client):
    """No seeded data in mongomock → empty frame, no exception."""
    out = compute_features_for("AAPL")
    assert out.empty
