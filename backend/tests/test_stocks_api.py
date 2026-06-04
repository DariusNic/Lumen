"""Stocks API endpoint tests.

Three routes (all `@jwt_required()`):
  - GET /api/stocks
  - GET /api/stocks/<ticker>
  - GET /api/stocks/<ticker>/signal
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from app.ml.signals import predict


def _register(client, email="stocks@example.com"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123",
              "full_name": "Stocks User", "base_currency": "USD"},
    ).get_json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_bars(client, ticker: str, n_days: int = 200, start_close: float = 180.0) -> None:
    """Seed `n_days` of synthetic OHLCV bars for `ticker`, with the LAST bar
    dated today. The endpoints filter history by `utcnow() - <range>` so
    bars need to fall inside the recent window for tests to exercise them.
    """
    from app.extensions import mongo
    rng = np.random.default_rng(hash(ticker) & 0xFFFF)
    close = start_close + np.cumsum(rng.standard_normal(n_days) * 0.8)
    rows = []
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(n_days):
        c = float(close[i])
        rows.append({
            "ticker": ticker,
            # Walk backwards from today so the last (i = n_days-1) bar is today.
            "date": today - timedelta(days=(n_days - 1 - i)),
            "open": c - 0.3, "high": c + 0.5, "low": c - 0.5,
            "close": c, "volume": float(rng.integers(1_000_000, 5_000_000)),
        })
    mongo.db["stock_data"].insert_many(rows)


@pytest.fixture(autouse=True)
def _restore_predict_cache():
    yield
    predict.reset_model_cache()


# ---------------------------------------------------------------------------
# GET /api/stocks
# ---------------------------------------------------------------------------

def test_list_stocks_requires_auth(client):
    assert client.get("/api/stocks").status_code == 401


def test_list_stocks_returns_seeded_tickers(client):
    body = _register(client)
    headers = _auth(body["access_token"])

    _seed_bars(client, "AAPL", n_days=10, start_close=180)
    _seed_bars(client, "MSFT", n_days=10, start_close=370)

    res = client.get("/api/stocks", headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    by_t = {t["ticker"]: t for t in data["tickers"]}
    assert "AAPL" in by_t
    assert "MSFT" in by_t
    # 1d / 5d changes are populated when there's enough history.
    assert by_t["AAPL"]["change_1d_pct"] is not None
    assert by_t["AAPL"]["change_5d_pct"] is not None
    # Last close is the most recent bar.
    assert isinstance(by_t["AAPL"]["last_close"], float)


def test_list_stocks_handles_thin_history(client):
    """A ticker with only 1 bar should still appear, but with None for 1d/5d."""
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=1)
    res = client.get("/api/stocks", headers=_auth(body["access_token"])).get_json()
    aapl = next(t for t in res["tickers"] if t["ticker"] == "AAPL")
    assert aapl["change_1d_pct"] is None
    assert aapl["change_5d_pct"] is None


def test_list_stocks_skips_tickers_with_no_data(client):
    """The 100-ticker constant is fixed; tickers without seeded bars are
    silently dropped from the response so the UI doesn't render empty rows."""
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=10)
    res = client.get("/api/stocks", headers=_auth(body["access_token"])).get_json()
    tickers_returned = {t["ticker"] for t in res["tickers"]}
    assert tickers_returned == {"AAPL"}
    assert res["total"] == 1


# ---------------------------------------------------------------------------
# GET /api/stocks/<ticker>
# ---------------------------------------------------------------------------

def test_get_ticker_returns_history_in_default_3M_range(client):
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=100)
    res = client.get("/api/stocks/AAPL", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    assert data["ticker"] == "AAPL"
    assert data["range"] == "3M"
    assert data["rows"] > 0
    # First row has all OHLCV fields.
    row = data["history"][0]
    assert {"date", "open", "high", "low", "close", "volume"} <= set(row)


def test_get_ticker_supports_range_param(client):
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=400)
    headers = _auth(body["access_token"])

    short = client.get("/api/stocks/AAPL?range=1M", headers=headers).get_json()
    long_ = client.get("/api/stocks/AAPL?range=ALL", headers=headers).get_json()
    assert short["rows"] < long_["rows"]
    assert short["range"] == "1M"
    assert long_["range"] == "ALL"


def test_get_ticker_unknown_ticker_404(client):
    body = _register(client)
    res = client.get("/api/stocks/NOPE", headers=_auth(body["access_token"]))
    assert res.status_code == 404


def test_get_ticker_known_but_no_data_404(client):
    """Ticker is in the universe but `stock_data` has no rows for it yet
    (e.g. we just deployed and haven't run the seed)."""
    body = _register(client)
    res = client.get("/api/stocks/AAPL", headers=_auth(body["access_token"]))
    assert res.status_code == 404


