"""Paper-trading portfolio service.

Money in this module is always in USD. The frontend converts to the user's
base currency via `useCurrency()` at display time.

Execution model:
  - Every buy/sell executes at the **last known close** for the ticker. We
    never simulate intra-day execution — the test universe is daily bars
    and that's the price the model trains on, so trading should match.
  - Fractional shares allowed. Paper trading isn't trying to match real
    broker constraints; it's giving the user a clear view of what their
    AI-signal-driven decisions would have produced.
  - No commissions, no slippage. Documented as a Chapter 5 limitation —
    real-world performance would be lower.

Realized P&L on sells uses **FIFO (First-In-First-Out)** lot accounting.
Each buy appends a new lot `{qty, cost_per_share, bought_at}` to the
holding. A sell consumes lots starting with the **oldest** one,
computing per-lot realized P&L = `(sell_price - lot.cost_per_share) ×
consumed_qty` and summing across the lots it touches.

FIFO is the IRS default for unspecified-lot stock sales and what most
US retail brokerages use by default. It gives intuitive attribution
in the trade-history view: a sell "consumes" the oldest position, so
the realized gain shows up on the sell that actually disposed of the
appreciated shares.

Tradeoff: a same-day buy-then-sell at the same price will show a
small non-zero realized P&L if the user already held older cheaper
shares of the same ticker — because accounting treats shares as
fungible once mixed in a holding ("you sold 1 of your N shares,
oldest first"), not as a wash trade against the just-added lot.

The display fields `qty` and `avg_cost` on each holding are still
maintained as the sum and weighted-average across `lots` so the UI keeps
showing one row per ticker.

Two collections:
  `portfolios`         — one doc per user. Holds cash + a list of holdings.
  `portfolio_trades`   — append-only log used by `GET /history` and Chapter 4.

The `accounts.Paper Portfolio` row's balance is recomputed live by
`account_service` whenever it's read; this service only writes to the
`portfolios` and `portfolio_trades` collections.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING

from app.extensions import mongo
from app.models.portfolio import (
    EquityPoint,
    HoldingPublic,
    PortfolioHistory,
    PortfolioPublic,
    TradePublic,
)
from app.models.user import to_utc_naive, utcnow
from app.services import stock_data_service
from app.utils.constants import INITIAL_PORTFOLIO_CASH_USD, TICKERS
from app.utils.errors import NotFoundError, ValidationError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed (auto-create portfolio at registration, idempotent on login)
# ---------------------------------------------------------------------------

def seed_for_user(user_id: str) -> None:
    """Create an empty $10k portfolio if the user doesn't have one yet.

    Idempotent — safe to call on every login as a self-healing backfill for
    accounts that pre-date the portfolio feature.
    """
    coll = mongo.db["portfolios"]
    if coll.count_documents({"user_id": ObjectId(user_id)}, limit=1) > 0:
        return
    now = utcnow()
    coll.insert_one({
        "user_id": ObjectId(user_id),
        "cash_usd": float(INITIAL_PORTFOLIO_CASH_USD),
        "initial_cash_usd": float(INITIAL_PORTFOLIO_CASH_USD),
        "holdings": [],   # [{ticker, qty, avg_cost, first_bought}]
        "trade_count": 0,
        "created_at": now,
        "reset_at": None,
    })


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _portfolio_for(user_id: str) -> dict[str, Any]:
    doc = mongo.db["portfolios"].find_one({"user_id": ObjectId(user_id)})
    if doc is None:
        # Self-heal: a user who registered before the portfolio feature
        # landed will hit this on first call. Create + retry.
        seed_for_user(user_id)
        doc = mongo.db["portfolios"].find_one({"user_id": ObjectId(user_id)})
    assert doc is not None
    return doc


def _last_price(ticker: str) -> Optional[float]:
    """Most recent traded price for portfolio valuation. Prefers a live
    intraday quote (with a 5-minute cache) so the user's P&L can move
    during the trading day, even before the daily refresh cron at 21:00
    UTC writes the new daily close. Falls back to the most recent daily
    close when yfinance is unreachable."""
    quote = stock_data_service.live_quote(ticker)
    if quote is not None:
        return quote
    bar = stock_data_service.latest_bar(ticker)
    return float(bar["close"]) if bar else None


def _validate_ticker(ticker: str) -> str:
    """Normalize + check the ticker is in the configured universe."""
    t = ticker.strip().upper()
    if t not in TICKERS:
        raise ValidationError(
            "Ticker not in tracked universe",
            details={"ticker": t, "supported": "see TICKERS in app/utils/constants.py"},
        )
    return t


def _holdings_index(holdings: list[dict[str, Any]]) -> dict[str, int]:
    return {h["ticker"]: i for i, h in enumerate(holdings)}


def _ensure_lots(h: dict[str, Any]) -> list[dict[str, Any]]:
    """Lazy migration: older portfolio docs only have `qty`/`avg_cost`/
    `first_bought` per holding. Materialize them into a single synthetic
    LIFO lot so the rest of the code can work uniformly. Idempotent —
    if `lots` already exists it's returned unchanged.
    """
    lots = h.get("lots")
    if lots:
        return list(lots)
    synthetic = [{
        "qty": float(h.get("qty", 0)),
        "cost_per_share": float(h.get("avg_cost", 0)),
        "bought_at": h.get("first_bought", utcnow()),
    }]
    h["lots"] = synthetic
    return synthetic


def _recompute_from_lots(h: dict[str, Any]) -> None:
    """Refresh the derived `qty` + `avg_cost` view fields from the lot list."""
    lots = h.get("lots", [])
    total_qty = sum(float(l["qty"]) for l in lots)
    if total_qty <= 1e-9:
        h["qty"] = 0.0
        h["avg_cost"] = 0.0
        return
    cost_basis = sum(float(l["qty"]) * float(l["cost_per_share"]) for l in lots)
    h["qty"] = total_qty
    h["avg_cost"] = cost_basis / total_qty


# ---------------------------------------------------------------------------
# Buy / sell
# ---------------------------------------------------------------------------

def buy(user_id: str, ticker: str, qty: float) -> TradePublic:
    """Execute a paper buy of `qty` shares of `ticker` at the latest close.

    Raises:
      - `ValidationError` if ticker unknown, qty ≤ 0, or insufficient cash.
      - `NotFoundError`  if the ticker has no seeded price data.
    """
    if qty <= 0:
        raise ValidationError("Quantity must be positive", details={"qty": qty})
    ticker = _validate_ticker(ticker)
    price = _last_price(ticker)
    if price is None:
        raise NotFoundError(
            "No price data for ticker — run the seed or daily refresh first.",
            details={"ticker": ticker},
        )
    total = float(qty) * float(price)

    portfolio = _portfolio_for(user_id)
    if portfolio["cash_usd"] < total:
        raise ValidationError(
            "Insufficient cash",
            details={
                "needed": round(total, 2),
                "available": round(portfolio["cash_usd"], 2),
            },
        )

    # LIFO lot accounting: each buy appends a new lot. The `qty` and
    # `avg_cost` fields on the holding are derived (sum / weighted mean
    # across lots) so the existing read paths and UI display contract
    # stay unchanged.
    holdings = list(portfolio.get("holdings", []))
    idx_map = _holdings_index(holdings)
    now = utcnow()
    new_lot = {"qty": float(qty), "cost_per_share": float(price), "bought_at": now}
    if ticker in idx_map:
        h = holdings[idx_map[ticker]]
        lots = _ensure_lots(h)
        lots.append(new_lot)
        h["lots"] = lots
        _recompute_from_lots(h)
    else:
        holdings.append({
            "ticker": ticker,
            "qty": float(qty),
            "avg_cost": float(price),
            "first_bought": now,
            "lots": [new_lot],
        })

    new_cash = float(portfolio["cash_usd"]) - total
    mongo.db["portfolios"].update_one(
        {"user_id": ObjectId(user_id)},
        {
            "$set": {
                "cash_usd": new_cash,
                "holdings": holdings,
            },
            "$inc": {"trade_count": 1},
        },
    )
    trade_doc = {
        "user_id": ObjectId(user_id),
        "date": now,
        "ticker": ticker,
        "side": "buy",
        "qty": float(qty),
        "price": float(price),
        "total": total,
        "realized_pnl": None,
    }
    res = mongo.db["portfolio_trades"].insert_one(trade_doc)
    trade_doc["_id"] = res.inserted_id
    return _trade_public(trade_doc)


def sell(user_id: str, ticker: str, qty: float) -> TradePublic:
    """Execute a paper sell. Average-cost realized P&L."""
    if qty <= 0:
        raise ValidationError("Quantity must be positive", details={"qty": qty})
    ticker = _validate_ticker(ticker)
    price = _last_price(ticker)
    if price is None:
        raise NotFoundError(
            "No price data for ticker — run the seed or daily refresh first.",
            details={"ticker": ticker},
        )

    portfolio = _portfolio_for(user_id)
    holdings = list(portfolio.get("holdings", []))
    idx_map = _holdings_index(holdings)
    if ticker not in idx_map:
        raise ValidationError(
            "You don't hold this ticker",
            details={"ticker": ticker},
        )
    h = holdings[idx_map[ticker]]
    if float(qty) - float(h["qty"]) > 1e-9:
        raise ValidationError(
            "Insufficient shares",
            details={
                "ticker": ticker,
                "holding": float(h["qty"]),
                "requested": float(qty),
            },
        )

    total = float(qty) * float(price)

    # FIFO sell: consume from the oldest lots first. Matches the IRS default
    # for stock sales and what most US retail brokers use by default. The
    # realized gain attaches to the sell that actually disposed of the
    # appreciated shares — intuitive in the trade-history view.
    lots = _ensure_lots(h)
    lots_sorted = sorted(lots, key=lambda l: l["bought_at"])
    remaining_to_sell = float(qty)
    realized = 0.0
    new_lots: list[dict[str, Any]] = []
    for lot in lots_sorted:
        lot_qty = float(lot["qty"])
        if remaining_to_sell <= 1e-9:
            new_lots.append(lot)
            continue
        consume = min(lot_qty, remaining_to_sell)
        realized += (float(price) - float(lot["cost_per_share"])) * consume
        remaining_to_sell -= consume
        leftover = lot_qty - consume
        if leftover > 1e-9:
            new_lots.append({
                "qty": leftover,
                "cost_per_share": float(lot["cost_per_share"]),
                "bought_at": lot["bought_at"],
            })
    # Restore the original chronological order on disk (oldest first) so
    # future LIFO sells can still sort deterministically.
    new_lots.sort(key=lambda l: l["bought_at"])
    h["lots"] = new_lots
    _recompute_from_lots(h)

    if h["qty"] <= 1e-9:
        # Position closed — drop the holding entirely.
        holdings.pop(idx_map[ticker])

    new_cash = float(portfolio["cash_usd"]) + total
    now = utcnow()
    mongo.db["portfolios"].update_one(
        {"user_id": ObjectId(user_id)},
        {
            "$set": {
                "cash_usd": new_cash,
                "holdings": holdings,
            },
            "$inc": {"trade_count": 1},
        },
    )
    trade_doc = {
        "user_id": ObjectId(user_id),
        "date": now,
        "ticker": ticker,
        "side": "sell",
        "qty": float(qty),
        "price": float(price),
        "total": total,
        "realized_pnl": realized,
    }
    res = mongo.db["portfolio_trades"].insert_one(trade_doc)
    trade_doc["_id"] = res.inserted_id
    return _trade_public(trade_doc)


# ---------------------------------------------------------------------------
# Read paths
# ---------------------------------------------------------------------------

def _trade_public(doc: dict[str, Any]) -> TradePublic:
    return TradePublic(
        id=str(doc["_id"]),
        date=doc["date"],
        ticker=doc["ticker"],
        side=doc["side"],
        qty=float(doc["qty"]),
        price=float(doc["price"]),
        total=float(doc["total"]),
        realized_pnl=(float(doc["realized_pnl"]) if doc.get("realized_pnl") is not None else None),
    )


def get_portfolio(user_id: str) -> PortfolioPublic:
    """Return current state with mark-to-market valuations."""
    portfolio = _portfolio_for(user_id)
    holdings_pub: list[HoldingPublic] = []
    market_value = 0.0
    cost_basis = 0.0
    for h in portfolio.get("holdings", []):
        last = _last_price(h["ticker"])
        qty = float(h["qty"])
        avg = float(h["avg_cost"])
        cost = qty * avg
        cost_basis += cost
        if last is not None:
            mv = qty * last
            market_value += mv
            pnl = mv - cost
            pnl_pct = (pnl / cost * 100) if cost else 0.0
            holdings_pub.append(HoldingPublic(
                ticker=h["ticker"], qty=qty, avg_cost=avg,
                last_price=last, market_value=round(mv, 2),
                unrealized_pnl=round(pnl, 2), unrealized_pnl_pct=round(pnl_pct, 2),
            ))
        else:
            holdings_pub.append(HoldingPublic(
                ticker=h["ticker"], qty=qty, avg_cost=avg,
            ))

    cash = float(portfolio["cash_usd"])
    initial = float(portfolio["initial_cash_usd"])
    total_value = cash + market_value
    total_return = total_value - initial
    return PortfolioPublic(
        cash_usd=round(cash, 2),
        initial_cash_usd=round(initial, 2),
        holdings=holdings_pub,
        market_value_usd=round(market_value, 2),
        total_value_usd=round(total_value, 2),
        cost_basis_usd=round(cost_basis, 2),
        unrealized_pnl_usd=round(market_value - cost_basis, 2),
        unrealized_pnl_pct=round((market_value - cost_basis) / cost_basis * 100, 2) if cost_basis else 0.0,
        total_return_usd=round(total_return, 2),
        total_return_pct=round(total_return / initial * 100, 2) if initial else 0.0,
        trade_count=int(portfolio.get("trade_count", 0)),
        created_at=portfolio["created_at"],
        reset_at=portfolio.get("reset_at"),
    )


def list_trades(user_id: str, limit: int = 200) -> list[TradePublic]:
    # Secondary sort by `_id` desc breaks the tie when two trades share the
    # same millisecond timestamp — ObjectIds are monotonically increasing
    # within a process, so this gives a stable insertion-order fallback.
    cursor = mongo.db["portfolio_trades"].find(
        {"user_id": ObjectId(user_id)},
    ).sort([("date", -1), ("_id", -1)]).limit(limit)
    return [_trade_public(d) for d in cursor]


# ---------------------------------------------------------------------------
# History — reconstruct equity curve from the trade log + price history
# ---------------------------------------------------------------------------

_RANGE_DAYS: dict[str, Optional[int]] = {
    "1M": 31, "3M": 92, "6M": 183, "1Y": 366, "ALL": None,
}


def _midnight(d: datetime) -> datetime:
    return to_utc_naive(d).replace(hour=0, minute=0, second=0, microsecond=0)


def history(user_id: str, range_key: str = "3M") -> PortfolioHistory:
    """Reconstruct one equity-curve point per calendar day in the requested
    range, walking the trade log forward and looking up close prices.

    Algorithm:
      1. Pull all trades sorted ascending.
      2. Determine the date window: from max(portfolio.created_at, today − range)
         to today.
      3. For each day in the window, replay any trades that landed on/before
         it to get cash + holdings as of EOD.
      4. Look up that day's close price for each holding and compute
         total_value = cash + Σ(qty × close).

    O(days × tickers_held) Mongo lookups. For a 90-day chart with ≤ 10
    holdings, that's < 1000 small reads — comfortably fast.
    """
    if range_key not in _RANGE_DAYS:
        raise ValidationError(
            "Invalid `range`",
            details={"value": range_key, "allowed": sorted(_RANGE_DAYS)},
        )
    portfolio = _portfolio_for(user_id)
    initial = float(portfolio["initial_cash_usd"])

    today = _midnight(utcnow())
    days = _RANGE_DAYS[range_key]
    floor = portfolio["created_at"] if portfolio.get("reset_at") is None else portfolio["reset_at"]
    floor_mid = _midnight(floor)
    if days is None:
        start = floor_mid
    else:
        candidate = today - timedelta(days=days - 1)
        start = max(candidate, floor_mid)

    trades = list(mongo.db["portfolio_trades"].find(
        {"user_id": ObjectId(user_id)},
    ).sort("date", ASCENDING))

    # Pre-fetch close-price series per ticker we ever held, indexed by date.
    # We pad the lookup window backwards by 14 days so `_close_at_or_before`
    # can always find a fallback close — markets close for weekends, holidays,
    # and longer stretches when stock_data hasn't been refreshed yet (e.g.
    # the 1-day "today" window when today is a weekend or before the seed
    # has rolled forward). Without the pad, a window that starts at today
    # with no bar dated today returns market_value=0 for every holding.
    tickers_ever_held = sorted({t["ticker"] for t in trades})
    price_map: dict[str, dict[datetime, float]] = {}
    fetch_start = start - timedelta(days=14)
    for tk in tickers_ever_held:
        history_df = stock_data_service.get_history(tk, start=fetch_start, end=today)
        if history_df.empty:
            price_map[tk] = {}
            continue
        price_map[tk] = {
            _midnight(idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx): float(row["close"])
            for idx, row in history_df.iterrows()
        }

    points: list[EquityPoint] = []
    cur = start
    trade_idx = 0
    # `initial_cash_usd` mutates with every deposit/withdrawal so it reflects
    # the *current* basis, not the day-zero baseline. To reconstruct the past
    # truthfully we have to peel those funds events back off: the curve must
    # start at the original baseline, then step up/down on the actual
    # deposit/withdrawal dates. Without this, depositing today would lift
    # every historical day by the deposit amount.
    net_funds_flow = 0.0
    for t in trades:
        if t["side"] == "deposit":
            net_funds_flow += float(t["total"])
        elif t["side"] == "withdrawal":
            net_funds_flow -= float(t["total"])
    cash = float(portfolio["initial_cash_usd"]) - net_funds_flow
    holdings_qty: dict[str, float] = {}

    def _apply_trade(t: dict) -> None:
        nonlocal cash
        side = t["side"]
        total = float(t["total"])
        if side == "buy":
            cash -= total
            holdings_qty[t["ticker"]] = holdings_qty.get(t["ticker"], 0.0) + float(t["qty"])
        elif side == "sell":
            cash += total
            holdings_qty[t["ticker"]] = holdings_qty.get(t["ticker"], 0.0) - float(t["qty"])
        elif side == "deposit":
            cash += total
            return  # no holdings impact
        elif side == "withdrawal":
            cash -= total
            return
        if abs(holdings_qty.get(t["ticker"], 0.0)) < 1e-9:
            holdings_qty.pop(t["ticker"], None)

    # Apply any trades that happened before the window starts so the opening
    # day reflects the right state.
    while trade_idx < len(trades) and trades[trade_idx]["date"] < start:
        _apply_trade(trades[trade_idx])
        trade_idx += 1

    while cur <= today:
        # Apply any trades that fired on/before today's EOD.
        while trade_idx < len(trades) and _midnight(trades[trade_idx]["date"]) <= cur:
            _apply_trade(trades[trade_idx])
            trade_idx += 1

        # Mark-to-market — use the close on `cur` if available, else most-recent
        # close on or before `cur` (handles weekends/holidays).
        market = 0.0
        for tk, qty in holdings_qty.items():
            close = _close_at_or_before(price_map.get(tk, {}), cur)
            if close is not None:
                market += qty * close
        points.append(EquityPoint(
            date=cur,
            cash_usd=round(cash, 2),
            market_value_usd=round(market, 2),
            total_value_usd=round(cash + market, 2),
        ))
        cur = cur + timedelta(days=1)

    return PortfolioHistory(
        range=range_key,  # type: ignore[arg-type]
        points=points,
        initial_cash_usd=initial,
    )


def _close_at_or_before(price_by_date: dict[datetime, float], target: datetime) -> Optional[float]:
    """Most-recent close in `price_by_date` whose date ≤ target. Linear scan
    is fine — the dict has at most ~365 entries per ticker for a 1Y range."""
    if target in price_by_date:
        return price_by_date[target]
    best: Optional[float] = None
    best_date: Optional[datetime] = None
    for d, c in price_by_date.items():
        if d <= target and (best_date is None or d > best_date):
            best_date = d
            best = c
    return best


# ---------------------------------------------------------------------------
# Funds adjustment — paper-only deposit / withdrawal
# ---------------------------------------------------------------------------

def adjust_funds(user_id: str, direction: str, amount_usd: float) -> TradePublic:
    """Add or remove virtual USD from the paper portfolio.

    Deliberately **not** linked to the PFM ledger — no Cash account is
    debited, no `transactions` row is inserted. The user can manually log
    a corresponding real-world transaction from the Transactions page if
    they want that side of the bookkeeping. The Funds dialog shows an
    info banner explaining this.

    Effects (both deposit and withdrawal):
      - `portfolio.cash_usd` adjusted by ±amount.
      - `portfolio.initial_cash_usd` adjusted by the same amount so
        total_return_pct stays honest (a $5k deposit shouldn't appear as
        50% performance). Withdrawals floor `initial_cash_usd` at $0 so
        a user who withdraws more than they ever put in doesn't end up
        with a negative basis and an undefined return %.
      - A `portfolio_trades` row is appended with `side="deposit"` or
        `side="withdrawal"`. `ticker="CASH"`, `qty=1`, `price=total=amount`
        so the existing TradePublic shape is preserved; the frontend
        renders these rows with a distinct label.
      - `trade_count` incremented.

    Raises ValidationError for invalid direction, non-positive amount,
    over-cap (>$1M), or withdrawal exceeding current `cash_usd`.
    """
    if direction not in ("deposit", "withdrawal"):
        raise ValidationError(
            "Direction must be 'deposit' or 'withdrawal'",
            details={"direction": direction},
        )
    if amount_usd <= 0:
        raise ValidationError(
            "Amount must be greater than zero",
            details={"amount_usd": amount_usd},
        )
    if amount_usd > 1_000_000:
        raise ValidationError(
            "Amount above the $1,000,000 per-call cap. Run multiple smaller adjustments if intentional.",
            details={"amount_usd": amount_usd, "cap": 1_000_000},
        )

    portfolio = _portfolio_for(user_id)
    cash = float(portfolio["cash_usd"])
    if direction == "withdrawal" and amount_usd > cash:
        raise ValidationError(
            "Insufficient trading cash to withdraw this amount.",
            details={"requested": amount_usd, "available": round(cash, 2)},
        )

    now = utcnow()
    signed = amount_usd if direction == "deposit" else -amount_usd
    new_cash = cash + signed
    initial = float(portfolio.get("initial_cash_usd", 0.0))
    # Bump basis on deposit, decrement on withdrawal (floored at 0).
    new_initial = max(0.0, initial + signed)

    mongo.db["portfolios"].update_one(
        {"user_id": ObjectId(user_id)},
        {
            "$set": {
                "cash_usd": new_cash,
                "initial_cash_usd": new_initial,
            },
            "$inc": {"trade_count": 1},
        },
    )

    trade_doc = {
        "user_id": ObjectId(user_id),
        "date": now,
        "ticker": "CASH",
        "side": direction,
        "qty": 1.0,
        "price": float(amount_usd),
        "total": float(amount_usd),
        "realized_pnl": None,
    }
    res = mongo.db["portfolio_trades"].insert_one(trade_doc)
    trade_doc["_id"] = res.inserted_id
    return _trade_public(trade_doc)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def reset(user_id: str) -> PortfolioPublic:
    """Wipe holdings + trade log + cash → initial. The reset_at timestamp
    becomes the new floor for `history()`'s date range."""
    now = utcnow()
    mongo.db["portfolio_trades"].delete_many({"user_id": ObjectId(user_id)})
    mongo.db["portfolios"].update_one(
        {"user_id": ObjectId(user_id)},
        {"$set": {
            "cash_usd": float(INITIAL_PORTFOLIO_CASH_USD),
            "holdings": [],
            "trade_count": 0,
            "reset_at": now,
        }},
    )
    return get_portfolio(user_id)


# ---------------------------------------------------------------------------
# Live mark-to-market — used by `accounts.Paper Portfolio` hydration
# ---------------------------------------------------------------------------

def market_value_usd(user_id: str) -> float:
    """Cash + Σ(qty × last_close) in USD. Called by the `accounts` service
    when it hydrates the auto-tracked Paper Portfolio account's balance."""
    portfolio = mongo.db["portfolios"].find_one(
        {"user_id": ObjectId(user_id)},
        projection={"cash_usd": 1, "holdings": 1},
    )
    if not portfolio:
        return 0.0
    total = float(portfolio.get("cash_usd", 0.0))
    for h in portfolio.get("holdings", []):
        last = _last_price(h["ticker"])
        if last is not None:
            total += float(h["qty"]) * float(last)
    return total
