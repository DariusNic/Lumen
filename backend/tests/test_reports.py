def _register(client):
    return client.post(
        "/api/auth/register",
        json={
            "email": "ana@example.com",
            "password": "password123",
            "full_name": "Ana",
            "base_currency": "RON",
        },
    ).get_json()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _seed_transactions(client, token):
    """5 expenses + 1 salary across 2 categories."""
    rows = [
        ("2026-05-04T00:00:00", -342.50, "CARREFOUR Baneasa"),    # Groceries
        ("2026-05-04T00:00:00", -68.00,  "GLOVO order"),           # Restaurants
        ("2026-05-03T00:00:00", -3200.00, "CHIRIE Aviatorilor"),  # Housing
        ("2026-05-03T00:00:00", -52.00,  "Wolt courier"),          # Restaurants
        ("2026-05-02T00:00:00", -127.40, "Profi Floreasca"),      # Groceries
        ("2026-05-02T00:00:00", 3800.00, "SALARIU ACME SRL"),     # Salary (income)
    ]
    for date, amount, desc in rows:
        client.post(
            "/api/transactions",
            json={"date": date, "amount": amount, "currency": "RON", "description": desc},
            headers=_auth(token),
        )


def test_spending_by_category_aggregates_expenses(client):
    body = _register(client)
    _seed_transactions(client, body["access_token"])

    res = client.get(
        "/api/reports/spending", headers=_auth(body["access_token"])
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_expense"] == round(342.50 + 68 + 3200 + 52 + 127.40, 2)
    assert data["total_income"] == 3800.00

    by_name = {item["category_name"]: item for item in data["items"]}
    # Restaurants (Glovo + Wolt) totals 120
    assert by_name["Restaurants"]["total"] == 120.0
    assert by_name["Restaurants"]["count"] == 2
    # Groceries (Carrefour + Profi) totals 469.90
    assert abs(by_name["Groceries"]["total"] - 469.90) < 0.01
    # Housing (Chirie) is the largest
    assert by_name["Housing"]["total"] == 3200.0
    # Salary (income) does NOT appear under spending
    assert "Salary" not in by_name


def test_spending_filters_by_date_range(client):
    body = _register(client)
    _seed_transactions(client, body["access_token"])

    res = client.get(
        "/api/reports/spending?from=2026-05-03&to=2026-05-04",
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    data = res.get_json()
    # Excludes May 2 transactions (Profi 127.40 expense + 3800 salary income)
    assert data["total_income"] == 0
    expected_expense = 342.50 + 68 + 3200 + 52
    assert abs(data["total_expense"] - expected_expense) < 0.01


def test_spending_invalid_date_returns_422(client):
    body = _register(client)
    res = client.get(
        "/api/reports/spending?from=not-a-date", headers=_auth(body["access_token"])
    )
    assert res.status_code == 422


def test_spending_requires_auth(client):
    res = client.get("/api/reports/spending")
    assert res.status_code == 401


def test_monthly_summary(client):
    body = _register(client)
    _seed_transactions(client, body["access_token"])
    res = client.get(
        "/api/reports/monthly?months=3", headers=_auth(body["access_token"])
    )
    assert res.status_code == 200
    data = res.get_json()
    # All 6 transactions in May 2026 → exactly one row.
    assert any(m["year"] == 2026 and m["month"] == 5 for m in data["months"])
    may = next(m for m in data["months"] if m["year"] == 2026 and m["month"] == 5)
    assert may["income"] == 3800.0
    assert may["expense"] == round(342.50 + 68 + 3200 + 52 + 127.40, 2)


def test_monthly_summary_rejects_out_of_range(client):
    body = _register(client)
    res = client.get(
        "/api/reports/monthly?months=99", headers=_auth(body["access_token"])
    )
    assert res.status_code == 422


def test_top_merchants_aggregates_by_merchant(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    # Two transactions to "Glovo", one to "Wolt" — Glovo should rank higher.
    for amount, desc in [(-100.0, "GLOVO"), (-200.0, "GLOVO"), (-150.0, "WOLT")]:
        client.post(
            "/api/transactions",
            json={
                "date": "2026-05-04T00:00:00",
                "amount": amount,
                "currency": "RON",
                "description": desc,
            },
            headers=headers,
        )
    res = client.get("/api/reports/merchants?limit=5", headers=headers)
    assert res.status_code == 200
    items = res.get_json()["items"]
    assert items[0]["merchant"].upper() == "GLOVO"
    assert items[0]["total"] == 300.0
    assert items[0]["count"] == 2
    assert items[0]["avg"] == 150.0


def test_top_merchants_rejects_bad_limit(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/reports/merchants?limit=999", headers=headers)
    assert res.status_code == 422
