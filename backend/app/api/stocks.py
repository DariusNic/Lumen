"""Stock data + signal endpoints.

  GET /api/stocks                  → list every tracked ticker with last close
                                     + 1d / 5d % change. Used by MarketsPage.
  GET /api/stocks/<ticker>          → OHLCV history for one ticker (range
                                     selector via `?range=1M|3M|6M|1Y|ALL`).
                                     Used by StockDetailPage.
  GET /api/stocks/<ticker>/signal   → current BUY / HOLD / SELL signal with
                                     `predict_proba` confidence + rule-based
                                     explanation. Wraps `predict_signal`.

All routes are JWT-required even though stock data is global — keeps the
attack surface tight and matches every other resource in the app.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from flask import Blueprint, jsonify, request

from app.models.user import utcnow
from flask_jwt_extended import jwt_required

from app.extensions import mongo
from app.ml.signals import predict
from app.services import predictions_cache, stock_data_service
from app.utils.constants import TICKER_META, TICKERS
from app.utils.errors import NotFoundError, ValidationError

bp = Blueprint("stocks", __name__)

_RANGE_DAYS: dict[str, Optional[int]] = {
    "1M": 31,
    "3M": 92,
    "6M": 183,
    "1Y": 366,
    "ALL": None,
}


# ---------------------------------------------------------------------------
# GET /api/stocks — universe summary
# ---------------------------------------------------------------------------

@bp.get("/stocks")
@jwt_required()
def list_stocks():
    """Return one row per ticker in the configured universe with its latest
    bar and 1d / 5d percent change.

    Implementation: per-ticker `find().sort().limit(6)`. A single
    aggregation across all 184k bars hit Mongo's 32 MB sort memory limit
    (it sorted everything before grouping, then pushed entire histories
    into arrays). The per-ticker loop is 100 indexed range scans of 6
    rows each — fast (<1 s on Atlas free) and won't outgrow memory as the
    universe scales.
    """
    tickers = list(TICKERS)
    coll = mongo.db["stock_data"]

    items: list[dict[str, Any]] = []
    for t in tickers:
        bars = list(
            coll.find(
                {"ticker": t},
                projection={"date": 1, "close": 1, "_id": 0},
            ).sort("date", -1).limit(6)
        )
        if not bars:
            continue
        latest = bars[0]
        prev_1d = bars[1] if len(bars) > 1 else None
        prev_5d = bars[5] if len(bars) > 5 else None
        change_1d = (
            (latest["close"] - prev_1d["close"]) / prev_1d["close"]
            if prev_1d and prev_1d["close"] else None
        )
        change_5d = (
            (latest["close"] - prev_5d["close"]) / prev_5d["close"]
            if prev_5d and prev_5d["close"] else None
        )
        meta = TICKER_META.get(t, {})
        items.append({
            "ticker": t,
            "name": meta.get("name", t),
            "sector": meta.get("sector", "Other"),
            "last_close": float(latest["close"]),
            "last_date": latest["date"].isoformat() if hasattr(latest["date"], "isoformat") else latest["date"],
            "change_1d_pct": float(change_1d) if change_1d is not None else None,
            "change_5d_pct": float(change_5d) if change_5d is not None else None,
        })

    return jsonify({"tickers": items, "total": len(items)})


# ---------------------------------------------------------------------------
# GET /api/stocks/<ticker> — single-ticker history
# ---------------------------------------------------------------------------

@bp.get("/stocks/<ticker>")
@jwt_required()
def get_ticker(ticker: str):
    ticker = ticker.upper()
    if ticker not in TICKERS:
        raise NotFoundError("Ticker not in tracked universe", details={"ticker": ticker})

    range_key = (request.args.get("range") or "3M").upper()
    if range_key not in _RANGE_DAYS:
        raise ValidationError(
            "Invalid `range`",
            details={"value": range_key, "allowed": sorted(_RANGE_DAYS)},
        )
    days = _RANGE_DAYS[range_key]
    start = None
    if days is not None:
        start = utcnow() - timedelta(days=days)

    df = stock_data_service.get_history(ticker, start=start)
    if df.empty:
        raise NotFoundError("No price history for ticker", details={"ticker": ticker})

    history = [
        {
            "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for idx, row in df.iterrows()
    ]
    meta = TICKER_META.get(ticker, {})
    return jsonify({
        "ticker": ticker,
        "name": meta.get("name", ticker),
        "sector": meta.get("sector", "Other"),
        "range": range_key,
        "rows": len(history),
        "history": history,
    })


# ---------------------------------------------------------------------------
# GET /api/stocks/<ticker>/signal — current signal
# ---------------------------------------------------------------------------

@bp.get("/stocks/<ticker>/signal")
@jwt_required()
def get_signal(ticker: str):
    """Returns a `SignalOutput`. Reads from the `ml_predictions` cache
    (refreshed daily at 21:30 UTC). On cache miss/staleness falls back to
    live compute. May raise:
      - `SignalUnavailable` (503) → model not trained, or ticker has no/
        too-little data — handled by the global error envelope.
      - `NotFoundError` (404) → ticker isn't in the configured universe.
    """
    ticker = ticker.upper()
    if ticker not in TICKERS:
        raise NotFoundError("Ticker not in tracked universe", details={"ticker": ticker})
    cached = predictions_cache.get_one(ticker)
    if cached is not None:
        return jsonify(cached.model_dump(mode="json"))
    sig = predict.predict_signal(ticker)
    return jsonify(sig.model_dump(mode="json"))


@bp.get("/stocks/signals")
@jwt_required()
def get_all_signals():
    """Batched signal inference for the whole universe. Used by the Markets
    page so each row can show a BUY/HOLD/SELL pill without firing 100
    separate /signal requests. Tickers without seeded data or enough
    warmup are silently skipped — the page must render even when the
    universe isn't fully populated.

    Reads from the `ml_predictions` cache (refreshed daily at 21:30 UTC)
    to avoid the ~4-6s cold-load cost of re-running 100 ticker
    predictions per request (Q-PERF-1). If the cache is empty / stale for
    most tickers (e.g. right after a deploy before the first cron run),
    falls through to live compute and the next cron fires up the cache.

    503 still applies if the model artifact itself is missing (caller
    hasn't trained yet).
    """
    tickers = list(TICKERS)
    cached = predictions_cache.get_batch(tickers)
    # If we got cache coverage for most of the universe, serve from cache —
    # avoids the multi-second loop. The 50% threshold means we only fall
    # through to live compute when the cache is genuinely cold (deploy /
    # first run / migration), not when a single ticker happens to be stale.
    if len(cached) >= len(tickers) // 2:
        signals = [cached[t] for t in tickers if t in cached]
    else:
        signals = predict.predict_signals_batch(tickers)
    return jsonify({
        "signals": [s.model_dump(mode="json") for s in signals],
        "total": len(signals),
    })
