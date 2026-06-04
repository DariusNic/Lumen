"""Tests for `app/services/fx_service.py` and the `/api/fx/convert` endpoint.

Frankfurter HTTP is always mocked — these tests must never reach the real API.
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.services import fx_service


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _frankfurter_response(rates: dict[str, float], date: str | None = None) -> dict:
    """Shape what the real Frankfurter `/v1/latest` returns.

    `date` defaults to today (UTC). That matters: the FX cache rejects rows
    older than `MAX_STALE_DAYS=7`, so a hardcoded historical date would make
    every subsequent `get_rate` re-fetch instead of reusing the cache.
    """
    if date is None:
        date = datetime.utcnow().date().isoformat()
    out = dict(rates)
    out.pop("EUR", None)  # the real API never echoes the self-rate
    return {"amount": 1.0, "base": "EUR", "date": date, "rates": out}


class _FakeResponse:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _patch_frankfurter(rates: dict[str, float], date: str | None = None):
    """Patch `requests.get` inside `fx_service` to return a canned response."""
    payload = _frankfurter_response(rates, date)
    return patch.object(fx_service.requests, "get", return_value=_FakeResponse(payload))


# ---------------------------------------------------------------------------
# Pure service: get_rate / convert
# ---------------------------------------------------------------------------

def test_get_rate_same_currency_is_one(client):
    """No HTTP call, no cache lookup — same currency short-circuits."""
    assert fx_service.get_rate("RON", "RON") == 1.0


def test_get_rate_eur_ron_uses_frankfurter(client):
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        rate = fx_service.get_rate("EUR", "RON")
    assert rate == pytest.approx(4.97)


def test_get_rate_cross_rate_derived_from_eur_base(client):
    """USD→RON should be derived as RON/USD from the EUR-based cache."""
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        rate = fx_service.get_rate("USD", "RON")
    assert rate == pytest.approx(4.97 / 1.08, rel=1e-6)


def test_convert_applies_rate(client):
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        out = fx_service.convert(100.0, "USD", "RON")
    assert out == pytest.approx(100.0 * (4.97 / 1.08), rel=1e-6)


def test_get_rate_unsupported_currency_rejected(client):
    with pytest.raises(Exception) as excinfo:
        fx_service.get_rate("RON", "JPY")
    assert "Unsupported" in str(excinfo.value) or "supported" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Cache: persistence + reuse + staleness
# ---------------------------------------------------------------------------

def test_rate_cached_after_first_fetch(client):
    """First call hits Frankfurter, second call reuses the cache."""
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}) as mocked:
        fx_service.get_rate("EUR", "RON")
        fx_service.get_rate("USD", "RON")
        fx_service.get_rate("RON", "USD")
    assert mocked.call_count == 1


def test_stale_cache_reused_within_seven_days(client):
    """If the live fetch fails, cache up to 7 days old still works."""
    from app.extensions import mongo

    # Seed a cache row 5 days back, then make Frankfurter unreachable.
    five_days_ago = datetime.utcnow() - timedelta(days=5)
    fx_service._write_cache(five_days_ago, {"USD": 1.08, "RON": 4.97, "EUR": 1.0})

    with patch.object(fx_service.requests, "get", side_effect=RuntimeError("network down")):
        rate = fx_service.get_rate("EUR", "RON")
    assert rate == pytest.approx(4.97)

    # Sanity — cache still only has the seeded row.
    rows = list(mongo.db["fx_rates"].find({}))
    assert len(rows) == 1


def test_stale_cache_older_than_seven_days_rejected(client):
    """If the only cache row is > 7 days old, the API call must reject."""
    eight_days_ago = datetime.utcnow() - timedelta(days=8)
    fx_service._write_cache(eight_days_ago, {"USD": 1.08, "RON": 4.97, "EUR": 1.0})

    from app.utils.errors import ValidationError
    with patch.object(fx_service.requests, "get", side_effect=RuntimeError("network down")):
        with pytest.raises(ValidationError) as excinfo:
            fx_service.get_rate("EUR", "RON")
    assert "stale" in excinfo.value.message.lower() or "stale" in str(excinfo.value.details)


# ---------------------------------------------------------------------------
# Transaction integration: amount_base is converted at insert time
# ---------------------------------------------------------------------------

def _register(client, currency="RON"):
    return client.post(
        "/api/auth/register",
        json={
            "email": "fx@example.com",
            "password": "password123",
            "full_name": "FX User",
            "base_currency": currency,
        },
    ).get_json()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_transaction_amount_base_converted_at_insert(client):
    """USD transaction on a RON base account stores `amount_base` in RON via FX."""
    body = _register(client, currency="RON")
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        res = client.post(
            "/api/transactions",
            json={
                "date": "2026-05-04T00:00:00",
                "amount": -100.0,
                "currency": "USD",
                "description": "AMZN PURCHASE",
            },
            headers=_auth(body["access_token"]),
        )
    assert res.status_code == 201
    tx = res.get_json()["transaction"]
    assert tx["amount"] == -100.0
    assert tx["currency"] == "USD"
    # USD→RON = 4.97/1.08 ≈ 4.6019
    expected = -100.0 * (4.97 / 1.08)
    assert tx["amount_base"] == pytest.approx(expected, rel=1e-4)


def test_transaction_same_currency_skips_fx(client):
    """RON transaction on a RON base account does NOT call Frankfurter."""
    body = _register(client, currency="RON")
    with patch.object(fx_service.requests, "get") as mocked:
        res = client.post(
            "/api/transactions",
            json={
                "date": "2026-05-04T00:00:00",
                "amount": -342.50,
                "currency": "RON",
                "description": "CARREFOUR",
            },
            headers=_auth(body["access_token"]),
        )
    assert res.status_code == 201
    assert res.get_json()["transaction"]["amount_base"] == -342.50
    mocked.assert_not_called()


# ---------------------------------------------------------------------------
# /api/fx/convert endpoint
# ---------------------------------------------------------------------------

def test_convert_endpoint_basic(client):
    body = _register(client)
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        res = client.get(
            "/api/fx/convert?from=USD&to=RON&amount=100",
            headers=_auth(body["access_token"]),
        )
    assert res.status_code == 200
    data = res.get_json()
    assert data["from"] == "USD"
    assert data["to"] == "RON"
    assert data["rate"] == pytest.approx(4.97 / 1.08, rel=1e-6)
    assert data["converted"] == pytest.approx(100 * (4.97 / 1.08), rel=1e-4)


def test_convert_endpoint_requires_auth(client):
    res = client.get("/api/fx/convert?from=USD&to=RON&amount=100")
    assert res.status_code == 401


def test_convert_endpoint_validates_inputs(client):
    body = _register(client)
    res = client.get("/api/fx/convert?from=USD", headers=_auth(body["access_token"]))
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Account totals — summed in base currency via FX
# ---------------------------------------------------------------------------

def test_base_currency_change_rewrites_amount_base(client):
    """When the user PATCHes /api/me with a new base_currency, every existing
    transaction's `amount_base` must be re-converted at its own date — otherwise
    the dashboard sums RON values under an EUR symbol."""
    body = _register(client, currency="RON")
    headers = _auth(body["access_token"])

    # Insert a few RON transactions while base=RON. amount_base should equal amount.
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        for desc, amt in [("Salary", 9400), ("Auchan", -300), ("Burger King", -60)]:
            res = client.post(
                "/api/transactions",
                json={
                    "date": "2026-05-04T00:00:00",
                    "amount": amt,
                    "currency": "RON",
                    "description": desc,
                },
                headers=headers,
            )
            assert res.status_code == 201

        before = client.get("/api/transactions", headers=headers).get_json()["transactions"]
        # Same currency as base → 1:1
        assert all(t["amount"] == t["amount_base"] for t in before)

        # Switch base to EUR. Backfill must re-convert via Frankfurter.
        res = client.patch("/api/me", json={"base_currency": "EUR"}, headers=headers)
        assert res.status_code == 200
        assert res.get_json()["user"]["base_currency"] == "EUR"

    after = client.get("/api/transactions", headers=headers).get_json()["transactions"]
    # RON→EUR rate (mocked rates['RON']=4.97, EUR base) → divide by 4.97.
    expected_rate = 1.0 / 4.97
    salary = next(t for t in after if t["description"] == "Salary")
    assert salary["amount"] == 9400.0  # native amount unchanged
    assert salary["amount_base"] == pytest.approx(9400.0 * expected_rate, rel=1e-3)


def test_base_currency_change_converts_monthly_budgets(client):
    """`categories.monthly_budget` has no currency stamp — it's implicit base.
    Switching base must convert every set budget at today's rate so a 600 EUR
    Groceries budget becomes ~2982 RON, not "RON 600"."""
    body = _register(client, currency="EUR")
    headers = _auth(body["access_token"])

    # Set a 600 EUR budget on Groceries while base=EUR.
    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    groceries = next(c for c in cats if c["name"] == "Groceries")
    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        client.patch(
            f"/api/categories/{groceries['id']}",
            json={"monthly_budget": 600},
            headers=headers,
        )

        # Switch base to RON. Conversion uses today's mocked rate (1 EUR = 4.97 RON).
        client.patch("/api/me", json={"base_currency": "RON"}, headers=headers)

    after = client.get("/api/categories", headers=headers).get_json()["categories"]
    groceries_after = next(c for c in after if c["id"] == groceries["id"])
    assert groceries_after["monthly_budget"] == pytest.approx(600 * 4.97, rel=1e-3)

    # Other categories with 0 budget are left alone.
    other = next(c for c in after if c["name"] == "Other")
    assert other["monthly_budget"] == 0


def test_base_currency_change_restamps_net_cashflow_account(client):
    """The auto-tracked Net cash flow account's currency must follow the user's
    base, otherwise totals() would convert it twice."""
    from app.extensions import mongo
    from bson import ObjectId

    body = _register(client, currency="RON")
    user_id = body["user"]["id"]

    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        client.patch("/api/me", json={"base_currency": "EUR"}, headers=_auth(body["access_token"]))

    net_cf = mongo.db["accounts"].find_one(
        {"user_id": ObjectId(user_id), "source_ref": "transactions:net"}
    )
    assert net_cf["currency"] == "EUR"


def test_base_currency_change_aborts_when_fx_unreachable(client):
    """If Frankfurter is unreachable AND no fresh cache exists, the base-currency
    PATCH must be refused — otherwise we'd corrupt amount_base for every tx."""
    body = _register(client, currency="RON")
    headers = _auth(body["access_token"])

    # No fx_rates cache exists. Simulate a network outage.
    with patch.object(fx_service.requests, "get", side_effect=RuntimeError("network down")):
        res = client.patch("/api/me", json={"base_currency": "EUR"}, headers=headers)

    assert res.status_code == 422
    body_json = res.get_json()
    assert "fx" in body_json["message"].lower() or "currency" in body_json["message"].lower()

    # User's base must be unchanged.
    me = client.get("/api/me", headers=headers).get_json()["user"]
    assert me["base_currency"] == "RON"


