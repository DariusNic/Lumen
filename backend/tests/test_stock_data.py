"""Stock data acquisition + persistence tests.

yfinance is the one network seam — every test mocks
`stock_data_service._yfinance_download` so the suite never reaches the
real Yahoo API. We build small pandas frames in the same shape yfinance
returns (MultiIndex columns for batched calls) so the slicing /
normalization paths are exercised end-to-end.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services import stock_data_service


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_frame(rows: dict[str, list[tuple[float, float, float, float, float]]],
                start: str = "2024-01-02") -> pd.DataFrame:
    """Build a yfinance-style multi-ticker frame.

    `rows` maps ticker -> list of (open, high, low, close, volume). Dates start
    at `start` and increment one calendar day per row (good enough for tests;
    we don't care about exchange calendars in fixtures).
    """
    if not rows:
        return pd.DataFrame()

    n = max(len(v) for v in rows.values())
    dates = pd.date_range(start=start, periods=n, freq="D")
    cols: list[tuple[str, str]] = []
    data: dict[tuple[str, str], list[float]] = {}
    for ticker, bars in rows.items():
        for field in ("Open", "High", "Low", "Close", "Volume"):
            cols.append((ticker, field))
        for i, field in enumerate(("Open", "High", "Low", "Close", "Volume")):
            data[(ticker, field)] = [b[i] if b is not None else float("nan") for b in bars]
    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_tuples(cols)
    return df


def _patch_download(frame: pd.DataFrame):
    return patch.object(stock_data_service, "_yfinance_download", return_value=frame)


# ---------------------------------------------------------------------------
# seed_history
# ---------------------------------------------------------------------------

def test_seed_writes_one_row_per_bar(client):
    from app.extensions import mongo

    frame = _make_frame({
        "AAPL": [(180, 182, 179, 181, 1_000_000), (181, 184, 180, 183, 1_200_000)],
        "MSFT": [(370, 372, 368, 371, 800_000),  (371, 375, 370, 374, 900_000)],
    })
    with _patch_download(frame):
        stats = stock_data_service.seed_history(["AAPL", "MSFT"], start="2024-01-02")

    assert stats["tickers_ok"] == 2
    assert stats["tickers_failed"] == 0
    assert stats["rows_written"] == 4
    assert mongo.db["stock_data"].count_documents({}) == 4


def test_seed_is_idempotent_on_ticker_date(client):
    """Running the seed twice on the same data must not duplicate rows."""
    from app.extensions import mongo

    frame = _make_frame({"AAPL": [(180, 182, 179, 181, 1_000_000)]})
    with _patch_download(frame):
        stock_data_service.seed_history(["AAPL"], start="2024-01-02")
        stock_data_service.seed_history(["AAPL"], start="2024-01-02")

    assert mongo.db["stock_data"].count_documents({}) == 1


def test_seed_drops_nan_bars(client):
    """yfinance backfills missing trading days as NaN — those rows must be
    dropped, not stored as zero-value bars."""
    from app.extensions import mongo

    frame = _make_frame({
        "AAPL": [
            (180, 182, 179, 181, 1_000_000),
            None,                               # all-NaN row
            (182, 185, 181, 184, 1_100_000),
        ],
    })
    with _patch_download(frame):
        stock_data_service.seed_history(["AAPL"], start="2024-01-02")

    assert mongo.db["stock_data"].count_documents({}) == 2


def test_seed_handles_failed_ticker_gracefully(client):
    """A ticker with no rows in the response is reported as failed but
    doesn't abort the rest of the batch."""
    from app.extensions import mongo

    frame = _make_frame({"AAPL": [(180, 182, 179, 181, 1_000_000)]})
    # Note MSFT is requested but absent from the response.
    with _patch_download(frame):
        stats = stock_data_service.seed_history(["AAPL", "MSFT"], start="2024-01-02")

    assert stats["tickers_ok"] == 1
    assert stats["tickers_failed"] == 1
    assert "MSFT" in stats["failed_list"]
    # Still wrote the AAPL bar.
    assert mongo.db["stock_data"].count_documents({"ticker": "AAPL"}) == 1


def test_seed_handles_brk_b_hyphen(client):
    """Berkshire Hathaway uses 'BRK-B' on Yahoo. The hyphen must round-trip
    through the fetcher and storage layer unchanged."""
    from app.extensions import mongo

    frame = _make_frame({"BRK-B": [(440, 442, 438, 441, 500_000)]})
    with _patch_download(frame):
        stats = stock_data_service.seed_history(["BRK-B"], start="2024-01-02")

    assert stats["tickers_ok"] == 1
    docs = list(mongo.db["stock_data"].find({"ticker": "BRK-B"}))
    assert len(docs) == 1
    assert docs[0]["ticker"] == "BRK-B"


def test_seed_empty_response_marks_all_failed(client):
    with _patch_download(pd.DataFrame()):
        stats = stock_data_service.seed_history(["AAPL", "MSFT"], start="2024-01-02")
    assert stats["tickers_ok"] == 0
    assert stats["tickers_failed"] == 2


# ---------------------------------------------------------------------------
# refresh_latest
# ---------------------------------------------------------------------------

def test_refresh_latest_upserts_new_bars(client):
    """refresh_latest is the daily job entry. New bars added; existing ones
    overwritten if Yahoo back-revises them."""
    from app.extensions import mongo

    seed = _make_frame({"AAPL": [(180, 182, 179, 181, 1_000_000)]}, start="2024-01-02")
    with _patch_download(seed):
        stock_data_service.seed_history(["AAPL"], start="2024-01-02")

    refresh = _make_frame({
        "AAPL": [
            (180, 182, 179, 181.50, 1_050_000),  # Jan 2 revised (close, volume changed)
            (181, 184, 180, 183, 1_200_000),     # Jan 3 new
        ],
    }, start="2024-01-02")
    with _patch_download(refresh):
        stats = stock_data_service.refresh_latest(["AAPL"])

    assert mongo.db["stock_data"].count_documents({"ticker": "AAPL"}) == 2
    jan2 = mongo.db["stock_data"].find_one({"ticker": "AAPL", "date": datetime(2024, 1, 2)})
    assert jan2 is not None
    assert jan2["close"] == 181.50  # back-revision picked up
    assert stats["rows_written"] >= 1


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def test_get_history_returns_sorted_dataframe(client):
    frame = _make_frame({
        "AAPL": [
            (180, 182, 179, 181, 1_000_000),
            (181, 184, 180, 183, 1_200_000),
            (183, 186, 182, 185, 1_300_000),
        ],
    }, start="2024-01-02")
    with _patch_download(frame):
        stock_data_service.seed_history(["AAPL"], start="2024-01-02")

    df = stock_data_service.get_history("AAPL")
    assert len(df) == 3
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    # Index is sorted ascending.
    assert df.index.is_monotonic_increasing
    # First close = 181, last close = 185.
    assert df["close"].iloc[0] == 181
    assert df["close"].iloc[-1] == 185


def test_get_history_empty_for_unknown_ticker(client):
    df = stock_data_service.get_history("NOPE")
    assert df.empty
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]


