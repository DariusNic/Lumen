"""Tests for the ML stage of the categorization cascade.

We don't retrain inside the test suite (slow + nondeterministic). Instead we
build a tiny in-memory pipeline, monkey-patch it into `predict._MODEL`, and
verify the cascade behavior:

- rules win when they match,
- ML wins when no rule matches AND confidence ≥ threshold,
- fallback wins when confidence < threshold.
"""
from __future__ import annotations

import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.ml.categorization import predict


@pytest.fixture(autouse=True)
def _restore_model_cache():
    """Each test gets a clean cache. The previous test's monkey-patched model
    must not leak into the next."""
    yield
    predict.reset_model_cache()


def _make_tiny_model() -> Pipeline:
    """Train a 3-class pipeline on a handful of examples so `predict_proba`
    behaves like the real one. Pure sklearn, no joblib I/O."""
    x = [
        "annabella magazin mixt",
        "shopmagazin promenada",
        "diana express pipera",
        "freshmarket vitan",
        "magazin alimentar local",
        "tucanocoffee downtown",
        "bistro origo cluj",
        "trattoria buongiorno",
        "cafenea fixa",
        "patiserie boulangerie",
        "asociatia proprietari bloc 5",
        "asociatie locatari b12",
        "intretinere casa luna mai",
        "chirie luna iunie",
        "plata chirie apartament",
    ]
    y = [
        "Groceries", "Groceries", "Groceries", "Groceries", "Groceries",
        "Restaurants", "Restaurants", "Restaurants", "Restaurants", "Restaurants",
        "Housing", "Housing", "Housing", "Housing", "Housing",
    ]
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
        ("clf", LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000, random_state=42)),
    ])
    pipe.fit(x, y)
    return pipe


def _install(model) -> None:
    """Bypass joblib loading; force `_MODEL` to the given pipeline."""
    predict._MODEL = model
    predict._MODEL_LOAD_FAILED = False


# ---------------------------------------------------------------------------

def test_rules_take_precedence_over_ml():
    """Even when the ML model would predict differently, a rule hit short-
    circuits the cascade. (Cascade order is fixed.)"""
    _install(_make_tiny_model())
    # "Carrefour" is a rule → Groceries. The ML model never sees this string.
    assert predict.categorize("CARREFOUR Promenada") == "Groceries"


def test_ml_classifies_novel_grocery_merchant():
    """A description not covered by any rule, but matching a Groceries cluster
    in the model, comes back as Groceries via the ML stage."""
    _install(_make_tiny_model())
    assert predict.categorize("Annabella Magazin Vitan") == "Groceries"


def test_ml_classifies_novel_restaurant_merchant():
    """A description close to Restaurants training rows (no rule hit) is
    routed to Restaurants by the ML stage."""
    _install(_make_tiny_model())
    assert predict.categorize("Bistro Origo new branch") == "Restaurants"


def test_low_confidence_falls_back_to_other(monkeypatch):
    """When the model's top-class probability is below the 0.65 threshold,
    the cascade returns "Other" rather than picking up a weak signal."""
    pipe = _make_tiny_model()
    _install(pipe)

    # Pick a description the tiny model can't confidently classify and verify
    # the cascade falls through. We force this by raising the threshold above
    # any realistic prediction — same effect as the model being unsure.
    monkeypatch.setattr(predict, "ML_CONFIDENCE_THRESHOLD", 0.999)
    assert predict.categorize("totally novel merchant qzz xyz") == "Other"


def test_missing_artifact_degrades_to_rules_only(monkeypatch, tmp_path):
    """If the joblib artifact doesn't exist, the cascade still works — it
    just skips the ML stage. (Important for fresh checkouts and CI.)"""
    monkeypatch.setattr(predict, "_MODEL_PATH", tmp_path / "nope.joblib")
    predict.reset_model_cache()

    # Rules still win.
    assert predict.categorize("CARREFOUR PMT") == "Groceries"
    # No rule + no model → fallback.
    assert predict.categorize("totally novel merchant qzz xyz") == "Other"


def test_ml_predicting_other_falls_through_to_fallback():
    """If the ML model itself predicts "Other" with high confidence, we still
    return the fallback (rather than declaring an ML hit). Keeps the contract
    that `_ml_predict` only returns *positive* category hits."""
    class FakeModel:
        classes_ = ["Groceries", "Other"]
        def predict_proba(self, _xs):
            return [[0.10, 0.90]]
    _install(FakeModel())
    assert predict.categorize("anything") == "Other"


def test_empty_description_returns_other():
    """No-rule + empty input → fallback, regardless of ML state."""
    _install(_make_tiny_model())
    assert predict.categorize("") == "Other"


def test_correction_logged_when_user_recategorizes(client):
    """When a user manually re-categorizes a transaction, the (description,
    chosen_category) pair is logged into the `corrections` collection so a
    future retrain has fresh feedback."""
    from app.extensions import mongo

    body = client.post("/api/auth/register", json={
        "email": "ml@example.com", "password": "password123",
        "full_name": "ML User", "base_currency": "RON",
    }).get_json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    # Insert a transaction the rules will catch as Groceries.
    tx = client.post("/api/transactions", json={
        "date": "2026-05-04T00:00:00", "amount": -50, "currency": "RON",
        "description": "CARREFOUR Promenada",
    }, headers=headers).get_json()["transaction"]
    assert tx["category_name"] == "Groceries"

    # User decides this one was actually a Restaurants charge. PATCH the
    # category and verify the correction was logged.
    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    restaurants_id = next(c["id"] for c in cats if c["name"] == "Restaurants")
    client.patch(f"/api/transactions/{tx['id']}",
                 json={"category_id": restaurants_id}, headers=headers)

    rows = list(mongo.db["corrections"].find({}))
    assert len(rows) == 1
    assert rows[0]["description"] == "CARREFOUR Promenada"
    assert rows[0]["chosen_category"] == "Restaurants"
