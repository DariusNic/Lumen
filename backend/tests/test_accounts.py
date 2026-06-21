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

def test_register_seeds_two_default_accounts(client):
    body = _register(client)
    res = client.get("/api/accounts", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    accs = data["accounts"]
    assert len(accs) == 2
    names = {a["name"] for a in accs}
    assert names == {"Paper Portfolio", "Net cash flow"}
    # Both are auto-tracked — there are no manual/user-created accounts.
    assert all(a["is_automatic"] for a in accs)


def test_default_paper_portfolio_is_usd_and_automatic(client):
    body = _register(client)
    accs = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    pp = next(a for a in accs if a["name"] == "Paper Portfolio")
    assert pp["currency"] == "USD"
    assert pp["is_automatic"] is True
    assert pp["source_ref"] == "portfolio"
    assert pp["category"] == "asset"


def test_default_net_cashflow_uses_user_base_currency(client):
    body = _register(client, currency="EUR")
    accs = client.get("/api/accounts", headers=_auth(body["access_token"])).get_json()["accounts"]
    ncf = next(a for a in accs if a["name"] == "Net cash flow")
    assert ncf["currency"] == "EUR"
    assert ncf["is_automatic"] is True
    assert ncf["source_ref"] == "transactions:net"


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


# ---------- totals ----------

def test_totals_endpoint_aggregates_auto_accounts(client):
    # Register with USD so the auto Paper Portfolio's currency matches the
    # base — no FX conversion needed in this test, totals math stays exact.
    body = _register(client, currency="USD")
    headers = _auth(body["access_token"])
    # A salary pushes Net cash flow to +2000.
    client.post(
        "/api/transactions",
        json={"date": "2026-05-04T00:00:00", "amount": 2000, "currency": "USD", "description": "Salary"},
        headers=headers,
    )
    data = client.get("/api/accounts", headers=headers).get_json()
    # Paper Portfolio 10000 (auto-seeded $10k) + Net cash flow 2000 = assets 12000.
    # No account can be a liability anymore (manual accounts were removed).
    assert data["totals"]["assets"] == 12000
    assert data["totals"]["liabilities"] == 0
    assert data["totals"]["net_worth"] == 12000


# ---------- isolation + auth ----------

def test_users_dont_see_each_others_accounts(client):
    a = _register(client, "a@example.com")
    b = _register(client, "b@example.com")
    a_ids = {x["id"] for x in
             client.get("/api/accounts", headers=_auth(a["access_token"])).get_json()["accounts"]}
    b_ids = {x["id"] for x in
             client.get("/api/accounts", headers=_auth(b["access_token"])).get_json()["accounts"]}
    # Each user's two auto accounts are distinct documents — no overlap.
    assert a_ids and b_ids
    assert a_ids.isdisjoint(b_ids)


def test_list_requires_auth(client):
    res = client.get("/api/accounts")
    assert res.status_code == 401
