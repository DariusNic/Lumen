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


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# ---------- defaults ----------

def test_register_seeds_three_default_accounts(client):
    body = _register(client)
    res = client.get("/api/accounts", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    accs = data["accounts"]
    assert len(accs) == 3
    names = {a["name"] for a in accs}
    assert names == {"Cash", "Paper Portfolio", "Net cash flow"}


def test_default_paper_portfolio_is_usd_and_automatic(client):
    body = _register(client)
    accs = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    pp = next(a for a in accs if a["name"] == "Paper Portfolio")
    assert pp["currency"] == "USD"
    assert pp["is_automatic"] is True
    assert pp["source_ref"] == "portfolio"
    assert pp["category"] == "asset"


def test_default_cash_uses_user_base_currency(client):
    body = _register(client, currency="EUR")
    accs = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    cash = next(a for a in accs if a["name"] == "Cash")
    assert cash["currency"] == "EUR"
    assert cash["is_automatic"] is False
    assert cash["balance"] == 0.0


def test_net_cashflow_balance_aggregates_transactions(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    # Two expenses, one income → net = -200 - 50 + 1000 = 750
    for amt, desc in [(-200, "Carrefour"), (-50, "Glovo"), (1000, "Salary")]:
        client.post(
            "/api/transactions",
            json={
                "date": "2026-05-04T00:00:00",
                "amount": amt,
                "currency": "RON",
                "description": desc,
            },
            headers=headers,
        )
    accs = client.get("/api/accounts", headers=headers).get_json()["accounts"]
    ncf = next(a for a in accs if a["name"] == "Net cash flow")
    assert ncf["balance"] == 750.0
    assert ncf["source_ref"] == "transactions:net"


# ---------- create / update / delete ----------

def test_create_manual_account(client):
    body = _register(client)
    res = client.post(
        "/api/accounts",
        json={
            "name": "Apartment Bucuresti",
            "type": "real_estate",
            "balance": 92000,
            "currency": "EUR",
            "notes": "Estimated market value",
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    a = res.get_json()["account"]
    assert a["category"] == "asset"
    assert a["balance"] == 92000
    assert a["is_automatic"] is False


def test_create_liability_account(client):
    body = _register(client)
    res = client.post(
        "/api/accounts",
        json={
            "name": "Apartment mortgage",
            "type": "mortgage",
            "balance": 38000,
            "currency": "EUR",
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    a = res.get_json()["account"]
    assert a["category"] == "liability"


def test_create_rejects_unknown_type(client):
    body = _register(client)
    res = client.post(
        "/api/accounts",
        json={"name": "Weird", "type": "crypto_wallet", "currency": "RON"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_create_rejects_duplicate_name(client):
    body = _register(client)
    # "Cash" already exists from seeding
    res = client.post(
        "/api/accounts",
        json={"name": "Cash", "type": "cash", "currency": "RON"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_update_manual_account(client):
    body = _register(client)
    a = client.post(
        "/api/accounts",
        json={"name": "Old name", "type": "savings", "balance": 1000, "currency": "RON"},
        headers=_auth(body["access_token"]),
    ).get_json()["account"]
    res = client.patch(
        f"/api/accounts/{a['id']}",
        json={"name": "ING Savings", "balance": 8400},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    updated = res.get_json()["account"]
    assert updated["name"] == "ING Savings"
    assert updated["balance"] == 8400


def test_cannot_update_automatic_account(client):
    body = _register(client)
    accs = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    pp = next(a for a in accs if a["name"] == "Paper Portfolio")
    res = client.patch(
        f"/api/accounts/{pp['id']}",
        json={"balance": 99999},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_cannot_delete_automatic_account(client):
    body = _register(client)
    accs = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    cash_auto = next(a for a in accs if a["name"] == "Net cash flow")
    res = client.delete(
        f"/api/accounts/{cash_auto['id']}", headers=_auth(body["access_token"])
    )
    assert res.status_code == 422


def test_delete_manual_account(client):
    body = _register(client)
    a = client.post(
        "/api/accounts",
        json={"name": "Temp", "type": "savings", "currency": "RON"},
        headers=_auth(body["access_token"]),
    ).get_json()["account"]
    res = client.delete(f"/api/accounts/{a['id']}", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    after = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    assert all(x["id"] != a["id"] for x in after)


# ---------- totals ----------

def test_totals_endpoint_aggregates_assets_and_liabilities(client):
    # Register with USD so the auto Paper Portfolio's currency matches the
    # base — no FX conversion needed in this test, totals math stays exact.
    body = _register(client, currency="USD")
    headers = _auth(body["access_token"])
    client.post(
        "/api/accounts",
        json={"name": "Apartment", "type": "real_estate", "balance": 90000, "currency": "USD"},
        headers=headers,
    )
    client.post(
        "/api/accounts",
        json={"name": "Mortgage", "type": "mortgage", "balance": 30000, "currency": "USD"},
        headers=headers,
    )
    data = client.get("/api/accounts", headers=headers).get_json()
    # Cash 0 + Paper Portfolio 10000 (auto-seeded $10k) + Net cash flow 0 + Apartment 90000
    # = assets 100000; Mortgage 30000 = liabilities; net = 70000.
    assert data["totals"]["assets"] == 100000
    assert data["totals"]["liabilities"] == 30000
    assert data["totals"]["net_worth"] == 70000


# ---------- isolation + auth ----------

def test_users_dont_see_each_others_accounts(client):
    a = _register(client, "a@example.com")
    b = _register(client, "b@example.com")
    client.post(
        "/api/accounts",
        json={"name": "A only", "type": "savings", "currency": "RON"},
        headers=_auth(a["access_token"]),
    )
    accs_b = client.get("/api/accounts", headers=_auth(b["access_token"])).get_json()["accounts"]
    assert all(x["name"] != "A only" for x in accs_b)


def test_list_requires_auth(client):
    res = client.get("/api/accounts")
    assert res.status_code == 401
