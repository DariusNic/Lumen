"""Alerts are derived from current state, so each test sets up the source
condition (overspent budget, behind goal, recurring due) and asserts the
right alert appears with the right severity."""
from datetime import datetime, timedelta, timezone


def _register(client, email="ana@example.com"):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Ana",
            "base_currency": "RON",
        },
    ).get_json()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# ---------- empty state ----------


def test_alerts_endpoint_shape(client):
    """A fresh user should see no rule-specific alerts (overrun, goal-behind,
    recurring, stale-account) — they only fire once the relevant data
    exists. We assert the response shape and that the alert list is empty."""
    body = _register(client)
    res = client.get("/api/alerts", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    assert "alerts" in data
    assert "unread_count" in data
    rule_alerts = [
        a for a in data["alerts"]
        if a["source"] in ("budget_overrun", "goal_behind", "recurring_due", "stale_account")
    ]
    assert rule_alerts == []


# ---------- budget overrun rule ----------


def test_budget_overrun_creates_critical_alert(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    # Set a budget on the auto-seeded "Restaurants" category.
    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    restaurants = next(c for c in cats if c["name"] == "Restaurants")
    client.patch(
        f"/api/categories/{restaurants['id']}",
        json={"monthly_budget": 800.0},
        headers=headers,
    )

    # Spend 1240 RON this month — 155% of budget → critical.
    today = datetime.now(timezone.utc)
    client.post(
        "/api/transactions",
        json={
            "date": _iso(today),
            "amount": -1240.0,
            "currency": "RON",
            "description": "Wolt order",
            "category_id": restaurants["id"],
        },
        headers=headers,
    )

    res = client.get("/api/alerts", headers=headers)
    alerts = res.get_json()["alerts"]
    overruns = [a for a in alerts if a["source"] == "budget_overrun"]
    assert len(overruns) == 1
    assert overruns[0]["severity"] == "critical"
    assert "Restaurants" in overruns[0]["title"]
    assert overruns[0]["unread"] is True


def test_budget_at_risk_creates_warning_alert(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    groceries = next(c for c in cats if c["name"] == "Groceries")
    client.patch(
        f"/api/categories/{groceries['id']}",
        json={"monthly_budget": 1000.0},
        headers=headers,
    )

    today = datetime.now(timezone.utc)
    # 850 / 1000 = 85% → warning, not critical.
    client.post(
        "/api/transactions",
        json={
            "date": _iso(today),
            "amount": -850.0,
            "currency": "RON",
            "description": "Carrefour",
            "category_id": groceries["id"],
        },
        headers=headers,
    )

    alerts = client.get("/api/alerts", headers=headers).get_json()["alerts"]
    overruns = [a for a in alerts if a["source"] == "budget_overrun"]
    assert len(overruns) == 1
    assert overruns[0]["severity"] == "warning"


def test_budget_under_threshold_no_alert(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    transport = next(c for c in cats if c["name"] == "Transport")
    client.patch(
        f"/api/categories/{transport['id']}",
        json={"monthly_budget": 500.0},
        headers=headers,
    )
    today = datetime.now(timezone.utc)
    # 200 / 500 = 40% → no alert.
    client.post(
        "/api/transactions",
        json={
            "date": _iso(today),
            "amount": -200.0,
            "currency": "RON",
            "description": "STB",
            "category_id": transport["id"],
        },
        headers=headers,
    )

    alerts = client.get("/api/alerts", headers=headers).get_json()["alerts"]
    assert not [a for a in alerts if a["source"] == "budget_overrun"]


# ---------- recurring due rule ----------


def test_recurring_due_within_window_creates_info_alert(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    # Recurring with start_date 25 days ago + monthly cadence → next_due in ~5 days.
    start = datetime.now(timezone.utc) - timedelta(days=25)
    res = client.post(
        "/api/recurring",
        json={
            "name": "Rent",
            "merchant_pattern": "BLOC RENT",
            "amount": 3200.0,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": _iso(start),
        },
        headers=headers,
    )
    assert res.status_code == 201

    alerts = client.get("/api/alerts", headers=headers).get_json()["alerts"]
    due = [a for a in alerts if a["source"] == "recurring_due"]
    assert len(due) == 1
    assert due[0]["severity"] == "info"
    assert "Rent" in due[0]["message"] or "BLOC RENT" in due[0]["message"]


def test_recurring_far_out_no_alert(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    # next_due ~25 days out → outside the 7-day reminder window.
    start = datetime.now(timezone.utc) - timedelta(days=5)
    client.post(
        "/api/recurring",
        json={
            "name": "Spotify",
            "merchant_pattern": "SPOTIFY",
            "amount": 35.0,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": _iso(start),
        },
        headers=headers,
    )
    alerts = client.get("/api/alerts", headers=headers).get_json()["alerts"]
    assert not [a for a in alerts if a["source"] == "recurring_due"]


def test_recurring_income_does_not_alert(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    start = datetime.now(timezone.utc) - timedelta(days=25)
    client.post(
        "/api/recurring",
        json={
            "name": "Salary",
            "merchant_pattern": "ACME PAYROLL",
            "amount": 8000.0,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": _iso(start),
            "is_income": True,
        },
        headers=headers,
    )
    alerts = client.get("/api/alerts", headers=headers).get_json()["alerts"]
    assert not [a for a in alerts if a["source"] == "recurring_due"]


# ---------- mark read ----------


def test_mark_read_persists_across_requests(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    restaurants = next(c for c in cats if c["name"] == "Restaurants")
    client.patch(
        f"/api/categories/{restaurants['id']}",
        json={"monthly_budget": 800.0},
        headers=headers,
    )
    client.post(
        "/api/transactions",
        json={
            "date": _iso(datetime.now(timezone.utc)),
            "amount": -1500.0,
            "currency": "RON",
            "description": "Wolt",
            "category_id": restaurants["id"],
        },
        headers=headers,
    )

    alerts = client.get("/api/alerts", headers=headers).get_json()["alerts"]
    assert all(a["unread"] for a in alerts)
    target_id = next(a["id"] for a in alerts if a["source"] == "budget_overrun")

    res = client.post(
        "/api/alerts/read",
        json={"ids": [target_id]},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.get_json()["marked"] == 1

    refreshed = client.get("/api/alerts", headers=headers).get_json()
    assert refreshed["unread_count"] < len(refreshed["alerts"])
    target = next(a for a in refreshed["alerts"] if a["id"] == target_id)
    assert target["unread"] is False


def test_mark_all_read(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    cats = client.get("/api/categories", headers=headers).get_json()["categories"]
    rest = next(c for c in cats if c["name"] == "Restaurants")
    client.patch(
        f"/api/categories/{rest['id']}",
        json={"monthly_budget": 400.0},
        headers=headers,
    )
    client.post(
        "/api/transactions",
        json={
            "date": _iso(datetime.now(timezone.utc)),
            "amount": -800.0,
            "currency": "RON",
            "description": "Wolt",
            "category_id": rest["id"],
        },
        headers=headers,
    )

    res = client.post("/api/alerts/read", json={}, headers=headers)
    assert res.status_code == 200
    assert res.get_json()["marked"] >= 1

    after = client.get("/api/alerts", headers=headers).get_json()
    assert after["unread_count"] == 0
    assert all(a["unread"] is False for a in after["alerts"])


# ---------- isolation between users ----------


def test_alerts_isolated_per_user(client):
    a_body = _register(client, "ana@example.com")
    b_body = _register(client, "bob@example.com")
    a_headers = _auth(a_body["access_token"])
    b_headers = _auth(b_body["access_token"])

    cats = client.get("/api/categories", headers=a_headers).get_json()["categories"]
    rest = next(c for c in cats if c["name"] == "Restaurants")
    client.patch(
        f"/api/categories/{rest['id']}",
        json={"monthly_budget": 400.0},
        headers=a_headers,
    )
    client.post(
        "/api/transactions",
        json={
            "date": _iso(datetime.now(timezone.utc)),
            "amount": -800.0,
            "currency": "RON",
            "description": "Wolt",
            "category_id": rest["id"],
        },
        headers=a_headers,
    )

    a_alerts = client.get("/api/alerts", headers=a_headers).get_json()["alerts"]
    b_alerts = client.get("/api/alerts", headers=b_headers).get_json()["alerts"]
    assert any(a["source"] == "budget_overrun" for a in a_alerts)
    assert not any(a["source"] == "budget_overrun" for a in b_alerts)


# ---------- auth ----------


def test_alerts_requires_auth(client):
    res = client.get("/api/alerts")
    assert res.status_code == 401
    res = client.post("/api/alerts/read", json={"ids": ["x"]})
    assert res.status_code == 401
