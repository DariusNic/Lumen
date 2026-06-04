"""Paper-trading portfolio tests — service + API."""
from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId


def _register(client, email="trader@example.com"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123",
              "full_name": "Paper Trader", "base_currency": "USD"},
    ).get_json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_bars(client, ticker: str, n_days: int = 50, start_close: float = 100.0) -> None:
    """Seed `n_days` of bars ending today so latest_bar() returns a known price."""
    from app.extensions import mongo
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for i in range(n_days):
        c = float(start_close + i * 0.5)  # gentle uptrend
        rows.append({
            "ticker": ticker,
            "date": today - timedelta(days=(n_days - 1 - i)),
            "open": c - 0.2, "high": c + 0.4, "low": c - 0.4,
            "close": c, "volume": 1_000_000.0,
        })
    mongo.db["stock_data"].insert_many(rows)


# ---------------------------------------------------------------------------
# Auto-seed at register
# ---------------------------------------------------------------------------

def test_register_creates_empty_10k_portfolio(client):
    body = _register(client)
    res = client.get("/api/portfolio", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    p = res.get_json()
    assert p["cash_usd"] == 10000.0
    assert p["initial_cash_usd"] == 10000.0
    assert p["holdings"] == []
    assert p["market_value_usd"] == 0.0
    assert p["total_value_usd"] == 10000.0
    assert p["trade_count"] == 0


def test_get_portfolio_requires_auth(client):
    assert client.get("/api/portfolio").status_code == 401


# ---------------------------------------------------------------------------
# Buy
# ---------------------------------------------------------------------------

def test_buy_deducts_cash_and_creates_holding(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=30, start_close=180)
    # Last bar close = 180 + 29*0.5 = 194.5
    res = client.post("/api/portfolio/buy",
                      json={"ticker": "AAPL", "qty": 10}, headers=headers)
    assert res.status_code == 201
    trade = res.get_json()["trade"]
    assert trade["side"] == "buy"
    assert trade["qty"] == 10
    assert trade["price"] == 194.5
    assert trade["total"] == 1945.0

    p = client.get("/api/portfolio", headers=headers).get_json()
    assert p["cash_usd"] == 10000.0 - 1945.0
    assert len(p["holdings"]) == 1
    h = p["holdings"][0]
    assert h["ticker"] == "AAPL"
    assert h["qty"] == 10
    assert h["avg_cost"] == 194.5
    assert p["trade_count"] == 1


def test_second_buy_uses_average_cost(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)  # last close = 104.5
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 10}, headers=headers)

    # Add another bar at 200, then buy 10 more.
    from app.extensions import mongo
    new_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    mongo.db["stock_data"].insert_one({
        "ticker": "AAPL", "date": new_date,
        "open": 200, "high": 200, "low": 200, "close": 200.0, "volume": 1.0,
    })
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 10}, headers=headers)

    p = client.get("/api/portfolio", headers=headers).get_json()
    h = next(h for h in p["holdings"] if h["ticker"] == "AAPL")
    assert h["qty"] == 20
    # avg_cost = (10 * 104.5 + 10 * 200) / 20 = 152.25
    assert h["avg_cost"] == 152.25


def test_buy_rejects_insufficient_cash(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=2000)  # last close = 2004.5
    # Would cost 6 * 2004.5 = 12,027 > $10,000.
    res = client.post("/api/portfolio/buy",
                      json={"ticker": "AAPL", "qty": 6}, headers=headers)
    assert res.status_code == 422
    assert "cash" in res.get_json()["message"].lower()


def test_buy_rejects_unknown_ticker(client):
    body = _register(client)
    res = client.post("/api/portfolio/buy",
                      json={"ticker": "NOPE", "qty": 1}, headers=_auth(body["access_token"]))
    assert res.status_code == 422


def test_buy_rejects_no_price_data(client):
    body = _register(client)
    res = client.post("/api/portfolio/buy",
                      json={"ticker": "AAPL", "qty": 1}, headers=_auth(body["access_token"]))
    assert res.status_code == 404


def test_buy_rejects_zero_or_negative_qty(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL")
    assert client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 0},
                       headers=headers).status_code == 422
    assert client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": -5},
                       headers=headers).status_code == 422


# ---------------------------------------------------------------------------
# Sell
# ---------------------------------------------------------------------------

