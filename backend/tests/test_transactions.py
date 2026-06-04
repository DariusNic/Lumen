def _register(client, email="ana@example.com", currency="RON"):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Ana Popescu",
            "base_currency": currency,
        },
    ).get_json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create(client, token, **overrides):
    payload = {
        "date": "2026-05-04T00:00:00",
        "amount": -342.50,
        "currency": "RON",
        "description": "CARREFOUR BANEASA",
    }
    payload.update(overrides)
    return client.post("/api/transactions", json=payload, headers=_auth(token))


# ---- create ---------------------------------------------------------------

def test_create_auto_categorizes_via_rules(client):
    body = _register(client)
    res = _create(client, body["access_token"])
    assert res.status_code == 201
    tx = res.get_json()["transaction"]
    assert tx["category_name"] == "Groceries"
    assert tx["amount"] == -342.50
    assert tx["amount_base"] == -342.50  # currency matches base
    assert tx["source"] == "manual"
    assert tx["is_recurring"] is False


def test_create_falls_back_to_other(client):
    body = _register(client)
    res = _create(client, body["access_token"], description="Asd qwerty random text")
    assert res.status_code == 201
    assert res.get_json()["transaction"]["category_name"] == "Other"


def test_create_with_explicit_category_id(client):
    body = _register(client)
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    salary_id = next(c["id"] for c in cats if c["name"] == "Salary")
    res = _create(
        client,
        body["access_token"],
        description="Random thing",
        category_id=salary_id,
        amount=3800,
    )
    assert res.status_code == 201
    assert res.get_json()["transaction"]["category_name"] == "Salary"


def test_create_rejects_invalid_currency(client):
    body = _register(client)
    res = _create(client, body["access_token"], currency="GBP")
    assert res.status_code == 422


def test_create_rejects_future_date(client):
    """Transactions can't be future-dated — they didn't happen yet."""
    from datetime import datetime, timedelta, timezone
    body = _register(client)
    future = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()
    res = _create(client, body["access_token"], date=future)
    assert res.status_code == 422


def test_update_rejects_future_date(client):
    from datetime import datetime, timedelta, timezone
    body = _register(client)
    tx = _create(client, body["access_token"]).get_json()["transaction"]
    future = (datetime.now(timezone.utc) + timedelta(days=5)).replace(microsecond=0).isoformat()
    res = client.patch(
        f"/api/transactions/{tx['id']}",
        json={"date": future},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_create_rejects_missing_description(client):
    body = _register(client)
    res = _create(client, body["access_token"], description="")
    assert res.status_code == 422


def test_create_requires_auth(client):
    res = client.post(
        "/api/transactions",
        json={
            "date": "2026-05-04T00:00:00",
            "amount": -10,
            "currency": "RON",
            "description": "x",
        },
    )
    assert res.status_code == 401


# ---- list -----------------------------------------------------------------

def test_list_returns_paginated(client):
    body = _register(client)
    for i in range(5):
        _create(client, body["access_token"], description=f"GLOVO order {i}", amount=-50)

    res = client.get("/api/transactions", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 5
    assert len(data["transactions"]) == 5
    # All should have been auto-categorized as Restaurants
    assert all(t["category_name"] == "Restaurants" for t in data["transactions"])


def test_list_filters_by_search(client):
    body = _register(client)
    _create(client, body["access_token"], description="GLOVO lunch", amount=-50)
    _create(client, body["access_token"], description="CARREFOUR", amount=-100)

    res = client.get(
        "/api/transactions?search=GLOVO", headers=_auth(body["access_token"])
    )
    txs = res.get_json()["transactions"]
    assert len(txs) == 1
    assert txs[0]["description"] == "GLOVO lunch"


def test_list_filters_by_category(client):
    body = _register(client)
    _create(client, body["access_token"], description="GLOVO lunch", amount=-50)
    _create(client, body["access_token"], description="CARREFOUR", amount=-100)
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    groceries_id = next(c["id"] for c in cats if c["name"] == "Groceries")

    res = client.get(
        f"/api/transactions?category_id={groceries_id}",
        headers=_auth(body["access_token"]),
    )
    txs = res.get_json()["transactions"]
    assert len(txs) == 1
    assert txs[0]["category_name"] == "Groceries"


def test_list_isolates_users(client):
    a = _register(client, "a@example.com")
    b = _register(client, "b@example.com")
    _create(client, a["access_token"], description="A's tx", amount=-10)
    res = client.get("/api/transactions", headers=_auth(b["access_token"]))
    assert res.get_json()["total"] == 0


# ---- update / delete ------------------------------------------------------

def test_update_recategorize_logs_correction(client, app):
    body = _register(client)
    tx = _create(client, body["access_token"], description="Asd random").get_json()["transaction"]
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    salary_id = next(c["id"] for c in cats if c["name"] == "Salary")

    res = client.patch(
        f"/api/transactions/{tx['id']}",
        json={"category_id": salary_id},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    assert res.get_json()["transaction"]["category_name"] == "Salary"
    # Correction logged for week-5 ML retrain.
    from app.extensions import mongo
    corrections = list(mongo.db["corrections"].find({}))
    assert len(corrections) == 1
    assert corrections[0]["chosen_category"] == "Salary"
    assert corrections[0]["description"] == "Asd random"


def test_update_amount_recomputes_amount_base(client):
    body = _register(client)
    tx = _create(client, body["access_token"]).get_json()["transaction"]
    res = client.patch(
        f"/api/transactions/{tx['id']}",
        json={"amount": -500},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    updated = res.get_json()["transaction"]
    assert updated["amount"] == -500
    assert updated["amount_base"] == -500


def test_delete_soft_deletes(client):
    body = _register(client)
    tx = _create(client, body["access_token"]).get_json()["transaction"]
    res = client.delete(
        f"/api/transactions/{tx['id']}", headers=_auth(body["access_token"])
    )
    assert res.status_code == 200
    res2 = client.get(
        f"/api/transactions/{tx['id']}", headers=_auth(body["access_token"])
    )
    assert res2.status_code == 404


def test_recategorize_endpoint(client):
    body = _register(client)
    # Create with explicit Salary category, then re-run rules → should flip to Groceries
    cats = client.get("/api/categories", headers=_auth(body["access_token"])).get_json()["categories"]
    salary_id = next(c["id"] for c in cats if c["name"] == "Salary")
    tx = _create(
        client,
        body["access_token"],
        description="CARREFOUR Banesa",
        category_id=salary_id,
    ).get_json()["transaction"]
    assert tx["category_name"] == "Salary"

    res = client.post(
        f"/api/transactions/{tx['id']}/categorize",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    assert res.get_json()["transaction"]["category_name"] == "Groceries"
