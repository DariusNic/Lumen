"""Honest evaluation of the categorization cascade.

The training script reports accuracy on a *random* 80/20 split of the seed
corpus. That metric is optimistic because train and test share merchants —
the model just has to recognize "Carrefour" again under different decoration.
This script runs three complementary protocols to present a defensible
picture of model performance:

1. **Random split** (stratified 80/20) — the optimistic upper bound. Same
   protocol as `train_tfidf_lr.py`. Useful as a sanity check that the model
   trained correctly.

2. **Merchant holdout** (StratifiedGroupKFold, K=5) — the honest number. The
   same merchant never appears in both train and test for a given fold. Each
   fold trains on K-1 merchant groups per category and tests on the held-out
   group. We aggregate predictions across folds for an overall accuracy and
   per-category F1, plus mean +/- std across folds.

3. **Rule coverage** — independent of the ML stage. For every row in the
   corpus, what percentage is matched by `categorize_by_rules` (correctly,
   wrongly, or not at all)? Tells us how much work the rules already do
   and how much the ML stage actually has to carry.

Run from `backend/`:
    python -m scripts.eval_categorization

Output: `ml_models/v1/eval_report.json`. Designed to feed straight into the
Chapter 3 evaluation table — every number cited there comes from this file.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedGroupKFold, train_test_split

from app.ml.categorization.rules import categorize_by_rules
from app.ml.categorization.train_tfidf_lr import (
    CORPUS_PATH,
    RANDOM_STATE,
    TEST_SIZE,
    build_pipeline,
)

# CORPUS_PATH is backend/app/ml/categorization/data/seed_corpus.csv → parents[4] = backend/.
# We co-locate the eval report next to metrics.json under ml_models/v1/.
REPORT_PATH = CORPUS_PATH.parents[4] / "ml_models" / "v1" / "eval_report.json"
N_FOLDS = 5


# ---------------------------------------------------------------------------
# Corpus loading (with merchant_base)
# ---------------------------------------------------------------------------

def _load_corpus_with_groups() -> tuple[list[str], list[str], list[str]]:
    descriptions: list[str] = []
    labels: list[str] = []
    groups: list[str] = []
    with CORPUS_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            descriptions.append(row["description"])
            labels.append(row["category"])
            groups.append(row.get("merchant_base") or row["description"])
    return descriptions, labels, groups


# ---------------------------------------------------------------------------
# Protocol 1: random stratified split
# ---------------------------------------------------------------------------

def eval_random_split(x: list[str], y: list[str]) -> dict[str, Any]:
    x_train, x_test, y_train, y_test = train_test_split(
        x, y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,
    )
    pipe = build_pipeline()
    pipe.fit(x_train, y_train)
    y_pred = pipe.predict(x_test)
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    return {
        "protocol": "random_split_80_20_stratified",
        "rows_train": len(x_train),
        "rows_test": len(x_test),
        "accuracy": float(report["accuracy"]),
        "macro_f1": float(report["macro avg"]["f1-score"]),
        "per_category": _per_category(report),
    }


# ---------------------------------------------------------------------------
# Protocol 2: merchant holdout (StratifiedGroupKFold)
# ---------------------------------------------------------------------------

def eval_merchant_holdout(x: list[str], y: list[str], groups: list[str]) -> dict[str, Any]:
    cv = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)

    fold_accuracies: list[float] = []
    fold_macro_f1s: list[float] = []
    # Aggregate predictions across all folds (each row tested exactly once)
    # so we can produce a single per-category report.
    all_y_true: list[str] = []
    all_y_pred: list[str] = []
    train_merchants_per_fold: list[int] = []
    test_merchants_per_fold: list[int] = []

    for fold_idx, (train_idx, test_idx) in enumerate(cv.split(x, y, groups=groups)):
        x_tr = [x[i] for i in train_idx]
        y_tr = [y[i] for i in train_idx]
        x_te = [x[i] for i in test_idx]
        y_te = [y[i] for i in test_idx]
        train_merchants_per_fold.append(len({groups[i] for i in train_idx}))
        test_merchants_per_fold.append(len({groups[i] for i in test_idx}))

        pipe = build_pipeline()
        pipe.fit(x_tr, y_tr)
        y_pred = pipe.predict(x_te)

        report = classification_report(y_te, y_pred, output_dict=True, zero_division=0)
        fold_accuracies.append(float(report["accuracy"]))
        fold_macro_f1s.append(float(report["macro avg"]["f1-score"]))

        all_y_true.extend(y_te)
        all_y_pred.extend(y_pred)

    overall_report = classification_report(all_y_true, all_y_pred, output_dict=True, zero_division=0)
    return {
        "protocol": "merchant_holdout_stratified_group_kfold",
        "n_folds": N_FOLDS,
        "rows_evaluated": len(all_y_true),
        "train_merchants_per_fold_mean": statistics.mean(train_merchants_per_fold),
        "test_merchants_per_fold_mean": statistics.mean(test_merchants_per_fold),
        "fold_accuracy_mean": statistics.mean(fold_accuracies),
        "fold_accuracy_std": statistics.stdev(fold_accuracies) if len(fold_accuracies) > 1 else 0.0,
        "fold_macro_f1_mean": statistics.mean(fold_macro_f1s),
        "fold_macro_f1_std": statistics.stdev(fold_macro_f1s) if len(fold_macro_f1s) > 1 else 0.0,
        "aggregated_accuracy": float(overall_report["accuracy"]),
        "aggregated_macro_f1": float(overall_report["macro avg"]["f1-score"]),
        "per_category": _per_category(overall_report),
    }


# ---------------------------------------------------------------------------
# Protocol 3: rule coverage
# ---------------------------------------------------------------------------

def eval_rule_coverage(x: list[str], y: list[str]) -> dict[str, Any]:
    """How much of the corpus do the regex rules already catch (correctly or
    wrongly), and how much falls through to the ML stage? Cascade math:

      total = matched_correct + matched_wrong + unmatched
      cascade_handles_via_rules     = matched_correct
      cascade_passes_to_ml          = matched_wrong + unmatched
      (matched_wrong is always overridden — we trust rules over ML, so a
       wrong rule hit can't be fixed downstream and is a true cascade error)

    Per-category coverage tells us which categories the rules already nail
    and which lean on the ML stage.
    """
    matched_correct = 0
    matched_wrong = 0
    unmatched = 0
    by_category: dict[str, dict[str, int]] = defaultdict(
        lambda: {"matched_correct": 0, "matched_wrong": 0, "unmatched": 0}
    )

    for desc, true_label in zip(x, y):
        rule_label = categorize_by_rules(desc)
        if rule_label is None:
            unmatched += 1
            by_category[true_label]["unmatched"] += 1
        elif rule_label == true_label:
            matched_correct += 1
            by_category[true_label]["matched_correct"] += 1
        else:
            matched_wrong += 1
            by_category[true_label]["matched_wrong"] += 1

    total = len(x)
    return {
        "protocol": "rule_coverage",
        "total_rows": total,
        "matched_correct": matched_correct,
        "matched_wrong": matched_wrong,
        "unmatched": unmatched,
        "rule_correct_pct": round(matched_correct / total * 100, 2),
        "rule_wrong_pct": round(matched_wrong / total * 100, 2),
        "passes_to_ml_pct": round(unmatched / total * 100, 2),
        "per_category": {
            cat: {
                "rows": sum(stats.values()),
                "matched_correct_pct": round(stats["matched_correct"] / max(sum(stats.values()), 1) * 100, 2),
                "matched_wrong_pct": round(stats["matched_wrong"] / max(sum(stats.values()), 1) * 100, 2),
                "unmatched_pct": round(stats["unmatched"] / max(sum(stats.values()), 1) * 100, 2),
            }
            for cat, stats in sorted(by_category.items())
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _per_category(report: dict[str, Any]) -> dict[str, dict[str, float]]:
    return {
        cat: {
            "precision": float(stats["precision"]),
            "recall": float(stats["recall"]),
            "f1": float(stats["f1-score"]),
            "support": int(stats["support"]),
        }
        for cat, stats in report.items()
        if cat not in ("accuracy", "macro avg", "weighted avg")
    }


def _print_summary(report: dict[str, Any]) -> None:
    print("=" * 76)
    print("CATEGORIZATION EVAL — three protocols")
    print("=" * 76)

    rs = report["random_split"]
    print("\n[1] Random 80/20 stratified split (optimistic — leaks merchants)")
    print(f"    accuracy: {rs['accuracy']:.4f}    macro-F1: {rs['macro_f1']:.4f}")
    print(f"    rows train/test: {rs['rows_train']}/{rs['rows_test']}")

    mh = report["merchant_holdout"]
    print("\n[2] Merchant holdout (StratifiedGroupKFold, K=5) — honest number")
    print(f"    fold accuracy: {mh['fold_accuracy_mean']:.4f} +/- {mh['fold_accuracy_std']:.4f}")
    print(f"    fold macro-F1: {mh['fold_macro_f1_mean']:.4f} +/- {mh['fold_macro_f1_std']:.4f}")
    print(f"    aggregated accuracy: {mh['aggregated_accuracy']:.4f}")
    print(f"    aggregated macro-F1: {mh['aggregated_macro_f1']:.4f}")
    print(f"    train/test merchants per fold: "
          f"{mh['train_merchants_per_fold_mean']:.1f} / {mh['test_merchants_per_fold_mean']:.1f}")

    rc = report["rule_coverage"]
    print("\n[3] Rule coverage (no ML — rules-only)")
    print(f"    correct: {rc['rule_correct_pct']:.1f}%   "
          f"wrong: {rc['rule_wrong_pct']:.1f}%   "
          f"unmatched (-> ML): {rc['passes_to_ml_pct']:.1f}%")

    print("\nPer-category macro-F1 under merchant holdout:")
    for cat, stats in sorted(mh["per_category"].items(), key=lambda kv: -kv[1]["f1"]):
        bar = "#" * int(stats["f1"] * 20)
        print(f"  {cat:14s}  F1={stats['f1']:.3f}  P={stats['precision']:.3f}  "
              f"R={stats['recall']:.3f}  n={stats['support']:4d}  {bar}")

    print(f"\nFull report: {REPORT_PATH}")


def main() -> None:
    descriptions, labels, groups = _load_corpus_with_groups()

    report: dict[str, Any] = {
        "evaluated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        "corpus": {
            "path": str(CORPUS_PATH.relative_to(CORPUS_PATH.parents[3])),
            "rows": len(descriptions),
            "categories": sorted(set(labels)),
            "merchants_total": len(set(groups)),
        },
        "random_split": eval_random_split(descriptions, labels),
        "merchant_holdout": eval_merchant_holdout(descriptions, labels, groups),
        "rule_coverage": eval_rule_coverage(descriptions, labels),
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    _print_summary(report)


if __name__ == "__main__":
    main()
