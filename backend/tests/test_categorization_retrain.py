"""Tests for the corrections → retrain feedback loop.

`train_and_evaluate(include_corrections=True)` is end-to-end heavy (full
TF-IDF fit on the seed corpus, joblib write), so we don't run it here. The
unit under test is the surface that touches Mongo: `load_corrections()`
read-and-dedup behavior.
"""
from app.extensions import mongo
from app.ml.categorization.train_tfidf_lr import load_corrections
from app.models.user import utcnow


def test_load_corrections_empty_collection_returns_empty(app):
    descs, labels = load_corrections()
    assert descs == []
    assert labels == []


def test_load_corrections_returns_inserted_rows(app):
    now = utcnow()
    mongo.db["corrections"].insert_many([
        {"user_id": None, "description": "Burger King meal",
         "chosen_category": "Restaurants", "created_at": now},
        {"user_id": None, "description": "Curatatorie centrul vechi",
         "chosen_category": "Other", "created_at": now},
    ])
    descs, labels = load_corrections()
    assert sorted(descs) == ["Burger King meal", "Curatatorie centrul vechi"]
    assert sorted(labels) == ["Other", "Restaurants"]


def test_load_corrections_deduplicates_by_description_and_category(app):
    """A user who re-categorizes the same (desc → category) ten times shouldn't
    pump that example into the training set ten times. Dedup happens on a
    casefolded `(description, category)` pair so capitalization drift between
    repeated corrections still collapses."""
    now = utcnow()
    mongo.db["corrections"].insert_many([
        {"user_id": None, "description": "Burger King meal",
         "chosen_category": "Restaurants", "created_at": now},
        {"user_id": None, "description": "Burger King meal",
         "chosen_category": "Restaurants", "created_at": now},
        {"user_id": None, "description": "BURGER KING MEAL",
         "chosen_category": "Restaurants", "created_at": now},
        # Different chosen_category → kept as a distinct training example
        # (the user changed their mind, both signals matter to the model).
        {"user_id": None, "description": "Burger King meal",
         "chosen_category": "Other", "created_at": now},
    ])
    descs, labels = load_corrections()
    # 2 unique (description.casefold(), category) pairs after dedup —
    # ('burger king meal', 'Restaurants') and ('burger king meal', 'Other').
    assert len(descs) == 2
    assert len(labels) == 2
    pairs = sorted(zip(descs, labels))
    assert pairs[0][1] in {"Other", "Restaurants"}
    assert pairs[1][1] in {"Other", "Restaurants"}
    assert pairs[0][1] != pairs[1][1]


def test_load_corrections_skips_rows_with_missing_fields(app):
    now = utcnow()
    mongo.db["corrections"].insert_many([
        {"description": "", "chosen_category": "Restaurants", "created_at": now},
        {"description": "Some desc", "chosen_category": "", "created_at": now},
        {"description": "Valid one", "chosen_category": "Restaurants", "created_at": now},
    ])
    descs, labels = load_corrections()
    assert descs == ["Valid one"]
    assert labels == ["Restaurants"]
