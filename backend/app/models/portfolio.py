"""Paper-trading portfolio Pydantic models.

The portfolio is denominated in **USD**. The frontend converts to the
user's base currency at display time via `useCurrency()` — we never store
a pre-converted balance here.

Two collections back this:

  `portfolios`         one document per user. Holds cash, holdings, and the
                       audit trail of buy/sell operations as embedded items.
  `portfolio_trades`   append-only log of every buy/sell, even reversed
                       ones. Used by `GET /api/portfolio/history` to
                       reconstruct the equity curve and by Chapter 4 for
                       audit-trail demos.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TradeSide = Literal["buy", "sell", "deposit", "withdrawal"]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
# Soft sanity cap on funds adjustments — a $1M typo shouldn't quietly land
# in the user's portfolio.
_MAX_FUNDS_USD = 1_000_000.0


class TradeCreate(BaseModel):
    """Inbound payload for `POST /api/portfolio/buy` and `/sell`."""

    ticker: str = Field(min_length=1, max_length=10)
    qty: PositiveFloat   # paper-trading allows fractional shares


FundsDirection = Literal["deposit", "withdrawal"]


class FundsAdjust(BaseModel):
    """Inbound payload for `POST /api/portfolio/funds`. The user picks
    `direction` explicitly (deposit / withdrawal) and supplies a positive
    `amount_usd`. We deliberately don't allow a signed amount so a stray
    minus sign in the UI can't deposit instead of withdraw."""

    direction: FundsDirection
    amount_usd: float = Field(gt=0, le=_MAX_FUNDS_USD, allow_inf_nan=False)


class HoldingPublic(BaseModel):
    ticker: str
    qty: float
    avg_cost: float
    last_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None


class TradePublic(BaseModel):
    id: str
    date: datetime
    ticker: str
    side: TradeSide
    qty: float
    price: float
    total: float
    realized_pnl: Optional[float] = None  # populated for sells only
    # For deposit/withdrawal rows: `ticker` is the constant "CASH",
    # `qty` is 1, `price` and `total` both equal the USD amount moved.
    # The frontend renders these with a distinct label/icon instead of
    # treating them as a trade.

    model_config = ConfigDict(from_attributes=True)


class PortfolioPublic(BaseModel):
    """Returned by `GET /api/portfolio`. Every monetary field is USD."""

    cash_usd: float
    initial_cash_usd: float
    holdings: list[HoldingPublic]
    market_value_usd: float           # sum of (qty × last_price) over holdings
    total_value_usd: float            # cash + market_value
    cost_basis_usd: float             # sum of (qty × avg_cost) over holdings
    unrealized_pnl_usd: float         # market_value - cost_basis
    unrealized_pnl_pct: float         # vs cost_basis
    total_return_usd: float           # total_value - initial_cash
    total_return_pct: float
    trade_count: int
    created_at: datetime
    reset_at: Optional[datetime]      # last reset; None for new portfolios


class EquityPoint(BaseModel):
    """One row of the equity curve."""

    date: datetime
    cash_usd: float
    market_value_usd: float
    total_value_usd: float


class PortfolioHistory(BaseModel):
    """Returned by `GET /api/portfolio/history?range=...`."""

    range: Literal["1M", "3M", "6M", "1Y", "ALL"]
    points: list[EquityPoint]
    initial_cash_usd: float
