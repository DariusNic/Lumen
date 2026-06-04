"""Stock OHLCV data acquisition + persistence.

yfinance is the primary source. Data lives globally in `stock_data` keyed
by `(ticker, date)`. The unique compound index in
`app/utils/db.py` lets us upsert idempotently — running the seed twice
or re-fetching the same day's bar overwrites instead of duplicating.

This module is a *service*: no Flask imports, no API knowledge. It's called
by the seed CLI (one-shot 5-year pull), the daily APScheduler refresh job
(yesterday's bar for every ticker), and by tests.

Edge cases the fetcher handles:
- **BRK-B and other hyphenated tickers** — Yahoo's canonical format. We
  pass them through verbatim; the fetcher uses Yahoo formats for both
  storage and lookup.
- **Per-ticker failures** — yfinance occasionally returns an empty frame
  for a ticker (delisted, rate-limited, transient). Those tickers are
  logged and skipped, not raised, so one bad ticker doesn't kill a
  100-ticker batch.
- **NaN bars** — Yahoo backfills missing days as NaN. We drop rows where
  any of OHLCV is NaN before insert.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.models.user import utcnow as _utcnow
from typing import Any, Iterable, Optional

import pandas as pd
from pymongo import ASCENDING, DESCENDING

from app.extensions import mongo
from app.models.user import to_utc_naive
from app.utils.constants import TICKERS, TRAIN_DATA_START

log = logging.getLogger(__name__)

# NYSE trading day closes at 16:00 America/New_York year-round; yfinance
# needs ~30min after close before its daily bar reflects settled values.
# Used by `_is_partial_intraday` to drop today's in-progress bar from any
# mid-session refresh (boot catch-up while markets are open).
_NYSE_TZ = ZoneInfo("America/New_York")
_NYSE_FINAL_HOUR = 16
_NYSE_FINAL_MINUTE = 30


def _is_partial_intraday(bar_ts: Any) -> bool:
    """True iff `bar_ts` is today's NYSE trading day and the session
    hasn't yet finalized.

    yfinance, called mid-session via `period="5d"`, includes a partial bar
    for the day-in-progress (running OHLC + partial volume). That bar must
    not land in `stock_data`: training and the cached predictions assume
    finalized bars only. At 21:30 UTC (cron firing time) NY is past the
    16:30 cutoff in both EDT and EST, so this check is a no-op for the
    cron and only filters the boot catch-up path.
    """
    now_ny = datetime.now(tz=_NYSE_TZ)
    bar_date = bar_ts.date() if hasattr(bar_ts, "date") else bar_ts
    if bar_date != now_ny.date():
        return False
    cutoff = now_ny.replace(
        hour=_NYSE_FINAL_HOUR, minute=_NYSE_FINAL_MINUTE,
        second=0, microsecond=0,
    )
    return now_ny < cutoff


def _normalize_bar_row(ticker: str, ts: pd.Timestamp, row: pd.Series) -> Optional[dict[str, Any]]:
    """Convert one yfinance row to a Mongo document. Returns None if any field
    is NaN (Yahoo backfills missing trading days as NaN, which we drop)."""
    try:
        open_ = float(row["Open"])
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = float(row["Volume"])
    except (KeyError, TypeError, ValueError):
        return None
    # NaN check — float comparisons are fine; pandas/numpy NaN != NaN.
    for v in (open_, high, low, close, volume):
        if v != v:  # noqa: PLR0124 — canonical NaN test, intentional
            return None

    py_date = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    return {
        "ticker": ticker,
        "date": to_utc_naive(py_date) if isinstance(py_date, datetime) else py_date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _yfinance_download(
    tickers: Iterable[str],
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: Optional[str] = None,
):
    """Thin wrapper so tests can monkey-patch this single seam.

    Returns whatever `yf.download` returns — pandas DataFrame with a
    MultiIndex column (level 0 = field, level 1 = ticker) for multi-ticker
    requests, or a single-level column DataFrame for one ticker.
    """
    import yfinance as yf  # imported lazily so the rest of the app doesn't pay the cost

    kwargs: dict[str, Any] = {
        "tickers": list(tickers),
        "auto_adjust": True,        # split + dividend adjusted closes
        "progress": False,
        "group_by": "ticker",        # column shape: ticker → field, easier to slice
        "threads": True,
    }
    if period is not None:
        kwargs["period"] = period
    if start is not None:
        kwargs["start"] = start
    if end is not None:
        kwargs["end"] = end
    return yf.download(**kwargs)


def _frame_for_ticker(df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Slice the per-ticker sub-frame out of the multi-ticker batch result.

    `yf.download(group_by="ticker")` returns columns like
    `(ticker, "Close")` for many tickers, or a flat `Close` for one. We
    handle both shapes so a 1-ticker call still works.
    """
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        if ticker not in df.columns.get_level_values(0):
            return None
        sub = df[ticker]
    else:
        sub = df
    if sub.empty or "Close" not in sub.columns:
        return None
    return sub.dropna(how="all")