def test_get_ticker_invalid_range_422(client):
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=10)
    res = client.get("/api/stocks/AAPL?range=42Y", headers=_auth(body["access_token"]))
    assert res.status_code == 422


def test_get_ticker_brk_b_round_trips_with_hyphen(client):
    """The BRK-B hyphen edge case — keep verifying it through every layer."""
    body = _register(client)
    _seed_bars(client, "BRK-B", n_days=10)
    res = client.get("/api/stocks/BRK-B", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    assert res.get_json()["ticker"] == "BRK-B"


# ---------------------------------------------------------------------------
# GET /api/stocks/<ticker>/signal
# ---------------------------------------------------------------------------

class _FakeBooster:
    classes_ = np.array([0, 1, 2])
    def __init__(self, proba): self._p = np.array(proba, dtype=float)
    def predict_proba(self, x): return np.tile(self._p, (len(x), 1))


def _install_model(proba):
    predict._MODEL = _FakeBooster(proba)
    predict._MODEL_LOAD_FAILED = False


def test_signal_endpoint_returns_buy(client):
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=200)
    _install_model([0.05, 0.20, 0.75])

    res = client.get("/api/stocks/AAPL/signal", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    assert data["ticker"] == "AAPL"
    assert data["label"] == "BUY"
    assert data["confidence"] == pytest.approx(0.75)
    assert set(data["probabilities"]) == {"BUY", "HOLD", "SELL"}
    assert isinstance(data["explanation"], str) and len(data["explanation"]) > 0


def test_signal_endpoint_unknown_ticker_404(client):
    body = _register(client)
    _install_model([0.33, 0.34, 0.33])
    res = client.get("/api/stocks/NOPE/signal", headers=_auth(body["access_token"]))
    assert res.status_code == 404


def test_signal_endpoint_no_model_503(client, tmp_path):
    """Missing artifact → SignalUnavailable maps to 503 via the global
    error handler."""
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=200)
    with patch.object(predict, "_MODEL_PATH", tmp_path / "nope.joblib"):
        predict.reset_model_cache()
        res = client.get("/api/stocks/AAPL/signal", headers=_auth(body["access_token"]))
    assert res.status_code == 503
    assert res.get_json()["error_code"] == "SIGNAL_UNAVAILABLE"


def test_signal_endpoint_no_data_503(client):
    """Ticker is known but `stock_data` has no bars — SignalUnavailable."""
    body = _register(client)
    _install_model([0.33, 0.34, 0.33])
    res = client.get("/api/stocks/AAPL/signal", headers=_auth(body["access_token"]))
    assert res.status_code == 503


def test_signal_endpoint_requires_auth(client):
    assert client.get("/api/stocks/AAPL/signal").status_code == 401


# ---------------------------------------------------------------------------
# GET /api/stocks/signals (batch — used by MarketsPage)
# ---------------------------------------------------------------------------

def test_signals_batch_returns_one_per_seeded_ticker(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=200)
    _seed_bars(client, "MSFT", n_days=200)
    _install_model([0.10, 0.20, 0.70])

    res = client.get("/api/stocks/signals", headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    tickers = {s["ticker"] for s in data["signals"]}
    assert {"AAPL", "MSFT"} <= tickers   # at least these two
    # Static `/signals` route must NOT be caught by the `/<ticker>` rule.
    sample = data["signals"][0]
    assert sample["label"] in {"BUY", "HOLD", "SELL"}
    assert isinstance(sample["confidence"], float)
    assert isinstance(sample["explanation"], str)


def test_signals_batch_skips_tickers_without_data(client):
    """Universe is 100 tickers but only 1 is seeded — batch returns just
    that one, doesn't 503 the whole request."""
    body = _register(client)
    headers = _auth(body["access_token"])
    _seed_bars(client, "AAPL", n_days=200)
    _install_model([0.30, 0.40, 0.30])

    res = client.get("/api/stocks/signals", headers=headers)
    assert res.status_code == 200
    assert res.get_json()["total"] == 1


def test_signals_batch_503_when_model_missing(client, tmp_path):
    body = _register(client)
    _seed_bars(client, "AAPL", n_days=200)
    with patch.object(predict, "_MODEL_PATH", tmp_path / "nope.joblib"):
        predict.reset_model_cache()
        res = client.get("/api/stocks/signals", headers=_auth(body["access_token"]))
    assert res.status_code == 503


def test_signals_batch_requires_auth(client):
    assert client.get("/api/stocks/signals").status_code == 401
