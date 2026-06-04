"""Stock data + signal Pydantic models.

`stock_data` rows are OHLCV bars from yfinance, one per (ticker, date). The
collection is global (not user-scoped) — every user reads the same underlying
prices. Compound unique index on (ticker, date) is in `app/utils/db.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


SignalLabel = Literal["BUY", "HOLD", "SELL"]


class OHLCVBar(BaseModel):
    """One day's price bar. Stored verbatim in `stock_data`."""

    ticker: str = Field(min_length=1, max_length=10)
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float  # float not int — yfinance occasionally returns NaN-coerced floats

    model_config = ConfigDict(from_attributes=True)


class TickerSummary(BaseModel):
    """Compact view returned by `GET /api/stocks` (lands in Turn C)."""

    ticker: str
    last_close: float
    last_date: datetime
    change_1d_pct: Optional[float] = None
    change_5d_pct: Optional[float] = None


class SignalOutput(BaseModel):
    """Returned by `GET /api/stocks/:ticker/signal` (lands in Turn C)."""

    ticker: str
    as_of: datetime
    label: SignalLabel
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[SignalLabel, float]
    explanation: str