def test_sell_realizes_pnl_and_credits_cash(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)  # close = 104.5
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 10}, headers=headers)

    # Push the close up to 200.
    from app.extensions import mongo
    new_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    mongo.db["stock_data"].insert_one({
        "ticker": "AAPL", "date": new_date,
        "open": 200, "high": 200, "low": 200, "close": 200.0, "volume": 1.0,
    })

    res = client.post("/api/portfolio/sell",
                      json={"ticker": "AAPL", "qty": 4}, headers=headers)
    assert res.status_code == 201
    trade = res.get_json()["trade"]
    assert trade["side"] == "sell"
    assert trade["qty"] == 4
    assert trade["price"] == 200.0
    assert trade["total"] == 800.0
    # realized = (price - avg_cost) * qty = (200 - 104.5) * 4 = 382.0
    assert trade["realized_pnl"] == 382.0

    p = client.get("/api/portfolio", headers=headers).get_json()
    h = next(h for h in p["holdings"] if h["ticker"] == "AAPL")
    assert h["qty"] == 6
    assert h["avg_cost"] == 104.5  # unchanged on sell


def test_sell_full_position_drops_holding(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 5}, headers=headers)
    client.post("/api/portfolio/sell", json={"ticker": "AAPL", "qty": 5}, headers=headers)

    p = client.get("/api/portfolio", headers=headers).get_json()
    assert p["holdings"] == []
    assert p["trade_count"] == 2


def test_sell_more_than_holding_rejected(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 5}, headers=headers)
    res = client.post("/api/portfolio/sell",
                      json={"ticker": "AAPL", "qty": 10}, headers=headers)
    assert res.status_code == 422
    assert "shares" in res.get_json()["message"].lower()


def test_sell_ticker_not_held_rejected(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL")
    res = client.post("/api/portfolio/sell",
                      json={"ticker": "AAPL", "qty": 1}, headers=headers)
    assert res.status_code == 422
    assert "don't hold" in res.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Mark-to-market in get_portfolio
# ---------------------------------------------------------------------------

def test_holdings_reflect_live_prices(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 10}, headers=headers)

    # Bump the close to 150.
    from app.extensions import mongo
    new_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    mongo.db["stock_data"].insert_one({
        "ticker": "AAPL", "date": new_date,
        "open": 150, "high": 150, "low": 150, "close": 150.0, "volume": 1.0,
    })

    p = client.get("/api/portfolio", headers=headers).get_json()
    h = p["holdings"][0]
    assert h["last_price"] == 150.0
    assert h["market_value"] == 1500.0
    # Bought at 104.5, mark at 150 → unrealized = (150 - 104.5) * 10 = 455
    assert h["unrealized_pnl"] == 455.0
    assert p["market_value_usd"] == 1500.0
    assert p["total_value_usd"] == p["cash_usd"] + 1500.0


# ---------------------------------------------------------------------------
# Trades log + reset
# ---------------------------------------------------------------------------

def test_trades_endpoint_returns_recent_first(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)
    _seed_bars(client, "MSFT", n_days=10, start_close=300)

    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 5}, headers=headers)
    client.post("/api/portfolio/buy", json={"ticker": "MSFT", "qty": 2}, headers=headers)

    trades = client.get("/api/portfolio/trades", headers=headers).get_json()["trades"]
    assert len(trades) == 2
    # Most recent first → MSFT before AAPL.
    assert trades[0]["ticker"] == "MSFT"
    assert trades[1]["ticker"] == "AAPL"


def test_reset_wipes_holdings_trades_and_restores_cash(client):
    from app.extensions import mongo

    body = _register(client)
    headers = _auth(body["access_token"])
    user_id = body["user"]["id"]
    _seed_bars(client, "AAPL", n_days=10, start_close=100)
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 5}, headers=headers)
    assert mongo.db["portfolio_trades"].count_documents({"user_id": ObjectId(user_id)}) == 1

    res = client.post("/api/portfolio/reset", headers=headers)
    assert res.status_code == 200
    p = res.get_json()
    assert p["cash_usd"] == 10000.0
    assert p["holdings"] == []
    assert p["trade_count"] == 0
    assert p["reset_at"] is not None
    assert mongo.db["portfolio_trades"].count_documents({"user_id": ObjectId(user_id)}) == 0


