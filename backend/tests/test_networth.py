"""Net worth tracking — service + API + backfill + scheduled job entry point."""
from datetime import datetime, timedelta, timezone

from bson import ObjectId


def _register(client, email="nw@example.com", currency="RON"):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "NW User",
            "base_currency": currency,
        },
    ).get_json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _past(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


def _paper_portfolio_base(client, headers, base_currency: str = "RON") -> float:
    """The seeded $10K USD Paper Portfolio's value in `base_currency`.

    Goes through `/api/fx/convert` so the conversion uses the same cached
    rate that `networth_service` does internally. Returns 2-decimal rounded.
    """
    if base_currency == "USD":
        return 10000.0
    fx = client.get(
        f"/api/fx/convert?from=USD&to={base_currency}&amount=10000",
        headers=headers,
    ).get_json()
    return round(float(fx["converted"]), 2)


# ---------------------------------------------------------------------------
# GET /api/networth — current
# ---------------------------------------------------------------------------

def test_current_networth_for_fresh_user_includes_paper_portfolio(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/networth", headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    # Fresh user has 2 seeded auto accounts: Net cash flow 0, and Paper
    # Portfolio with $10K USD seed → ~44k RON (varies with FX rate).
    pp = _paper_portfolio_base(client, headers, "RON")
    assert data["total_assets"] == pp
    assert data["total_liabilities"] == 0
    assert data["net_worth"] == pp
    assert data["base_currency"] == "RON"
    assert data["snapshot_count"] == 0
    assert data["delta_30d"] is None
    assert len(data["breakdown"]) == 2


def test_current_networth_reflects_transactions(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    # Insert a salary credit so Net cash flow becomes positive.
    client.post("/api/transactions", json={
        "date": _past(1), "amount": 5000, "currency": "RON", "description": "Salariu",
    }, headers=headers)

    data = client.get("/api/networth", headers=headers).get_json()
    pp = _paper_portfolio_base(client, headers, "RON")
    assert data["net_worth"] == round(5000 + pp, 2)
    assert data["total_assets"] == round(5000 + pp, 2)
    assert data["total_liabilities"] == 0


def test_current_networth_requires_auth(client):
    assert client.get("/api/networth").status_code == 401


# ---------------------------------------------------------------------------
# POST /api/networth/snapshot
# ---------------------------------------------------------------------------

def test_manual_snapshot_creates_row(client):
    from app.extensions import mongo

    body = _register(client)
    headers = _auth(body["access_token"])
    client.post("/api/transactions", json={
        "date": _past(1), "amount": 1000, "currency": "RON", "description": "Salary",
    }, headers=headers)

    res = client.post("/api/networth/snapshot", headers=headers)
    assert res.status_code == 201
    snap = res.get_json()["snapshot"]
    pp = _paper_portfolio_base(client, headers, "RON")
    assert snap["net_worth"] == round(1000 + pp, 2)
    assert snap["source"] == "manual"
    # Row in db.
    assert mongo.db["net_worth_snapshots"].count_documents({}) == 1


def test_manual_snapshot_idempotent_per_day(client):
    """Two snapshots on the same calendar day → one row (upsert), not two."""
    from app.extensions import mongo
    body = _register(client)
    headers = _auth(body["access_token"])

    client.post("/api/networth/snapshot", headers=headers)
    client.post("/api/networth/snapshot", headers=headers)
    assert mongo.db["net_worth_snapshots"].count_documents({}) == 1


def test_snapshot_picks_up_breakdown(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    # A salary makes the Net cash flow account a meaningful, non-zero entry.
    client.post("/api/transactions", json={
        "date": _past(1), "amount": 3000, "currency": "RON", "description": "Salariu",
    }, headers=headers)

    snap = client.post("/api/networth/snapshot", headers=headers).get_json()["snapshot"]
    names = [b["name"] for b in snap["breakdown"]]
    # The two auto accounts always appear in the breakdown.
    assert "Net cash flow" in names
    assert "Paper Portfolio" in names
    ncf = next(b for b in snap["breakdown"] if b["name"] == "Net cash flow")
    assert ncf["category"] == "asset"
    assert ncf["balance_base"] == 3000


# ---------------------------------------------------------------------------
# GET /api/networth/history
# ---------------------------------------------------------------------------

def test_history_empty_for_fresh_user(client):
    body = _register(client)
    res = client.get("/api/networth/history?range=3M", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    assert data["range"] == "3M"
    assert data["points"] == []


def test_history_returns_snapshots_in_order(client):
    from app.services import networth_service

    body = _register(client)
    headers = _auth(body["access_token"])
    user_id = body["user"]["id"]

    # Take a snapshot today + a few backdated ones via the service.
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    for d in [-30, -20, -10, 0]:
        networth_service.take_snapshot(
            user_id, source="backfill", on=today + timedelta(days=d),
        )

    data = client.get("/api/networth/history?range=3M", headers=headers).get_json()
    assert len(data["points"]) == 4
    dates = [p["date"] for p in data["points"]]
    assert dates == sorted(dates)  # ascending


def test_history_rejects_invalid_range(client):
    body = _register(client)
    res = client.get("/api/networth/history?range=42Y", headers=_auth(body["access_token"]))
    assert res.status_code == 422


def test_history_range_filters_old_points(client):
    """A snapshot 200 days back is excluded from the 3M (~92d) range."""
    from app.extensions import mongo
    from app.services import networth_service

    body = _register(client)
    headers = _auth(body["access_token"])
    user_id = body["user"]["id"]

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    # 1 row 200 days back, 1 row today.
    networth_service.take_snapshot(user_id, source="backfill", on=today - timedelta(days=200))
    networth_service.take_snapshot(user_id, source="backfill", on=today)

    # Sanity: both rows are in the DB.
    assert mongo.db["net_worth_snapshots"].count_documents({}) == 2

    data = client.get("/api/networth/history?range=3M", headers=headers).get_json()
    assert len(data["points"]) == 1   # only today
    data_all = client.get("/api/networth/history?range=ALL", headers=headers).get_json()
    assert len(data_all["points"]) == 2


# ---------------------------------------------------------------------------
# Delta vs ~30 days ago
# ---------------------------------------------------------------------------

def test_current_includes_delta_30d_when_history_exists(client):
    from app.services import networth_service

    body = _register(client)
    headers = _auth(body["access_token"])
    user_id = body["user"]["id"]

    # Plant a 30-day-old snapshot at 1000 RON.
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    snap = networth_service.take_snapshot(user_id, source="backfill", on=today - timedelta(days=30))
    # Override the historical value directly (we want to test the delta math, not balance reconstruction).
    from app.extensions import mongo
    mongo.db["net_worth_snapshots"].update_one(
        {"_id": ObjectId(snap.id)},
        {"$set": {"net_worth": 1000, "total_assets": 1000, "total_liabilities": 0}},
    )

    # Now insert a salary so today's net worth is 5000 + paper portfolio.
    client.post("/api/transactions", json={
        "date": _past(0), "amount": 5000, "currency": "RON", "description": "Salariu",
    }, headers=headers)

    data = client.get("/api/networth", headers=headers).get_json()
    pp = _paper_portfolio_base(client, headers, "RON")
    assert data["net_worth"] == round(5000 + pp, 2)
    # delta_30d = today - planted historical (1000)
    assert data["delta_30d"] == round((5000 + pp) - 1000, 2)
    # delta_pct = delta / planted * 100
    expected_pct = round(((5000 + pp - 1000) / 1000) * 100, 1)
    assert abs(data["delta_30d_pct"] - expected_pct) < 0.5


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------

def test_backfill_inserts_one_row_per_day(client):
    from app.extensions import mongo
    from app.services import networth_service

    body = _register(client)
    networth_service.backfill(body["user"]["id"], days=10, step_days=1)
    # 11 inclusive points (today + 10 days back).
    assert mongo.db["net_worth_snapshots"].count_documents({}) == 11


def test_backfill_idempotent(client):
    from app.extensions import mongo
    from app.services import networth_service

    body = _register(client)
    networth_service.backfill(body["user"]["id"], days=5)
    networth_service.backfill(body["user"]["id"], days=5)
    # Second run should overwrite, not duplicate.
    assert mongo.db["net_worth_snapshots"].count_documents({}) == 6


def test_backfill_net_cashflow_is_time_accurate(client):
    """The auto Net cash flow account at a past date should reflect only the
    transactions on or before that date — not the user's full history."""
    from app.services import networth_service

    body = _register(client)
    headers = _auth(body["access_token"])
    user_id = body["user"]["id"]

    # Two transactions: salary 60 days ago, expense 10 days ago.
    client.post("/api/transactions", json={
        "date": _past(60), "amount": 5000, "currency": "RON", "description": "Salariu",
    }, headers=headers)
    client.post("/api/transactions", json={
        "date": _past(10), "amount": -200, "currency": "RON", "description": "Random spend",
    }, headers=headers)

    networth_service.backfill(user_id, days=90, step_days=1)
    history = client.get("/api/networth/history?range=ALL", headers=headers).get_json()
    points = {p["date"][:10]: p["net_worth"] for p in history["points"]}

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    point_70 = (today - timedelta(days=70)).date().isoformat()
    point_30 = (today - timedelta(days=30)).date().isoformat()
    point_5 = (today - timedelta(days=5)).date().isoformat()

    # The Paper Portfolio's $10K seed shows up in every historical point.
    # Backfill uses *historical* FX rates (USD→RON for the snapshot date),
    # so the converted value drifts a few percent across dates — we allow
    # a 7% tolerance for the time-varying paper-portfolio component.
    pp_today = _paper_portfolio_base(client, headers, "RON")
    tol = pp_today * 0.07
    # 70 days ago — neither tx applies yet → just the paper portfolio.
    assert abs(points[point_70] - pp_today) < tol
    # 30 days ago — salary applied (60d), expense not yet (10d) → 5000 + pp.
    assert abs(points[point_30] - (5000 + pp_today)) < tol
    # 5 days ago — both applied → 4800 + pp.
    assert abs(points[point_5] - (4800 + pp_today)) < tol


# ---------------------------------------------------------------------------
# Scheduled job entry point
# ---------------------------------------------------------------------------

def test_snapshot_all_users_iterates_every_user(client):
    from app.extensions import mongo
    from app.services import networth_service

    _register(client, email="a@example.com")
    _register(client, email="b@example.com")
    _register(client, email="c@example.com")

    stats = networth_service.snapshot_all_users()
    assert stats["users_total"] == 3
    assert stats["ok"] == 3
    assert stats["failed"] == 0
    # One snapshot per user today.
    assert mongo.db["net_worth_snapshots"].count_documents({}) == 3


def test_snapshot_all_users_resilient_to_individual_failures(client, monkeypatch):
    """If one user's snapshot raises, others still complete."""
    from app.services import networth_service

    _register(client, email="alpha@example.com")
    _register(client, email="beta@example.com")

    real_take = networth_service.take_snapshot
    call_count = {"n": 0}

    def flaky_take(user_id, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated FX glitch on first user")
        return real_take(user_id, **kw)

    monkeypatch.setattr(networth_service, "take_snapshot", flaky_take)
    stats = networth_service.snapshot_all_users()
    assert stats["users_total"] == 2
    assert stats["ok"] == 1
    assert stats["failed"] == 1


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def test_users_dont_see_each_others_history(client):
    from app.services import networth_service

    a = _register(client, email="x@example.com")
    b = _register(client, email="y@example.com")
    networth_service.take_snapshot(a["user"]["id"], source="manual")

    points = client.get(
        "/api/networth/history?range=ALL", headers=_auth(b["access_token"]),
    ).get_json()["points"]
    assert points == []