def _persist(rows: list[dict[str, Any]], *, prefer_insert: bool = False) -> int:
    """Persist OHLCV rows on (ticker, date). Returns the number written.

    Two paths:
      - `prefer_insert=True` (seed) — try `insert_many(ordered=False)`. Most
        rows in a fresh seed are new, and bulk insert is ~10× faster against
        Atlas than per-row updates. Duplicate-key errors are swallowed (the
        unique index protects against dupes; we tolerate the error and count
        only the rows that landed).
      - `prefer_insert=False` (refresh) — per-row `update_one` upsert. Slower
        but updates back-revised bars. The daily refresh batch is ~100 rows
        so the difference doesn't matter.

    Why not `bulk_write`: mongomock's bridge doesn't accept the `sort` kwarg
    pymongo's `BulkWriteResult` adds; we'd need conditional code paths.
    `insert_many` works in both worlds.
    """
    if not rows:
        return 0
    coll = mongo.db["stock_data"]

    if prefer_insert:
        try:
            res = coll.insert_many(rows, ordered=False)
            return len(res.inserted_ids)
        except Exception as exc:  # noqa: BLE001
            # `BulkWriteError` from real PyMongo, plain Exception from mongomock.
            # The `details` dict (real PyMongo) carries `nInserted` so we can
            # report how many rows actually landed despite the dupe-key conflicts.
            details = getattr(exc, "details", None) or {}
            n_inserted = details.get("nInserted")
            if n_inserted is not None:
                return int(n_inserted)
            # Mongomock or any backend without `details` — fall through to a
            # per-row update path so the call is at least correct.
            log.info("insert_many returned %s; falling back to per-row upsert", type(exc).__name__)

    written = 0
    for r in rows:
        res = coll.update_one(
            {"ticker": r["ticker"], "date": r["date"]},
            {"$set": r},
            upsert=True,
        )
        if res.upserted_id is not None or res.modified_count > 0:
            written += 1
    return written


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def seed_history(
    tickers: Optional[Iterable[str]] = None,
    *,
    start: str = TRAIN_DATA_START,
    end: Optional[str] = None,
) -> dict[str, Any]:
    """One-shot historical backfill. Default training window starts 2019-01-01.

    Returns a counter dict: {tickers_total, tickers_ok, tickers_failed, rows_written}.
    Per-ticker failures are logged and skipped; the batch never aborts.
    """
    tickers = list(tickers) if tickers is not None else list(TICKERS)
    if end is None:
        end = _utcnow().strftime("%Y-%m-%d")
    log.info("Seeding %s tickers %s → %s", len(tickers), start, end)

    df = _yfinance_download(tickers, start=start, end=end)

    rows: list[dict[str, Any]] = []
    ok = 0
    failed: list[str] = []
    for t in tickers:
        sub = _frame_for_ticker(df, t)
        if sub is None or sub.empty:
            failed.append(t)
            log.warning("yfinance returned no data for %s", t)
            continue
        added = 0
        for ts, row in sub.iterrows():
            doc = _normalize_bar_row(t, ts, row)
            if doc is not None:
                rows.append(doc)
                added += 1
        if added > 0:
            ok += 1
        else:
            failed.append(t)

    written = _persist(rows, prefer_insert=True)
    return {
        "tickers_total": len(tickers),
        "tickers_ok": ok,
        "tickers_failed": len(failed),
        "failed_list": failed,
        "rows_written": written,
    }


def refresh_latest(tickers: Optional[Iterable[str]] = None) -> dict[str, Any]:
    """Fetch the most recent N days for each ticker and upsert. Used by the
    daily APScheduler job; period='5d' is enough to cover weekend/holiday
    gaps and re-write any back-revised bars.

    Today's in-progress bar is filtered out via `_is_partial_intraday`
    when called mid-session (boot catch-up path). The 21:30 UTC cron
    fires past NYSE close + buffer, so the filter is a no-op there.
    """
    tickers = list(tickers) if tickers is not None else list(TICKERS)
    df = _yfinance_download(tickers, period="5d")

    rows: list[dict[str, Any]] = []
    ok = 0
    failed: list[str] = []
    skipped_partial = 0
    for t in tickers:
        sub = _frame_for_ticker(df, t)
        if sub is None or sub.empty:
            failed.append(t)
            continue
        for ts, row in sub.iterrows():
            if _is_partial_intraday(ts):
                skipped_partial += 1
                continue
            doc = _normalize_bar_row(t, ts, row)
            if doc is not None:
                rows.append(doc)
        ok += 1
    if skipped_partial:
        log.info(
            "refresh_latest: skipped %s partial intraday bars (NYSE session open)",
            skipped_partial,
        )

    written = _persist(rows)
    return {
        "tickers_total": len(tickers),
        "tickers_ok": ok,
        "tickers_failed": len(failed),
        "failed_list": failed,
        "rows_written": written,
    }