def test_ensure_rates_for_past_date_hits_historical_endpoint(client):
    """For a past date with no cached row, `_ensure_rates_for` must fetch the
    *historical* Frankfurter rate (e.g. `/v1/2026-04-08`), not blindly reuse
    today's rate. This is the bug that was silently using wrong rates for
    old transactions during the recompute pass."""
    seen_urls: list[str] = []

    def fake_get(url, **kw):
        seen_urls.append(url)
        date_str = url.rsplit("/", 1)[-1]
        if date_str == "latest":
            date_str = "2026-05-08"
        return _FakeResponse(_frankfurter_response({"USD": 1.08, "RON": 4.97}, date=date_str))

    with patch.object(fx_service.requests, "get", side_effect=fake_get):
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        fx_service._ensure_rates_for(thirty_days_ago)

    # At least one URL ending in a YYYY-MM-DD (not "latest") must have fired.
    historical_urls = [u for u in seen_urls if u.rsplit("/", 1)[-1] != "latest"]
    assert historical_urls, f"expected a historical-date URL, only saw: {seen_urls}"


def test_account_totals_converted_to_base(client):
    """A USD asset of $1000 + the auto-seeded Paper Portfolio ($10,000 cash)
    on a RON base user → totals.assets ≈ $11,000 × (4.97 / 1.08) ≈ 50,620 RON
    (using the mocked rate)."""
    body = _register(client)
    headers = _auth(body["access_token"])

    with _patch_frankfurter({"USD": 1.08, "RON": 4.97}):
        # Add a USD savings account on top of the auto-seeded accounts.
        client.post(
            "/api/accounts",
            json={"name": "US bank", "type": "savings", "balance": 1000, "currency": "USD"},
            headers=headers,
        )
        totals = client.get("/api/accounts", headers=headers).get_json()["totals"]

    assert totals["base_currency"] == "RON"
    # Cash (0 RON) + Paper Portfolio ($10k USD) + Net cash flow (0 RON) + US bank ($1k USD).
    expected_usd_in_ron = 11_000 * (4.97 / 1.08)
    assert totals["assets"] == pytest.approx(expected_usd_in_ron, rel=1e-3)
    assert totals["liabilities"] == 0
    assert totals["mixed_currency"] is False