# ---------------------------------------------------------------------------
# Equity curve history
# ---------------------------------------------------------------------------

def test_history_starts_at_initial_cash_for_fresh_portfolio(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    res = client.get("/api/portfolio/history?range=3M", headers=headers).get_json()
    assert res["range"] == "3M"
    assert res["initial_cash_usd"] == 10000.0
    # No trades → flat $10k line for at least the most recent day.
    assert len(res["points"]) >= 1
    assert res["points"][-1]["total_value_usd"] == 10000.0


def test_history_reflects_buy_then_price_move(client):
    """After a buy and a price increase, the equity curve should rise."""
    from app.extensions import mongo

    body = _register(client)
    headers = _auth(body["access_token"])
    user_id = body["user"]["id"]
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Seed AAPL with prices that climb.
    for i in range(5):
        mongo.db["stock_data"].insert_one({
            "ticker": "AAPL",
            "date": today - timedelta(days=4 - i),
            "open": 100.0 + i * 10,
            "high": 100.0 + i * 10,
            "low":  100.0 + i * 10,
            "close": 100.0 + i * 10,   # 100, 110, 120, 130, 140
            "volume": 1.0,
        })
    # Push portfolio.created_at back so the history range includes the trade date.
    five_days_ago = today - timedelta(days=4)
    mongo.db["portfolios"].update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {"created_at": five_days_ago}},
    )
    # Buy 10 shares at the latest price (140) — costs $1400, leaves $8600 cash.
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 10}, headers=headers)
    # Backdate the trade so it appears at the start of the window.
    mongo.db["portfolio_trades"].update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {"date": five_days_ago, "price": 100.0, "total": 1000.0}},
    )
    # And reflect the matching cost basis on the holding.
    mongo.db["portfolios"].update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {"cash_usd": 9000.0, "holdings": [
            {"ticker": "AAPL", "qty": 10, "avg_cost": 100.0, "first_bought": five_days_ago},
        ]}},
    )

    res = client.get("/api/portfolio/history?range=ALL", headers=headers).get_json()
    points = res["points"]
    assert len(points) >= 5
    # First point has 10 shares × 100 = 1000 + 9000 cash = 10000.
    # Last point has 10 shares × 140 = 1400 + 9000 = 10400.
    assert points[-1]["total_value_usd"] == 10400.0


def test_history_rejects_invalid_range(client):
    body = _register(client)
    res = client.get("/api/portfolio/history?range=42Y", headers=_auth(body["access_token"]))
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Paper Portfolio account hydration
# ---------------------------------------------------------------------------

def test_paper_portfolio_account_balance_reflects_live_value(client):
    """The auto `Paper Portfolio` account's balance must equal cash + market
    value of holdings — that's what makes the Net Worth page accurate."""
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=10, start_close=100)
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 10}, headers=headers)

    accounts = client.get("/api/accounts", headers=headers).get_json()["accounts"]
    pp = next(a for a in accounts if a["name"] == "Paper Portfolio")
    # cash = 10000 - 10*104.5 = 8955; market = 10*104.5 = 1045 → total 10000.
    assert pp["balance"] == 10000.0
    assert pp["currency"] == "USD"
    assert pp["is_automatic"] is True


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

def test_users_dont_see_each_others_portfolios(client):
    a = _register(client, email="alpha@example.com")
    b = _register(client, email="beta@example.com")
    _seed_bars(client, "AAPL")
    client.post("/api/portfolio/buy", json={"ticker": "AAPL", "qty": 5},
                headers=_auth(a["access_token"]))
    p_b = client.get("/api/portfolio", headers=_auth(b["access_token"])).get_json()
    assert p_b["holdings"] == []
    assert p_b["cash_usd"] == 10000.0


def test_seed_for_user_is_idempotent(client):
    """Calling seed_for_user twice for the same user must not produce two
    portfolios — the unique compound index enforces this at the DB level."""
    from app.extensions import mongo
    from app.services import portfolio_service

    body = _register(client)
    user_id = body["user"]["id"]
    portfolio_service.seed_for_user(user_id)  # second call (register did the first)
    portfolio_service.seed_for_user(user_id)  # third
    assert mongo.db["portfolios"].count_documents({"user_id": ObjectId(user_id)}) == 1


