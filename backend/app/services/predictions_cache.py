"""Daily-prediction cache for the stock-signal model.

Problem this solves (Q-PERF-1 from the testing campaign): `GET
/api/stocks/signals` re-runs `predict_signals_batch` on every cold cache
miss — ~4-6 s for 100 tickers. The underlying bars only change once a day
(after the 21:30 UTC stock-data refresh), so we can write the day's
predictions to a `ml_predictions` collection and serve from there.

Doc shape:
    {
        ticker: str,
        date: datetime (naive UTC, midnight, the bar date the prediction
            was computed against — typically yesterday after the daily
            refresh runs),
        label: "BUY" | "HOLD" | "SELL",
        confidence: float,
        probabilities: { "BUY": float, "HOLD": float, "SELL": float },
        explanation: str,
        computed_at: datetime,
    }

Compound index `{ticker:1, date:-1}` is bootstrapped at startup.

Cache freshness: callers ask for the latest row per ticker. If the latest
row is older than `MAX_CACHE_AGE_HOURS`, we treat it as stale and let the
caller fall back to live compute. The 26h margin handles weekend gaps
(Friday's cache stays valid through Monday's first read) and the cron
miss-grace window (6h on `refresh_stock_data`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

from app.extensions import mongo
from app.models.stock import SignalOutput
from app.models.user import utcnow

log = logging.getLogger(__name__)

_COLLECTION = "ml_predictions"

# A cache row older than this is considered stale and triggers a live
# fallback. Generous enough to survive a weekend (Fri → Mon = 72h on close,
# but the bar date itself is unchanged) plus a missed cron run.
MAX_CACHE_AGE_HOURS = 96


def upsert_batch(signals: Iterable[SignalOutput], *, computed_at: Optional[datetime] = None) -> int:
    """Write the given predictions to the cache. One doc per
    `(ticker, signal.as_of)` — repeated calls for the same key overwrite
    the prior doc atomically. Returns the number of rows touched.

    The `as_of` field on a SignalOutput is the timestamp of the bar the
    prediction was computed against (yesterday after the daily refresh).
    We store it both as the cache key (`date`) and the source-of-truth
    `as_of` on the returned object — they're the same value, kept under
    both names for the index/serialization shape.
    """
    coll = mongo.db[_COLLECTION]
    now = computed_at or utcnow()
    n = 0
    for sig in signals:
        as_of = sig.as_of
        if as_of.tzinfo is not None:
            as_of = as_of.astimezone(tz=None).replace(tzinfo=None)
        coll.update_one(
            {"ticker": sig.ticker, "date": as_of},
            {"$set": {
                "ticker": sig.ticker,
                "date": as_of,
                "label": sig.label,
                "confidence": float(sig.confidence),
                "probabilities": {k: float(v) for k, v in sig.probabilities.items()},
                "explanation": sig.explanation,
                "computed_at": now,
            }},
            upsert=True,
        )
        n += 1
    return n


def _row_to_signal(doc: dict) -> SignalOutput:
    return SignalOutput(
        ticker=doc["ticker"],
        as_of=doc["date"],
        label=doc["label"],
        confidence=float(doc["confidence"]),
        probabilities={k: float(v) for k, v in doc["probabilities"].items()},
        explanation=doc["explanation"],
    )


def _is_fresh(doc: dict, now: datetime) -> bool:
    """A row is fresh if it was computed within MAX_CACHE_AGE_HOURS.
    Uses `computed_at` (when the prediction was written) rather than
    `date` (the bar date itself) — over a weekend the bar date stays at
    Friday but `computed_at` advances on every daily cron run.
    """
    computed_at = doc.get("computed_at")
    if computed_at is None:
        return False
    age = now - computed_at
    return age <= timedelta(hours=MAX_CACHE_AGE_HOURS)


def get_one(ticker: str, *, now: Optional[datetime] = None) -> Optional[SignalOutput]:
    """Return the freshest cached signal for `ticker`, or None if missing
    or stale. The caller falls back to live compute on None."""
    now = now or utcnow()
    doc = mongo.db[_COLLECTION].find_one(
        {"ticker": ticker},
        sort=[("date", -1)],
    )
    if not doc or not _is_fresh(doc, now):
        return None
    return _row_to_signal(doc)


def get_batch(tickers: list[str], *, now: Optional[datetime] = None) -> dict[str, SignalOutput]:
    """Return `{ticker: SignalOutput}` for every ticker that has a fresh
    cache row. Missing tickers are absent from the dict — the caller can
    decide to live-compute those (or skip)."""
    now = now or utcnow()
    if not tickers:
        return {}
    # Aggregation: latest row per ticker. Equivalent to:
    #   for t in tickers: find_one({"ticker": t}, sort=[("date", -1)])
    # but in one round-trip.
    pipeline = [
        {"$match": {"ticker": {"$in": list(tickers)}}},
        {"$sort": {"ticker": 1, "date": -1}},
        {"$group": {"_id": "$ticker", "doc": {"$first": "$$ROOT"}}},
    ]
    out: dict[str, SignalOutput] = {}
    for row in mongo.db[_COLLECTION].aggregate(pipeline):
        doc = row["doc"]
        if _is_fresh(doc, now):
            out[doc["ticker"]] = _row_to_signal(doc)
    return out
