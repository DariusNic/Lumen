"""Inference: produce a (label, confidence, explanation) signal for a ticker.

The trained pipeline is loaded lazily from `ml_models/v1/xgb_classifier.joblib`
on first call. If the artifact is missing (fresh checkout, CI), the API
endpoint surfaces a 503-equivalent error rather than serving nonsense.

Confidence comes from `predict_proba` — the maximum class probability.
Explanation comes from the rule-based engine in `explanations.py`.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from app.ml.signals.explanations import explain_row
from app.ml.signals.features import FEATURE_COLUMNS, compute_features
from app.ml.signals.labels import INT_TO_LABEL
from app.models.stock import SignalOutput
from app.models.user import utcnow
from app.services import stock_data_service
from app.utils.errors import AppError

log = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parents[3] / "ml_models" / "v1" / "xgb_classifier.joblib"
_MODEL: object | None = None
_MODEL_LOCK = threading.Lock()
_MODEL_LOAD_FAILED = False

# How many calendar days of history to pull for inference. The longest indicator
# warm-up is the 50-day EMA, but with weekends/holidays we want a safety margin
# so the latest bar always has every feature populated.
_INFERENCE_LOOKBACK_DAYS = 120


class SignalUnavailable(AppError):
    """Raised when a signal can't be produced (no data, no model, etc.)."""
    error_code = "SIGNAL_UNAVAILABLE"
    status_code = 503


def _load_model() -> object | None:
    """Lazy-load the trained Booster wrapper. Returns None if the artifact
    is missing — the API maps that to a 503."""
    global _MODEL, _MODEL_LOAD_FAILED
    if _MODEL is not None:
        return _MODEL
    if _MODEL_LOAD_FAILED:
        return None
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        if _MODEL_LOAD_FAILED:
            return None
        if not _MODEL_PATH.exists():
            log.info("Signal model not found at %s — training has not been run.", _MODEL_PATH)
            _MODEL_LOAD_FAILED = True
            return None
        try:
            import joblib
            _MODEL = joblib.load(_MODEL_PATH)
            log.info("Loaded signal model from %s", _MODEL_PATH)
        except Exception:  # noqa: BLE001
            log.exception("Failed to load signal model.")
            _MODEL_LOAD_FAILED = True
            return None
    return _MODEL


def reset_model_cache() -> None:
    """Test hook — drop the cached model so the next `predict_signal` call
    re-reads from disk."""
    global _MODEL, _MODEL_LOAD_FAILED
    with _MODEL_LOCK:
        _MODEL = None
        _MODEL_LOAD_FAILED = False


def predict_signals_batch(
    tickers: list[str], *, on: Optional[datetime] = None,
) -> list[SignalOutput]:
    """Batched inference for the MarketsPage list. Tickers without enough
    history are silently skipped — not raised — since the caller doesn't
    care about them and the page must render even if a few tickers haven't
    been seeded yet.

    Implementation: pulls history per-ticker, computes features, stacks all
    last-rows into a single DataFrame, runs `predict_proba` once. Much
    cheaper than 100 separate calls (single model dispatch, vectorized).
    """
    model = _load_model()
    if model is None:
        raise SignalUnavailable(
            "Signal model not trained yet. Run `python -m app.ml.signals.train_xgb`.",
        )

    end = on or utcnow()
    start = end - timedelta(days=_INFERENCE_LOOKBACK_DAYS)

    rows: list[pd.DataFrame] = []
    metadata: list[tuple[str, datetime, pd.Series]] = []
    for t in tickers:
        history = stock_data_service.get_history(t, start=start, end=end)
        if history.empty:
            continue
        feats = compute_features(history).dropna(subset=list(FEATURE_COLUMNS))
        if feats.empty:
            continue
        last = feats.iloc[[-1]]
        rows.append(last[list(FEATURE_COLUMNS)])
        as_of = last.index[-1]
        if isinstance(as_of, pd.Timestamp):
            as_of = as_of.to_pydatetime()
        metadata.append((t, as_of, last.iloc[0]))

    if not rows:
        return []

    x = pd.concat(rows, ignore_index=True)
    proba_matrix = np.asarray(model.predict_proba(x), dtype=float)
    classes = list(getattr(model, "classes_", [0, 1, 2]))

    results: list[SignalOutput] = []
    for (ticker, as_of, last_row), proba in zip(metadata, proba_matrix):
        proba_list = list(proba)
        best = max(range(len(proba_list)), key=lambda i: proba_list[i])
        label = INT_TO_LABEL[int(classes[best])]
        confidence = float(proba_list[best])
        probabilities = {INT_TO_LABEL[int(c)]: float(p) for c, p in zip(classes, proba_list)}
        results.append(SignalOutput(
            ticker=ticker,
            as_of=as_of,
            label=label,
            confidence=confidence,
            probabilities=probabilities,
            explanation=explain_row(last_row, label),
        ))
    return results


def predict_signal(ticker: str, *, on: Optional[datetime] = None) -> SignalOutput:
    """Produce the latest BUY / HOLD / SELL signal for `ticker`.

    Pulls the last ~120 days of history, computes features, and runs the
    Booster against the most recent fully-populated row. Returns a
    `SignalOutput` Pydantic model the API can `model_dump()` directly.

    Raises `SignalUnavailable` (503) when:
      - the model artifact is missing
      - the ticker has no data in `stock_data`
      - the latest features still have NaN (history too short for warm-up)
    """
    model = _load_model()
    if model is None:
        raise SignalUnavailable(
            "Signal model not trained yet. Run `python -m app.ml.signals.train_xgb` "
            "from the backend directory.",
        )

    end = on or utcnow()
    start = end - timedelta(days=_INFERENCE_LOOKBACK_DAYS)
    history = stock_data_service.get_history(ticker, start=start, end=end)
    if history.empty:
        raise SignalUnavailable(
            f"No price history for {ticker}. Run the seed or daily refresh first.",
            details={"ticker": ticker},
        )

    features = compute_features(history).dropna(subset=list(FEATURE_COLUMNS))
    if features.empty:
        raise SignalUnavailable(
            f"Not enough recent history for {ticker} to compute all features.",
            details={"ticker": ticker, "rows": int(len(history))},
        )

    last = features.iloc[[-1]]
    x = last[list(FEATURE_COLUMNS)]
    proba = np.asarray(model.predict_proba(x)[0], dtype=float)
    classes = list(getattr(model, "classes_", [0, 1, 2]))

    best_idx = int(np.argmax(proba))
    label = INT_TO_LABEL[int(classes[best_idx])]
    confidence = float(proba[best_idx])
    probabilities = {INT_TO_LABEL[int(c)]: float(p) for c, p in zip(classes, proba)}
    explanation = explain_row(last.iloc[0], label)

    as_of = last.index[-1]
    if isinstance(as_of, pd.Timestamp):
        as_of = as_of.to_pydatetime()

    return SignalOutput(
        ticker=ticker,
        as_of=as_of,
        label=label,
        confidence=confidence,
        probabilities=probabilities,
        explanation=explanation,
    )
