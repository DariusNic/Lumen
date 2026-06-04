"""Train the XGBoost stock-signal classifier.

Stack and protocol (do not change without sign-off):
  - **No shuffling.** Chronological split on transaction date.
  - **No future leakage.** Features already enforce this; labeling drops
    the last 5 rows per ticker.
  - **Per-ticker integrity.** `compute_features_universe` already groups.
  - **Class weighting via sample_weight** — XGBoost's sklearn API doesn't
    accept `class_weight`, so we compute inverse-frequency weights from
    the training labels.

Splits (locked dates):
  - **Train:** date < 2023-07-01     (2019-01-02 -> 2023-06-30)
  - **Val:**   2023-07-01 -> 2023-12-31  (used for early stopping)
  - **Test:**  date ≥ 2024-01-01     (held out, only touched at final eval)

Hyperparameters (signed off in the Week 5 outline):
  n_estimators=400, max_depth=5, learning_rate=0.05,
  subsample=0.8, colsample_bytree=0.8, min_child_weight=4,
  reg_lambda=1.0, random_state=20260508, early_stopping_rounds=30.

Run from `backend/`:
    python -u -m app.ml.signals.train_xgb

Outputs (overwritten on every run):
  - `ml_models/v1/xgb_classifier.joblib` — fitted Booster wrapper
  - `ml_models/v1/signals_metrics.json` — accuracy / F1 / Sharpe by split,
    feature list, hyperparameters, train/val/test row counts. The signal
    endpoint reads from this file at request time.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from xgboost import XGBClassifier

from app import create_app
from app.ml.signals.features import FEATURE_COLUMNS, compute_features_universe
from app.ml.signals.labels import HORIZON_DAYS, INT_TO_LABEL, LABEL_TO_INT, attach_labels, label_distribution
from app.utils.constants import TICKERS

log = logging.getLogger(__name__)

# --- Paths ------------------------------------------------------------------

_HERE = Path(__file__).resolve()
MODEL_DIR = _HERE.parents[3] / "ml_models" / "v1"
MODEL_PATH = MODEL_DIR / "xgb_classifier.joblib"
METRICS_PATH = MODEL_DIR / "signals_metrics.json"

# --- Locked dates -------------------------------------------

TRAIN_END = pd.Timestamp("2023-07-01")
VAL_END = pd.Timestamp("2024-01-01")

# --- Locked hyperparameters ------------------------------------------------

XGB_PARAMS: dict[str, Any] = {
    "objective": "multi:softprob",
    "num_class": 3,
    "n_estimators": 400,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 4,
    "reg_lambda": 1.0,
    "random_state": 20260508,
    "early_stopping_rounds": 30,
    "eval_metric": "mlogloss",
    "tree_method": "hist",
}


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------

def load_labeled_dataset(tickers: list[str] | None = None) -> pd.DataFrame:
    """Compute features + labels for the full universe, sorted by date."""
    tickers = tickers or list(TICKERS)
    feats = compute_features_universe(tickers)
    if feats.empty:
        raise RuntimeError(
            "No features produced — `stock_data` is empty. "
            "Run `python -m scripts.seed_stock_data` first."
        )
    labeled = attach_labels(feats)
    # `attach_labels` preserves the original index (date). Promote to a real
    # column so the chronological filter is straightforward and the JSON
    # report can include row-count breakdowns by date.
    labeled = labeled.reset_index().rename(columns={"index": "date"})
    if "date" not in labeled.columns:
        # Fallback for older pandas where the index name was 'date'.
        labeled["date"] = labeled.iloc[:, 0]
    labeled["date"] = pd.to_datetime(labeled["date"])
    labeled = labeled.sort_values(["date", "ticker"]).reset_index(drop=True)
    return labeled


def chronological_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train = df[df["date"] < TRAIN_END].copy()
    val = df[(df["date"] >= TRAIN_END) & (df["date"] < VAL_END)].copy()
    test = df[df["date"] >= VAL_END].copy()
    return train, val, test


# ---------------------------------------------------------------------------
# Sample weights — inverse class frequency on the training set
# ---------------------------------------------------------------------------

def _compute_sample_weights(y: np.ndarray) -> np.ndarray:
    """Return per-row weights inversely proportional to class frequency.
    Ensures BUY/SELL aren't drowned by HOLD without changing the loss
    function itself."""
    classes, counts = np.unique(y, return_counts=True)
    weights_for = {c: float(len(y)) / (len(classes) * cnt) for c, cnt in zip(classes, counts)}
    return np.array([weights_for[c] for c in y], dtype=float)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _strategy_sharpe(pred_labels: list[str], forward_returns: np.ndarray) -> float:
    """Annualized Sharpe of a simple BUY-long / SELL-short / HOLD-flat
    strategy on the held-out window.

    Per-row signed return: BUY -> +ret, SELL -> -ret, HOLD -> 0.
    Then Sharpe = mean / std × √(252 / HORIZON_DAYS).

    Caveats (documented in Chapter 5): zero transaction costs, overlapping
    HORIZON_DAYS-day windows treated as i.i.d. — overstates real-world
    performance.
    """
    signed = np.array([
        ret if lab == "BUY" else (-ret if lab == "SELL" else 0.0)
        for lab, ret in zip(pred_labels, forward_returns)
    ])
    if signed.std() == 0 or len(signed) == 0:
        return 0.0
    return float(signed.mean() / signed.std() * np.sqrt(252.0 / HORIZON_DAYS))


def evaluate(model: XGBClassifier, df: pd.DataFrame, *, split_name: str) -> dict[str, Any]:
    if df.empty:
        return {"split": split_name, "rows": 0}
    x = df[list(FEATURE_COLUMNS)]
    y_true = df["label"].map(LABEL_TO_INT).to_numpy()
    y_pred = model.predict(x)
    pred_labels = [INT_TO_LABEL[int(p)] for p in y_pred]

    report = classification_report(
        y_true, y_pred, output_dict=True, zero_division=0,
        labels=[0, 1, 2],
        target_names=["SELL", "HOLD", "BUY"],
    )

    return {
        "split": split_name,
        "rows": int(len(df)),
        "date_from": df["date"].min().isoformat(),
        "date_to": df["date"].max().isoformat(),
        "label_distribution": label_distribution(df["label"]),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "sharpe": _strategy_sharpe(pred_labels, df["forward_return"].to_numpy()),
        "per_class": {
            cls: {
                "precision": float(report[cls]["precision"]),
                "recall": float(report[cls]["recall"]),
                "f1": float(report[cls]["f1-score"]),
                "support": int(report[cls]["support"]),
            }
            for cls in ("SELL", "HOLD", "BUY")
        },
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def fit(train: pd.DataFrame, val: pd.DataFrame) -> XGBClassifier:
    x_train = train[list(FEATURE_COLUMNS)]
    y_train = train["label"].map(LABEL_TO_INT).to_numpy()
    x_val = val[list(FEATURE_COLUMNS)]
    y_val = val["label"].map(LABEL_TO_INT).to_numpy()

    sample_weight = _compute_sample_weights(y_train)
    model = XGBClassifier(**XGB_PARAMS)
    model.fit(
        x_train, y_train,
        sample_weight=sample_weight,
        eval_set=[(x_val, y_val)],
        verbose=False,
    )
    return model


def main() -> None:
    app = create_app()
    with app.app_context():
        print("Loading dataset…", flush=True)
        df = load_labeled_dataset()
        print(f"  {len(df):,} labeled rows · {df['ticker'].nunique()} tickers", flush=True)

        train, val, test = chronological_split(df)
        print(f"\nSplit:", flush=True)
        print(f"  train:      {len(train):>7,}  ({train['date'].min().date()} -> {train['date'].max().date()})", flush=True)
        print(f"  validation: {len(val):>7,}  ({val['date'].min().date()} -> {val['date'].max().date()})", flush=True)
        print(f"  test:       {len(test):>7,}  ({test['date'].min().date()} -> {test['date'].max().date()})", flush=True)

        print("\nTraining…", flush=True)
        model = fit(train, val)
        best_iter = int(getattr(model, "best_iteration", model.n_estimators) or model.n_estimators)
        print(f"  fit complete · best_iteration={best_iter} (of {XGB_PARAMS['n_estimators']})", flush=True)

        print("\nEvaluating…", flush=True)
        train_metrics = evaluate(model, train, split_name="train")
        val_metrics = evaluate(model, val, split_name="validation")
        test_metrics = evaluate(model, test, split_name="test")

        for m in (train_metrics, val_metrics, test_metrics):
            print(f"  {m['split']:<11s} acc={m['accuracy']:.4f}  F1={m['macro_f1']:.4f}  "
                  f"Sharpe={m['sharpe']:>+.2f}", flush=True)

        # Write artifact + metrics
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, MODEL_PATH)

        report = {
            "model": "xgb_classifier",
            "version": "v1",
            "trained_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "tickers": list(TICKERS),
            "feature_columns": list(FEATURE_COLUMNS),
            "label_to_int": LABEL_TO_INT,
            "hyperparameters": XGB_PARAMS,
            "split_dates": {
                "train_end": TRAIN_END.isoformat(),
                "val_end": VAL_END.isoformat(),
            },
            "best_iteration": best_iter,
            "splits": {
                "train": train_metrics,
                "validation": val_metrics,
                "test": test_metrics,
            },
        }
        with METRICS_PATH.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"\nArtifact: {MODEL_PATH}", flush=True)
        print(f"Metrics:  {METRICS_PATH}", flush=True)


if __name__ == "__main__":
    main()
