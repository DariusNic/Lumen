"""One-off backtest of the XGBoost stock-signal classifier on the held-out
test window (2024-01-01 onward).

This is a scratch script, not production code. It exists to produce honest
accuracy numbers as an independent check on the training script's own
self-reported metrics.

Run from `backend/`:
    .venv/Scripts/python.exe -m scripts.backtest_signals

Outputs everything to stdout. Writes nothing.

What it does:
  1. Boots a Flask app context so PyMongo / config / extensions load.
  2. For every ticker in `TICKERS`, pulls OHLCV from 2024-01-01 onward,
     computes the EXACT same features as production via
     `compute_features_for(...)`, attaches forward-looking 5-day labels via
     `attach_labels(...)`, and concatenates into one long frame.
  3. Loads the trained model from `ml_models/v1/xgb_classifier.joblib` and
     runs `model.predict()` on every labeled row.
  4. Reports overall accuracy, per-class precision/recall/F1, confusion
     matrix, baseline ("always HOLD") comparison, the model's own
     `signals_metrics.json` for cross-reference, and a note about coverage
     vs. the requested 1,000-prediction minimum.

Honesty contract: the splits, the thresholds, and the feature stack come
from production code — this script does NOT redefine any of them.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

# Ensure we're running with `backend/` on the path so `from app.* import ...`
# works regardless of cwd. The script is invoked via `python -m scripts.x`
# from `backend/`.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app import create_app  # noqa: E402
from app.ml.signals.features import FEATURE_COLUMNS, compute_features_for  # noqa: E402
from app.ml.signals.labels import (  # noqa: E402
    INT_TO_LABEL,
    LABEL_TO_INT,
    attach_labels,
)
from app.utils.constants import TICKERS  # noqa: E402

# Test window — locked.
TEST_START = pd.Timestamp("2024-01-01")

_MODEL_PATH = _BACKEND_DIR / "ml_models" / "v1" / "xgb_classifier.joblib"
_METRICS_PATH = _BACKEND_DIR / "ml_models" / "v1" / "signals_metrics.json"


def _load_model():
    import joblib

    if not _MODEL_PATH.exists():
        raise SystemExit(
            f"Model artifact missing at {_MODEL_PATH}. "
            f"Run `python -m app.ml.signals.train_xgb` first."
        )
    return joblib.load(_MODEL_PATH)


def _build_test_set() -> pd.DataFrame:
    """Compute features + labels for every ticker in the universe, restricted
    to the locked test window. Mirrors `train_xgb.load_labeled_dataset` but
    sliced for the test split only."""
    frames: list[pd.DataFrame] = []
    no_data: list[str] = []
    for t in TICKERS:
        # Pull from a bit before TEST_START so the indicator warm-up (~50 bars
        # for EMA-50) has room. Without this buffer the first ~2.5 months of
        # 2024 would be NaN'd out by the dropna pass.
        warmup_start = pd.Timestamp("2023-09-01")
        f = compute_features_for(t, start=warmup_start)
        if f.empty:
            no_data.append(t)
            continue
        frames.append(f)

    if not frames:
        raise SystemExit(
            "No data returned for any ticker. Is `stock_data` empty? "
            "Run `python -m scripts.seed_stock_data` first."
        )

    combined = pd.concat(frames, axis=0)
    combined = combined.dropna(subset=list(FEATURE_COLUMNS))
    labeled = attach_labels(combined)
    labeled = labeled.reset_index().rename(columns={"index": "date"})
    if "date" not in labeled.columns:
        labeled["date"] = labeled.iloc[:, 0]
    labeled["date"] = pd.to_datetime(labeled["date"])

    # Slice down to the locked test window.
    test = labeled[labeled["date"] >= TEST_START].copy()
    test = test.sort_values(["date", "ticker"]).reset_index(drop=True)

    if no_data:
        print(f"  (no data for {len(no_data)} tickers: {', '.join(no_data[:10])}"
              f"{'...' if len(no_data) > 10 else ''})", flush=True)
    return test


def _print_header(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n{title}\n{bar}", flush=True)


def _print_per_class(y_true: np.ndarray, y_pred: np.ndarray) -> None:
    labels_int = [LABEL_TO_INT["SELL"], LABEL_TO_INT["HOLD"], LABEL_TO_INT["BUY"]]
    target_names = ["SELL", "HOLD", "BUY"]
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels_int, zero_division=0
    )
    print(f"  {'class':<6}  {'precision':>10}  {'recall':>10}  {'F1':>10}  {'support':>10}")
    print(f"  {'-' * 6}  {'-' * 10}  {'-' * 10}  {'-' * 10}  {'-' * 10}")
    for name, p, r, f, s in zip(target_names, precision, recall, f1, support):
        print(f"  {name:<6}  {p:>10.4f}  {r:>10.4f}  {f:>10.4f}  {int(s):>10d}")

    macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    weighted_f1 = f1_score(y_true, y_pred, average="weighted", zero_division=0)
    print(f"\n  macro F1:    {macro_f1:.4f}")
    print(f"  weighted F1: {weighted_f1:.4f}")


def _print_confusion(y_true: np.ndarray, y_pred: np.ndarray) -> None:
    labels_int = [LABEL_TO_INT["SELL"], LABEL_TO_INT["HOLD"], LABEL_TO_INT["BUY"]]
    cm = confusion_matrix(y_true, y_pred, labels=labels_int)
    names = ["SELL", "HOLD", "BUY"]
    print("  rows = true label, cols = predicted label")
    print(f"  {'':<8}  {'SELL':>8}  {'HOLD':>8}  {'BUY':>8}  {'total':>8}")
    print(f"  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 8}  {'-' * 8}")
    for i, n in enumerate(names):
        row_total = int(cm[i].sum())
        print(f"  {n:<8}  {int(cm[i][0]):>8d}  {int(cm[i][1]):>8d}  {int(cm[i][2]):>8d}  {row_total:>8d}")
    col_totals = cm.sum(axis=0)
    print(f"  {'total':<8}  {int(col_totals[0]):>8d}  {int(col_totals[1]):>8d}  "
          f"{int(col_totals[2]):>8d}  {int(cm.sum()):>8d}")


def _print_baseline(y_true: np.ndarray) -> None:
    """Naive baseline: always predict the training-time majority class (HOLD)."""
    hold_int = LABEL_TO_INT["HOLD"]
    y_baseline = np.full_like(y_true, hold_int)
    acc = accuracy_score(y_true, y_baseline)
    macro = f1_score(y_true, y_baseline, average="macro", zero_division=0)
    weighted = f1_score(y_true, y_baseline, average="weighted", zero_division=0)
    print(f"  always-HOLD accuracy: {acc:.4f}")
    print(f"  always-HOLD macro F1: {macro:.4f}")
    print(f"  always-HOLD weighted F1: {weighted:.4f}")


def _print_saved_metrics() -> None:
    if not _METRICS_PATH.exists():
        print(f"  (no signals_metrics.json at {_METRICS_PATH})")
        return
    with _METRICS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    splits = data.get("splits", {})
    print(f"  trained_at:      {data.get('trained_at')}")
    print(f"  best_iteration:  {data.get('best_iteration')}")
    print(f"  train_end:       {data.get('split_dates', {}).get('train_end')}")
    print(f"  val_end:         {data.get('split_dates', {}).get('val_end')}")
    print()
    print(f"  {'split':<12}  {'rows':>8}  {'date_from':>12}  {'date_to':>12}  "
          f"{'accuracy':>10}  {'macro_F1':>10}  {'sharpe':>8}")
    print(f"  {'-' * 12}  {'-' * 8}  {'-' * 12}  {'-' * 12}  "
          f"{'-' * 10}  {'-' * 10}  {'-' * 8}")
    for name in ("train", "validation", "test"):
        s = splits.get(name, {})
        if not s:
            continue
        date_from = (s.get("date_from") or "")[:10]
        date_to = (s.get("date_to") or "")[:10]
        print(f"  {name:<12}  {int(s.get('rows', 0)):>8d}  {date_from:>12}  {date_to:>12}  "
              f"{float(s.get('accuracy', 0)):>10.4f}  {float(s.get('macro_f1', 0)):>10.4f}  "
              f"{float(s.get('sharpe', 0)):>+8.2f}")


def main() -> None:
    app = create_app()
    with app.app_context():
        print("Loading model artifact...", flush=True)
        model = _load_model()
        print(f"  loaded: {_MODEL_PATH}", flush=True)

        print("\nBuilding test set (features + labels, 2024-01-01 onward)...", flush=True)
        test = _build_test_set()
        n = len(test)
        print(f"  test rows: {n:,}  ·  tickers covered: {test['ticker'].nunique()}", flush=True)
        if n > 0:
            print(f"  date range: {test['date'].min().date()} -> {test['date'].max().date()}", flush=True)

        if n == 0:
            print("\nNo test rows produced. Likely `stock_data` has no data from 2024-01-01 onward.")
            return

        # Label distribution on the test window
        dist = Counter(test["label"])
        print("\n  label distribution on test window:")
        for lab in ("SELL", "HOLD", "BUY"):
            cnt = int(dist.get(lab, 0))
            pct = cnt / n * 100.0 if n else 0.0
            print(f"    {lab:<6}  {cnt:>8,}  ({pct:5.2f}%)")

        # Run inference
        print("\nRunning model.predict()...", flush=True)
        x = test[list(FEATURE_COLUMNS)]
        y_true = test["label"].map(LABEL_TO_INT).to_numpy()
        y_pred = np.asarray(model.predict(x), dtype=int)
        print(f"  predictions: {len(y_pred):,}", flush=True)

        # --- Coverage check vs. the requested 1,000-prediction minimum ----
        _print_header("Coverage")
        if n >= 1000:
            print(f"  N = {n:,} predictions — comfortably above the 1,000 minimum.")
        else:
            print(f"  N = {n} predictions — BELOW the requested 1,000 minimum.")
            print(f"  Likely cause: the test window starts {TEST_START.date()} "
                  f"and {len(TICKERS)} tickers were requested but only "
                  f"{test['ticker'].nunique()} produced data after the warm-up + label trim.")

        # --- Overall accuracy ---------------------------------------------
        _print_header("Overall accuracy")
        acc = accuracy_score(y_true, y_pred)
        print(f"  accuracy:  {acc:.4f}  ({(y_true == y_pred).sum():,} / {n:,} correct)")

        # --- Per-class metrics --------------------------------------------
        _print_header("Per-class precision / recall / F1")
        _print_per_class(y_true, y_pred)

        # --- Confusion matrix --------------------------------------------
        _print_header("Confusion matrix (test set)")
        _print_confusion(y_true, y_pred)

        # --- Baseline comparison ------------------------------------------
        _print_header("Naive baseline (always predict HOLD — the majority class)")
        _print_baseline(y_true)
        print()
        hold_acc = (y_true == LABEL_TO_INT["HOLD"]).mean()
        delta = acc - hold_acc
        sign = "+" if delta >= 0 else ""
        print(f"  model vs. always-HOLD: {sign}{delta * 100:.2f} percentage points")
        if delta <= 0:
            print("  WARNING: the model does NOT beat the naive baseline on this window.")
        elif delta < 0.02:
            print("  NOTE: the model beats always-HOLD by less than 2 pp — marginal edge.")

        # Confidence comes from predict_proba — show the mean max-probability
        # so we can comment on calibration.
        proba = np.asarray(model.predict_proba(x), dtype=float)
        max_conf = proba.max(axis=1)
        correct_mask = y_true == y_pred
        print(f"\n  mean max-probability (overall): {max_conf.mean():.4f}")
        if correct_mask.any():
            print(f"  mean max-probability (correct preds):   {max_conf[correct_mask].mean():.4f}")
        if (~correct_mask).any():
            print(f"  mean max-probability (incorrect preds): {max_conf[~correct_mask].mean():.4f}")

        # --- Saved metrics for cross-reference ---------------------------
        _print_header("Saved signals_metrics.json (training-time numbers)")
        _print_saved_metrics()

        print("\nDone.\n", flush=True)


if __name__ == "__main__":
    main()