def test_latest_bar(client):
    frame = _make_frame({
        "AAPL": [
            (180, 182, 179, 181, 1_000_000),
            (181, 184, 180, 183, 1_200_000),
        ],
    }, start="2024-01-02")
    with _patch_download(frame):
        stock_data_service.seed_history(["AAPL"], start="2024-01-02")

    latest = stock_data_service.latest_bar("AAPL")
    assert latest is not None
    assert latest["close"] == 183  # the second (later) bar


def test_known_tickers_returns_distinct_sorted(client):
    frame = _make_frame({
        "MSFT": [(370, 372, 368, 371, 800_000)],
        "AAPL": [(180, 182, 179, 181, 1_000_000)],
        "NVDA": [(900, 905, 895, 902, 500_000)],
    }, start="2024-01-02")
    with _patch_download(frame):
        stock_data_service.seed_history(["AAPL", "MSFT", "NVDA"], start="2024-01-02")

    assert stock_data_service.known_tickers() == ["AAPL", "MSFT", "NVDA"]


# ---------------------------------------------------------------------------
# TICKERS constant
# ---------------------------------------------------------------------------

def test_tickers_constant_has_exactly_100_unique(client):
    from app.utils.constants import TICKERS
    assert len(TICKERS) == 100
    assert len(set(TICKERS)) == 100
    # BRK-B is the canonical Yahoo format — confirm we kept the hyphen.
    assert "BRK-B" in TICKERS
    assert "BRK.B" not in TICKERS
