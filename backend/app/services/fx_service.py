"""FX rate service — Frankfurter (ECB) backed, cached daily in Mongo.

Design notes:
- Conversion happens once at insertion, not at read time, so this module
  is hot-path during transaction creates and CSV imports.
- Source is the Frankfurter API (no key, ECB rates, weekday cadence).
- If Frankfurter is unreachable, fall back to the most recent cached rate
  within 7 days. Older than 7 days → ValidationError, reject the transaction.
- ECB only quotes weekdays. Frankfurter handles weekend/holiday by returning
  the previous trading day's rate, so we don't need to special-case that.

Cache shape (one document per published rate date):

    fx_rates: {
      _id: ObjectId,
      base: "EUR",                      # always EUR — the ECB reference
      date: <UTC midnight Date>,        # the day Frankfurter returned
      rates: { "EUR": 1.0, "USD": 1.08, "RON": 4.97 },
      fetched_at: <Date>,
      source: "frankfurter" | "fallback"
    }

Cross-rate is derived as `rates[to] / rates[from]`. EUR is always present
(self-rate 1.0).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import requests
from pymongo import DESCENDING, UpdateOne

from app.extensions import mongo
from app.models.user import to_utc_naive, utcnow
from app.utils.errors import ValidationError

log = logging.getLogger(__name__)

# Frankfurter free, no key. https://api.frankfurter.dev/v1/latest is the canonical
# host as of 2025; the older `frankfurter.app` alias still resolves.
FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"

# Currencies the app supports. Pinned to keep `refresh_today()` deterministic
# and to match `SUPPORTED_CURRENCIES` on the frontend.
SUPPORTED = ("RON", "EUR", "USD")

# Cached rates older than this reject the transaction.
MAX_STALE_DAYS = 7

# HTTP timeout for live Frankfurter calls (seconds). Short enough to not stall
# a transaction insert; the cache fallback fires under the 7-day window if it
# expires.
HTTP_TIMEOUT = 5.0

# Generous timeout for the bulk timeseries endpoint — pulls hundreds of days
# in one shot, used by `prewarm_range` on base-currency change.
HTTP_TIMEOUT_RANGE = 30.0


def _midnight(d: datetime) -> datetime:
    n = to_utc_naive(d)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Cache primitives
# ---------------------------------------------------------------------------

def _read_cache(on_or_before: datetime) -> Optional[dict[str, Any]]:
    """The most recent cached rate row whose `date` is on or before `on_or_before`."""
    return mongo.db["fx_rates"].find_one(
        {"date": {"$lte": _midnight(on_or_before)}},
        sort=[("date", DESCENDING)],
    )


def _write_cache(date: datetime, rates: dict[str, float], source: str = "frankfurter") -> dict[str, Any]:
    doc = {
        "base": "EUR",
        "date": _midnight(date),
        "rates": {k: float(v) for k, v in rates.items()},
        "fetched_at": utcnow(),
        "source": source,
    }
    # Upsert by date — re-running the daily job mid-day shouldn't create dupes.
    mongo.db["fx_rates"].update_one(
        {"date": doc["date"]},
        {"$set": doc},
        upsert=True,
    )
    return doc


# ---------------------------------------------------------------------------
# Frankfurter HTTP
# ---------------------------------------------------------------------------

def _fetch_from_frankfurter(date: Optional[datetime] = None) -> dict[str, Any]:
    """Fetch ECB rates from Frankfurter for `date` (default: latest).

    Returns the parsed JSON unchanged. The caller is responsible for caching.
    """
    symbols = ",".join(c for c in SUPPORTED if c != "EUR")
    if date is None:
        url = f"{FRANKFURTER_BASE_URL}/latest"
    else:
        url = f"{FRANKFURTER_BASE_URL}/{date.strftime('%Y-%m-%d')}"
    params = {"base": "EUR", "symbols": symbols}
    res = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
    res.raise_for_status()
    data = res.json()
    if "rates" not in data or "date" not in data:
        raise RuntimeError(f"Unexpected Frankfurter payload: {data!r}")
    rates = dict(data["rates"])
    rates["EUR"] = 1.0  # ECB base; Frankfurter doesn't echo the self-rate
    return {"date": data["date"], "rates": rates}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refresh_today() -> dict[str, Any]:
    """Fetch today's rates from Frankfurter and upsert into the cache.

    Called by the daily APScheduler job and by `get_rate` when the cache miss is
    fresh enough that a live fetch is the right behavior.
    """
    payload = _fetch_from_frankfurter()
    rate_date = datetime.fromisoformat(payload["date"])
    return _write_cache(rate_date, payload["rates"], source="frankfurter")


def prewarm_range(start: datetime, end: datetime) -> int:
    """Bulk-cache ECB rates for `[start, end]` using Frankfurter's timeseries
    endpoint (`/v1/{from}..{to}`). One HTTP call covers the whole range.

    Used by the base-currency change handler: instead of N round-trips for
    N unique transaction dates, this pre-warms the cache so the subsequent
    per-tx `get_rate` calls all hit the local `fx_rates` collection.

    Best-effort: any Frankfurter error returns 0 and the per-tx fallback in
    `_ensure_rates_for` still works against whatever was already cached.

    Returns the number of rows upserted (= number of ECB trading days in
    the range; ECB skips weekends/holidays).
    """
    s = _midnight(start).date().isoformat()
    e = _midnight(end).date().isoformat()
    if s > e:
        return 0
    symbols = ",".join(c for c in SUPPORTED if c != "EUR")
    url = f"{FRANKFURTER_BASE_URL}/{s}..{e}"
    params = {"base": "EUR", "symbols": symbols}
    try:
        res = requests.get(url, params=params, timeout=HTTP_TIMEOUT_RANGE)
        res.raise_for_status()
        payload = res.json()
    except Exception as exc:  # noqa: BLE001 — best-effort, callers handle the miss
        log.warning("Frankfurter timeseries fetch failed for %s..%s: %s", s, e, exc)
        return 0
    rates_by_date = payload.get("rates")
    if not isinstance(rates_by_date, dict) or not rates_by_date:
        return 0

    now = utcnow()
    ops: list[UpdateOne] = []
    for date_str, day_rates in rates_by_date.items():
        try:
            rate_date = _midnight(datetime.fromisoformat(date_str))
        except ValueError:
            continue
        merged = {k: float(v) for k, v in day_rates.items()}
        merged["EUR"] = 1.0  # ECB self-rate; Frankfurter omits it
        ops.append(UpdateOne(
            {"date": rate_date},
            {"$set": {
                "base": "EUR",
                "date": rate_date,
                "rates": merged,
                "fetched_at": now,
                "source": "frankfurter",
            }},
            upsert=True,
        ))
    if not ops:
        return 0
    try:
        mongo.db["fx_rates"].bulk_write(ops, ordered=False)
    except Exception:  # noqa: BLE001 — degrade to per-row on backend quirks (e.g. mongomock)
        log.exception("fx_rates bulk_write failed; falling back to per-row upsert")
        for op in ops:
            # Re-derive the document from the UpdateOne payload — internal API
            # but stable enough in PyMongo 4.x. Safer than re-fetching.
            try:
                doc = op._doc["$set"]  # type: ignore[attr-defined]
                _write_cache(doc["date"], doc["rates"], source="frankfurter")
            except Exception:
                log.exception("fx_rates per-row upsert fallback failed")
    return len(ops)


def load_range_cache(start: datetime, end: datetime) -> dict[datetime, dict[str, float]]:
    """Read every cached `fx_rates` row whose date is in `[start, end]` with
    one Mongo query and return it as `{midnight_date: {"USD": 1.08, ...}}`.

    Companion to `prewarm_range`: after that pre-warm, the bulk recompute
    loop can resolve every per-tx rate from this dict instead of issuing
    a separate `find_one` per transaction. On Atlas M0 (~50 ms RTT) a
    700-tx loop drops from ~35 s to <1 s.
    """
    rows = mongo.db["fx_rates"].find(
        {"date": {"$gte": _midnight(start), "$lte": _midnight(end)}},
        {"date": 1, "rates": 1},
    )
    return {row["date"]: row["rates"] for row in rows}


def cross_rate_from_cache(
    cache: dict[datetime, dict[str, float]],
    from_ccy: str,
    to_ccy: str,
    on: datetime,
) -> Optional[float]:
    """Cross-rate `from_ccy → to_ccy` using a pre-built date→rates dict.

    Mirrors `_ensure_rates_for`'s "nearest row at or before target" rule
    (ECB skips weekends/holidays; Frankfurter returns the prior trading
    day for those). Returns None if the dict has nothing on/before
    `on` — caller falls back to the regular `get_rate` path.
    """
    if from_ccy == to_ccy:
        return 1.0
    target = _midnight(on)
    candidate_dates = [d for d in cache.keys() if d <= target]
    if not candidate_dates:
        return None
    rates = cache[max(candidate_dates)]
    if from_ccy not in rates or to_ccy not in rates:
        return None
    return float(rates[to_ccy]) / float(rates[from_ccy])


def _ensure_rates_for(date: datetime) -> dict[str, Any]:
    """Find a cached row valid for `date`, or fetch + cache if missing.

    For past dates we fetch the *historical* Frankfurter rate (so a tx from
    Jan 15 uses Jan 15's rate, not today's). For today / future the latest
    rate. If Frankfurter is unreachable, fall back to the most recent cached
    row within `MAX_STALE_DAYS` of `date`. Otherwise raise `ValidationError`.
    """
    target = _midnight(date)
    today = _midnight(utcnow())

    # 1. Cache hit: most recent row at-or-before target, within the staleness
    #    window. age_days >= 0 here because _read_cache filters to date <= target.
    cached = _read_cache(target)
    if cached is not None:
        age_days = (target - cached["date"]).days
        if age_days <= MAX_STALE_DAYS:
            return cached

    # 2. Cache miss or stale. Pick the right Frankfurter endpoint.
    try:
        if target >= today:
            return refresh_today()
        # Historical: fetch the specific date. Frankfurter handles weekends /
        # holidays by returning the previous trading day's rate.
        payload = _fetch_from_frankfurter(date=target)
        rate_date = datetime.fromisoformat(payload["date"])
        return _write_cache(rate_date, payload["rates"], source="frankfurter")
    except Exception as exc:  # noqa: BLE001 — network errors are expected
        log.warning("FX fetch failed for date=%s: %s", target.date(), exc)

    # 3. Last resort: any cache row within MAX_STALE_DAYS of target. We accept
    #    rows on either side of target here (we may have today's row when the
    #    user asks about a few days back) — the absolute distance is what
    #    matters relative to the staleness rule.
    cached = _read_cache(target)
    if cached is None:
        cached = mongo.db["fx_rates"].find_one(sort=[("date", DESCENDING)])
    if cached is None:
        raise ValidationError(
            "FX rate unavailable",
            details={"reason": "no_cache", "date": target.isoformat()},
        )
    age_days = abs((target - cached["date"]).days)
    if age_days > MAX_STALE_DAYS:
        raise ValidationError(
            "FX rate is stale",
            details={
                "reason": "stale_cache",
                "cache_date": cached["date"].isoformat(),
                "age_days": age_days,
                "max_stale_days": MAX_STALE_DAYS,
            },
        )
    return cached


def get_rate(from_ccy: str, to_ccy: str, on: Optional[datetime] = None) -> float:
    """Cross-rate `from_ccy → to_ccy`. `on` defaults to today."""
    from_ccy = from_ccy.upper()
    to_ccy = to_ccy.upper()
    if from_ccy == to_ccy:
        return 1.0
    if from_ccy not in SUPPORTED or to_ccy not in SUPPORTED:
        raise ValidationError(
            "Unsupported currency",
            details={"from": from_ccy, "to": to_ccy, "supported": list(SUPPORTED)},
        )
    cache = _ensure_rates_for(on or utcnow())
    rates = cache["rates"]
    if from_ccy not in rates or to_ccy not in rates:
        raise ValidationError(
            "Currency missing in cached rates",
            details={"from": from_ccy, "to": to_ccy, "cache_keys": list(rates.keys())},
        )
    # rates are EUR-based: 1 EUR = rates[X] X.
    # Cross: 1 from_ccy = (rates[to] / rates[from]) to_ccy.
    return float(rates[to_ccy]) / float(rates[from_ccy])


def convert(amount: float, from_ccy: str, to_ccy: str, on: Optional[datetime] = None) -> float:
    """Convert `amount` `from_ccy → to_ccy` using the rate valid on `on`."""
    return float(amount) * get_rate(from_ccy, to_ccy, on=on)
