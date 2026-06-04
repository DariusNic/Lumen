"""Inference tests for `app/ml/signals/predict.py`.

We don't retrain inside the suite — that would be slow and bring randomness.
Instead each test installs a tiny FakeBooster directly into `predict._MODEL`
so the cascade behavior is exercised without joblib I/O or XGBoost overhead.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.ml.signals import predict
from app.ml.signals.labels import LABEL_TO_INT


@pytest.fixture(autouse=True)
def _restore_model_cache():
    yield
    predict.reset_model_cache()


# ---------------------------------------------------------------------------
# FakeBooster — same interface as XGBClassifier for our needs
# ---------------------------------------------------------------------------

class FakeBooster:
    """Returns a fixed `predict_proba` regardless of features. The default is
    BUY-leaning (proba = [0.05, 0.20, 0.75]) so happy-path tests have a
    confident BUY to assert on. Override per-test by passing `proba`."""

    classes_ = np.array([0, 1, 2])  # SELL=0, HOLD=1, BUY=2

    def __init__(self, proba=None):
        self._proba = np.array(proba if proba is not None else [0.05, 0.20, 0.75], dtype=float)

    def predict_proba(self, x):
        n = len(x)
        return np.tile(self._proba, (n, 1))


def _install(model) -> None:
    predict._MODEL = model
    predict._MODEL_LOAD_FAILED = False


def _seed_history(client, ticker: str = "AAPL", n_days: int = 200) -> None:
    """Seed `n_days` of synthetic OHLCV bars for `ticker` so that the
    inference pipeline has enough history for the 50-day-EMA warmup."""
    from app.extensions import mongo

    rng = np.random.default_rng(42)
    close = 180 + np.cumsum(rng.standard_normal(n_days) * 0.8)
    rows = []
    base_date = datetime(2024, 1, 1)
    for i in range(n_days):
        c = float(close[i])
        rows.append({
            "ticker": ticker,
            "date": base_date + timedelta(days=i),
            "open": c - 0.3,
            "high": c + 0.5,
            "low": c - 0.5,
            "close": c,
            "volume": float(rng.integers(1_000_000, 5_000_000)),
        })
    mongo.db["stock_data"].insert_many(rows)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_predict_returns_buy_signal_with_confidence(client):
    _seed_history(client)
    _install(FakeBooster(proba=[0.05, 0.20, 0.75]))

    out = predict.predict_signal("AAPL", on=datetime(2024, 6, 30))
    assert out.ticker == "AAPL"
    assert out.label == "BUY"
    assert out.confidence == pytest.approx(0.75)
    assert out.probabilities == {"SELL": 0.05, "HOLD": 0.20, "BUY": 0.75}
    # Explanation is non-empty and deterministic (rule-based).
    assert isinstance(out.explanation, str)
    assert len(out.explanation) > 0


def test_predict_returns_sell_when_proba_dominates_class_0(client):
    _seed_history(client)
    _install(FakeBooster(proba=[0.80, 0.15, 0.05]))
    out = predict.predict_signal("AAPL", on=datetime(2024, 6, 30))
    assert out.label == "SELL"
    assert out.confidence == pytest.approx(0.80)


def test_predict_returns_hold_when_proba_dominates_class_1(client):
    _seed_history(client)
    _install(FakeBooster(proba=[0.10, 0.85, 0.05]))
    out = predict.predict_signal("AAPL", on=datetime(2024, 6, 30))
    assert out.label == "HOLD"


def test_predict_uses_latest_bar_as_of(client):
    _seed_history(client, n_days=200)
    _install(FakeBooster())
    # The latest bar in the seed is 2024-01-01 + 199 days → 2024-07-18.
    out = predict.predict_signal("AAPL", on=datetime(2024, 8, 1))
    # `as_of` is the last bar with all features populated, which lives within
    # the last few rows of the seeded window.
    assert out.as_of <= datetime(2024, 8, 1)
    assert out.as_of >= datetime(2024, 6, 30)


# ---------------------------------------------------------------------------
# Error paths — surface as 503 SignalUnavailable
# ---------------------------------------------------------------------------

def test_missing_model_raises_signal_unavailable(client, tmp_path):
    """Fresh checkout: no joblib artifact → SignalUnavailable, not nonsense."""
    _seed_history(client)
    with patch.object(predict, "_MODEL_PATH", tmp_path / "nope.joblib"):
        predict.reset_model_cache()
        with pytest.raises(predict.SignalUnavailable) as excinfo:
            predict.predict_signal("AAPL")
    assert excinfo.value.status_code == 503
    assert "not trained" in excinfo.value.message.lower()


def test_unknown_ticker_raises_signal_unavailable(client):
    """No data in `stock_data` for the ticker → SignalUnavailable."""
    _install(FakeBooster())
    with pytest.raises(predict.SignalUnavailable) as excinfo:
        predict.predict_signal("NOPE")
    assert excinfo.value.status_code == 503
    assert "no price history" in excinfo.value.message.lower()


def test_too_short_history_raises_signal_unavailable(client):
    """If the ticker has only a few bars, indicator warmup never fills →
    every row has NaN features → SignalUnavailable."""
    _seed_history(client, n_days=10)
    _install(FakeBooster())
    with pytest.raises(predict.SignalUnavailable) as excinfo:
        predict.predict_signal("AAPL", on=datetime(2024, 1, 15))
    assert "not enough" in excinfo.value.message.lower()


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

def test_reset_model_cache_clears_loaded_model(client, tmp_path):
    _install(FakeBooster())
    assert predict._MODEL is not None
    predict.reset_model_cache()
    assert predict._MODEL is None
    assert predict._MODEL_LOAD_FAILED is False


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

def test_probabilities_sum_to_one_and_keys_match_labels(client):
    _seed_history(client)
    _install(FakeBooster(proba=[0.30, 0.40, 0.30]))
    out = predict.predict_signal("AAPL", on=datetime(2024, 6, 30))

    assert set(out.probabilities.keys()) == {"BUY", "HOLD", "SELL"}
    total = sum(out.probabilities.values())
    assert total == pytest.approx(1.0, rel=1e-6)


def test_signal_output_serializes_to_json(client):
    """The endpoint will call `model_dump(mode="json")` — verify the result
    is a dict of plain primitives so Flask's `jsonify` won't choke."""
    _seed_history(client)
    _install(FakeBooster())
    out = predict.predict_signal("AAPL", on=datetime(2024, 6, 30))
    blob = out.model_dump(mode="json")
    assert isinstance(blob, dict)
    assert blob["ticker"] == "AAPL"
    assert blob["label"] in {"BUY", "HOLD", "SELL"}
    assert isinstance(blob["confidence"], float)
    assert isinstance(blob["probabilities"], dict)
    assert isinstance(blob["explanation"], str)