# ---------------------------------------------------------------------------
# Funds adjustment — deposit / withdrawal (paper-only)
# ---------------------------------------------------------------------------

def test_deposit_increases_cash_and_basis(client):
    """Deposit bumps cash AND initial_cash_usd so total_return_pct stays honest."""
    body = _register(client)
    h = _auth(body["access_token"])

    res = client.post(
        "/api/portfolio/funds",
        json={"direction": "deposit", "amount_usd": 5000},
        headers=h,
    )
    assert res.status_code == 201
    trade = res.get_json()["trade"]
    assert trade["side"] == "deposit"
    assert trade["ticker"] == "CASH"
    assert trade["total"] == 5000.0

    p = client.get("/api/portfolio", headers=h).get_json()
    assert p["cash_usd"] == 15000.0
    assert p["initial_cash_usd"] == 15000.0
    # No gain or loss yet — total_return_pct should be 0 because basis matched cash.
    assert p["total_return_pct"] == 0.0


def test_withdrawal_reduces_cash_and_basis(client):
    """Withdrawal reduces both cash and basis."""
    body = _register(client)
    h = _auth(body["access_token"])

    res = client.post(
        "/api/portfolio/funds",
        json={"direction": "withdrawal", "amount_usd": 3000},
        headers=h,
    )
    assert res.status_code == 201
    p = client.get("/api/portfolio", headers=h).get_json()
    assert p["cash_usd"] == 7000.0
    assert p["initial_cash_usd"] == 7000.0


def test_withdrawal_exceeding_cash_is_refused(client):
    """Can't withdraw more than the trading account holds. Default cash = $10k."""
    body = _register(client)
    h = _auth(body["access_token"])

    res = client.post(
        "/api/portfolio/funds",
        json={"direction": "withdrawal", "amount_usd": 15000},
        headers=h,
    )
    assert res.status_code == 422
    detail = res.get_json()
    assert "insufficient" in detail["message"].lower()
    # Cash unchanged after the rejected call.
    p = client.get("/api/portfolio", headers=h).get_json()
    assert p["cash_usd"] == 10000.0


def test_funds_validates_payload(client):
    """Zero or negative amount, missing direction, over-cap — all rejected."""
    body = _register(client)
    h = _auth(body["access_token"])

    for bad in [
        {"direction": "deposit", "amount_usd": 0},
        {"direction": "deposit", "amount_usd": -100},
        {"direction": "deposit", "amount_usd": 1_500_000},
        {"direction": "transfer", "amount_usd": 100},          # bogus direction
        {"amount_usd": 100},                                   # missing direction
        {"direction": "deposit"},                              # missing amount
    ]:
        res = client.post("/api/portfolio/funds", json=bad, headers=h)
        assert res.status_code == 422, f"Expected 422 for {bad}, got {res.status_code}"


def test_funds_does_not_touch_transactions_ledger(client):
    """Deposits/withdrawals are paper-portfolio-only. No PFM transaction is
    created — that's the contract we promise the user in the dialog banner."""
    body = _register(client)
    h = _auth(body["access_token"])

    client.post(
        "/api/portfolio/funds",
        json={"direction": "deposit", "amount_usd": 5000},
        headers=h,
    )
    client.post(
        "/api/portfolio/funds",
        json={"direction": "withdrawal", "amount_usd": 2000},
        headers=h,
    )
    # Two trade rows in portfolio_trades, zero transactions in the PFM ledger.
    trades = client.get("/api/portfolio/trades", headers=h).get_json()["trades"]
    sides = [t["side"] for t in trades]
    assert "deposit" in sides and "withdrawal" in sides

    txs = client.get("/api/transactions", headers=h).get_json()["transactions"]
    assert txs == []  # no PFM ledger entries logged


def test_withdrawal_floors_basis_at_zero(client):
    """If a user withdraws more than they ever deposited (post-gains), basis
    floors at 0 so total_return_pct doesn't go undefined."""
    body = _register(client)
    h = _auth(body["access_token"])

    # Default $10k. Withdraw all of it.
    res = client.post(
        "/api/portfolio/funds",
        json={"direction": "withdrawal", "amount_usd": 10000},
        headers=h,
    )
    assert res.status_code == 201
    p = client.get("/api/portfolio", headers=h).get_json()
    assert p["cash_usd"] == 0.0
    assert p["initial_cash_usd"] == 0.0
