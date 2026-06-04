"""Search hits transactions, goals, categories, recurring, accounts, and the
static stock universe. Each kind needs at least one happy-path test."""
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


def test_search_empty_query_returns_empty_list(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/search?q=", headers=headers)
    assert res.status_code == 200
    assert res.get_json()["results"] == []


def test_search_finds_transaction_by_description(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    client.post(
        "/api/transactions",
        json={
            "date": _iso(datetime.now(timezone.utc) - timedelta(days=2)),
            "amount": -65.0,
            "currency": "RON",
            "description": "GLOVO online order",
        },
        headers=headers,
    )

    res = client.get("/api/search?q=glovo", headers=headers)
    results = res.get_json()["results"]
    tx_hits = [r for r in results if r["kind"] == "transaction"]
    assert len(tx_hits) >= 1
    assert "GLOVO" in tx_hits[0]["title"].upper() or "glovo" in tx_hits[0]["title"].lower()


def test_search_finds_goal_by_name(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    client.post(
        "/api/goals",
        json={
            "name": "Italy vacation",
            "target_amount": 5000.0,
            "currency": "RON",
            "target_date": _iso(datetime.now(timezone.utc) + timedelta(days=400)),
        },
        headers=headers,
    )
    res = client.get("/api/search?q=italy", headers=headers)
    results = res.get_json()["results"]
    goal_hits = [r for r in results if r["kind"] == "goal"]
    assert len(goal_hits) == 1
    assert goal_hits[0]["title"] == "Italy vacation"


def test_search_finds_category(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/search?q=restaurant", headers=headers)
    results = res.get_json()["results"]
    cat_hits = [r for r in results if r["kind"] == "category"]
    assert len(cat_hits) >= 1
    assert "Restaurants" in [c["title"] for c in cat_hits]


def test_search_finds_stock_by_ticker(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/search?q=AAPL", headers=headers)
    results = res.get_json()["results"]
    stock_hits = [r for r in results if r["kind"] == "stock"]
    assert any(s["title"] == "AAPL" for s in stock_hits)


def test_search_finds_stock_by_company_name(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/search?q=apple", headers=headers)
    results = res.get_json()["results"]
    stock_hits = [r for r in results if r["kind"] == "stock"]
    assert any(s["title"] == "AAPL" for s in stock_hits)


def test_search_results_isolated_per_user(client):
    a = _register(client, "ana@example.com")
    b = _register(client, "bob@example.com")
    a_headers = _auth(a["access_token"])
    b_headers = _auth(b["access_token"])

    client.post(
        "/api/goals",
        json={
            "name": "Ana's secret goal",
            "target_amount": 1000.0,
            "currency": "RON",
            "target_date": _iso(datetime.now(timezone.utc) + timedelta(days=200)),
        },
        headers=a_headers,
    )
    a_res = client.get("/api/search?q=secret", headers=a_headers).get_json()["results"]
    b_res = client.get("/api/search?q=secret", headers=b_headers).get_json()["results"]
    assert any(r["kind"] == "goal" for r in a_res)
    assert not any(r["kind"] == "goal" for r in b_res)


def test_search_requires_auth(client):
    res = client.get("/api/search?q=apple")
    assert res.status_code == 401


def test_search_limit_bounds(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/search?q=apple&limit=0", headers=headers)
    assert res.status_code == 422
    res = client.get("/api/search?q=apple&limit=999", headers=headers)
    assert res.status_code == 422


def test_search_score_ranks_exact_match_first(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/search?q=AAPL&limit=20", headers=headers)
    results = res.get_json()["results"]
    assert results[0]["title"] == "AAPL"
    assert results[0]["kind"] == "stock"