# ---------------------------------------------------------------------------
# Read helpers (used by features.py + endpoint code in Turns A2/B/C)
# ---------------------------------------------------------------------------

def get_history(
    ticker: str,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Pull a ticker's OHLCV history into a pandas DataFrame, sorted ascending
    by date. Returns an empty frame (with the right columns) when the ticker
    has no rows yet."""
    filt: dict[str, Any] = {"ticker": ticker}
    if start or end:
        date_clause: dict[str, Any] = {}
        if start:
            date_clause["$gte"] = to_utc_naive(start)
        if end:
            date_clause["$lte"] = to_utc_naive(end)
        filt["date"] = date_clause
    cursor = mongo.db["stock_data"].find(
        filt,
        projection={"_id": 0, "date": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
    ).sort("date", ASCENDING)
    if limit is not None:
        cursor = cursor.limit(limit)
    docs = list(cursor)
    if not docs:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(docs)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def latest_bar(ticker: str) -> Optional[dict[str, Any]]:
    """Return the most recent bar for `ticker`, or None if no data."""
    return mongo.db["stock_data"].find_one(
        {"ticker": ticker},
        sort=[("date", DESCENDING)],
        projection={"_id": 0},
    )


# ---------------------------------------------------------------------------
# Live intraday quote — used by portfolio P&L during the trading day so the
# user sees price movement before the next daily cron fires at 21:30 UTC.
# Cached for 5 minutes per ticker to keep yfinance call volume reasonable.
# ---------------------------------------------------------------------------

_QUOTE_CACHE: dict[str, tuple[float, datetime]] = {}
_QUOTE_TTL_SECONDS = 300


def live_quote(ticker: str) -> Optional[float]:
    """Most recent traded price for `ticker` — intraday when available, else
    falls back to the latest daily close. Used by portfolio_service when
    computing current value / P&L so the user sees a moving number even
    before the daily refresh cron runs.

    Cached per ticker for 5 minutes. The cache is process-local; an in-process
    cache is fine because the application runs as a single Flask process.
    yfinance failures (rate limit, network) fall back to the daily close.
    """
    now = datetime.now(timezone.utc)
    cached = _QUOTE_CACHE.get(ticker)
    if cached and (now - cached[1]).total_seconds() < _QUOTE_TTL_SECONDS:
        return cached[0]

    price: Optional[float] = None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.fast_info
        for key in ("last_price", "regular_market_price", "previous_close"):
            v = info.get(key) if hasattr(info, "get") else getattr(info, key, None)
            if v is not None and v == v and v > 0:
                price = float(v)
                break
        if price is None:
            df = yf.download(ticker, period="1d", interval="1h",
                             auto_adjust=False, progress=False)
            if df is not None and not df.empty:
                close_col = None
                if isinstance(df.columns, pd.MultiIndex):
                    if ("Close", ticker) in df.columns:
                        close_col = df[("Close", ticker)]
                    elif "Close" in df.columns.get_level_values(0):
                        sub = df["Close"]
                        close_col = sub.iloc[:, 0] if hasattr(sub, "iloc") and sub.ndim == 2 else sub
                elif "Close" in df.columns:
                    close_col = df["Close"]
                if close_col is not None and not close_col.empty:
                    v_raw = close_col.iloc[-1]
                    if hasattr(v_raw, "item"):
                        v = float(v_raw.item())
                    else:
                        v = float(v_raw)
                    if v == v and v > 0:
                        price = v
    except Exception:
        log.exception("live_quote yfinance call failed for %s", ticker)

    if price is None:
        bar = latest_bar(ticker)
        price = float(bar["close"]) if bar else None

    if price is not None:
        _QUOTE_CACHE[ticker] = (price, now)
    return price


def known_tickers() -> list[str]:
    """Distinct tickers present in `stock_data`. Source of truth for the
    `GET /api/stocks` endpoint (Turn C) so we never advertise a ticker we
    can't actually price."""
    return sorted(mongo.db["stock_data"].distinct("ticker"))
