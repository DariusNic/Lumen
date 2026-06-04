"""Train the second stage of the categorization cascade.

Stack (locked):
    TF-IDF vectorizer with `analyzer='char_wb'`, `ngram_range=(3, 5)` →
    LogisticRegression multi-class, balanced class weights.

Char-level TF-IDF was chosen over word-level so the model handles the noisy
shape of bank-statement descriptions ("CARRFR BANEAS" or "carfr*pos") that
word tokenizers fragment. Romanian merchants are first-class — the corpus
mixes RO + EN at roughly 60/40 to match the user base.

Run from `backend/`:
    python -m app.ml.categorization.train_tfidf_lr

Outputs:
    ml_models/v1/tfidf_lr.joblib   — full pipeline (vectorizer + LR)
    ml_models/v1/metrics.json      — accuracy, macro-F1, per-category report,
                                      train/val sizes, hyperparameters

The cascade in `predict.py` lazy-loads the joblib at first use. Re-running
this script overwrites both files.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

# --- paths --------------------------------------------------------------

_HERE = Path(__file__).resolve()
CORPUS_PATH = _HERE.parent / "data" / "seed_corpus.csv"
MODEL_DIR = _HERE.parents[3] / "ml_models" / "v1"
MODEL_PATH = MODEL_DIR / "tfidf_lr.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"

# --- hyperparameters (locked — change with sign-off) ---

NGRAM_RANGE = (3, 5)
MIN_DF = 2          # ignore character n-grams seen in fewer than 2 rows
MAX_DF = 0.95       # ignore n-grams in > 95% of rows (truly generic shapes)
LR_C = 4.0          # regularization strength — looser fits this small dataset
RANDOM_STATE = 20260508
TEST_SIZE = 0.2     # 80 / 20 stratified split — tiny corpus, no validation set


def load_corpus(path: Path = CORPUS_PATH) -> tuple[list[str], list[str]]:
    """Read `seed_corpus.csv` into (descriptions, labels)."""
    if not path.exists():
        raise FileNotFoundError(
            f"Seed corpus not found at {path}. Run "
            f"`python -m scripts.build_seed_corpus` first."
        )
    descriptions: list[str] = []
    labels: list[str] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            descriptions.append(row["description"])
            labels.append(row["category"])
    return descriptions, labels


def load_corrections() -> tuple[list[str], list[str]]:
    """Pull `(description, chosen_category)` pairs from the `corrections`
    collection. Dedup on `(description.casefold(), category)` so a user who
    re-categorizes the same row five times doesn't disproportionately weight
    that example.

    Returns `([], [])` cleanly when the collection is empty OR the app
    context isn't available (so the CLI entrypoint and the test suite work
    without a live Mongo handle).
    """
    try:
        from app.extensions import mongo
        cursor = mongo.db["corrections"].find({}, {"description": 1, "chosen_category": 1})
    except Exception:  # noqa: BLE001 — no app context, no Mongo, no corrections
        return [], []

    seen: set[tuple[str, str]] = set()
    descriptions: list[str] = []
    labels: list[str] = []
    for row in cursor:
        desc = (row.get("description") or "").strip()
        label = (row.get("chosen_category") or "").strip()
        if not desc or not label:
            continue
        key = (desc.casefold(), label)
        if key in seen:
            continue
        seen.add(key)
        descriptions.append(desc)
        labels.append(label)
    return descriptions, labels


def build_pipeline() -> Pipeline:
    """The single sklearn Pipeline: TF-IDF char_wb (3, 5) → LogisticRegression."""
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=NGRAM_RANGE,
                    min_df=MIN_DF,
                    max_df=MAX_DF,
                    lowercase=True,
                    sublinear_tf=True,
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    C=LR_C,
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def train_and_evaluate(include_corrections: bool = False) -> dict[str, Any]:
    """Train + persist the cascade-stage model.

    `include_corrections=True` concatenates the seed corpus with the user
    feedback stored in the `corrections` Mongo collection. This is the path
    the daily retrain cron uses. The CLI entrypoint defaults to False so a
    `python -m app.ml.categorization.train_tfidf_lr` run remains
    deterministic and reproducible without a live database.
    """
    seed_desc, seed_labels = load_corpus()
    corr_desc: list[str] = []
    corr_labels: list[str] = []
    if include_corrections:
        corr_desc, corr_labels = load_corrections()

    descriptions = seed_desc + corr_desc
    labels = seed_labels + corr_labels

    x_train, x_test, y_train, y_test = train_test_split(
        descriptions,
        labels,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=labels,
    )

    pipe = build_pipeline()
    pipe.fit(x_train, y_train)
    accuracy = float(pipe.score(x_test, y_test))
    y_pred = pipe.predict(x_test)
    report_dict = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    macro_f1 = float(report_dict["macro avg"]["f1-score"])

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, MODEL_PATH)

    metrics = {
        "model": "tfidf_lr",
        "version": "v1",
        "trained_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "corpus": {
            "path": str(CORPUS_PATH.relative_to(_HERE.parents[2])),
            "rows_total": len(descriptions),
            "rows_seed": len(seed_desc),
            "rows_corrections": len(corr_desc),
            "rows_train": len(x_train),
            "rows_test": len(x_test),
            "categories": sorted(set(labels)),
        },
        "hyperparameters": {
            "vectorizer": {
                "analyzer": "char_wb",
                "ngram_range": list(NGRAM_RANGE),
                "min_df": MIN_DF,
                "max_df": MAX_DF,
                "sublinear_tf": True,
            },
            "classifier": {
                "type": "LogisticRegression",
                "C": LR_C,
                "class_weight": "balanced",
                "max_iter": 2000,
            },
            "split": {"test_size": TEST_SIZE, "stratify": True},
            "random_state": RANDOM_STATE,
        },
        "metrics": {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "per_category": {
                cat: {
                    "precision": float(stats["precision"]),
                    "recall": float(stats["recall"]),
                    "f1": float(stats["f1-score"]),
                    "support": int(stats["support"]),
                }
                for cat, stats in report_dict.items()
                if cat not in ("accuracy", "macro avg", "weighted avg")
            },
        },
    }
    with METRICS_PATH.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def main() -> None:
    metrics = train_and_evaluate()
    m = metrics["metrics"]
    print(f"Trained tfidf_lr on {metrics['corpus']['rows_total']} rows")
    print(f"  accuracy:  {m['accuracy']:.4f}")
    print(f"  macro F1:  {m['macro_f1']:.4f}")
    print(f"  artifact:  {MODEL_PATH}")
    print(f"  metrics:   {METRICS_PATH}")


if __name__ == "__main__":
    main()
