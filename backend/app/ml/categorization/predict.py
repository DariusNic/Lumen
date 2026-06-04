"""The categorization cascade.

The order is fixed: rules → ML → fallback "Other".

The ML stage is a TF-IDF char_wb (3, 5) + LogisticRegression pipeline trained
by `train_tfidf_lr.py` and serialized to `ml_models/v1/tfidf_lr.joblib`.
We accept its prediction only when `predict_proba` for the winning class is
≥ `ML_CONFIDENCE_THRESHOLD` (0.65). Below that, fall through to the
fallback so we never mislabel ambiguous descriptions with high confidence.

The model is loaded lazily on first call so import-time cost is zero and
test environments without `ml_models/v1/` artifacts still work — they just
skip the ML stage and use rules → "Other" only.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from app.ml.categorization.rules import categorize_by_rules

log = logging.getLogger(__name__)

FALLBACK_CATEGORY = "Other"
ML_CONFIDENCE_THRESHOLD = 0.65

_MODEL_PATH = Path(__file__).resolve().parents[3] / "ml_models" / "v1" / "tfidf_lr.joblib"
_MODEL: Optional[object] = None
_MODEL_LOCK = threading.Lock()
# Sentinel — we tried to load and failed. Avoids retrying on every call when
# the artifact genuinely isn't there (CI, fresh checkout).
_MODEL_LOAD_FAILED = False


def _load_model() -> Optional[object]:
    """Lazy-load the trained pipeline. Returns None when the artifact is
    missing — the cascade then degrades cleanly to rules → fallback."""
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
            log.info("Categorization ML model not found at %s — cascade will use rules only.", _MODEL_PATH)
            _MODEL_LOAD_FAILED = True
            return None
        try:
            import joblib  # imported lazily so the rest of the app doesn't pay for it
            _MODEL = joblib.load(_MODEL_PATH)
            log.info("Loaded categorization ML model from %s", _MODEL_PATH)
        except Exception:  # noqa: BLE001 — corrupt artifact shouldn't break categorization
            log.exception("Failed to load categorization ML model — cascade will use rules only.")
            _MODEL_LOAD_FAILED = True
            return None
    return _MODEL


def _ml_predict(description: str) -> Optional[str]:
    """Run the ML model. Return the predicted category name when its
    confidence ≥ ML_CONFIDENCE_THRESHOLD, otherwise None (caller falls back)."""
    model = _load_model()
    if model is None:
        return None
    try:
        proba = list(model.predict_proba([description])[0])
        classes = list(model.classes_)
    except Exception:  # noqa: BLE001 — never let a model glitch break categorization
        log.exception("ML predict_proba raised on description=%r", description)
        return None
    best_idx = max(range(len(proba)), key=lambda i: proba[i])
    confidence = float(proba[best_idx])
    if confidence < ML_CONFIDENCE_THRESHOLD:
        return None
    label = str(classes[best_idx])
    if label == FALLBACK_CATEGORY:
        # If even the model is most confident in "Other", let the fallback path
        # handle it — keeps the contract that ML decisions are *positive* hits.
        return None
    return label


def categorize(description: str) -> str:
    """Return the best-guess category name for a transaction description.

    Cascade: rules → ML (if ≥ 0.65 confidence) → "Other".
    Always returns one of the 14 system category names — never None — so the
    caller can resolve it directly to a `CategoryPublic.id`.
    """
    rule_hit = categorize_by_rules(description or "")
    if rule_hit is not None:
        return rule_hit

    ml_hit = _ml_predict(description or "")
    if ml_hit is not None:
        return ml_hit

    return FALLBACK_CATEGORY


def reset_model_cache() -> None:
    """Test hook: clear the lazy-loaded model so the next `categorize` call
    re-reads from disk. Useful for tests that train a fresh model and verify
    the cascade picks it up."""
    global _MODEL, _MODEL_LOAD_FAILED
    with _MODEL_LOCK:
        _MODEL = None
        _MODEL_LOAD_FAILED = False
