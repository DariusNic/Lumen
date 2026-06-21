"""Accounts — feeds the Net Worth tracker (plan §9).

Every user has two auto-seeded accounts at signup, both auto-tracked and
read-only (the user never edits them directly):
  - **Paper Portfolio** (`source_ref="portfolio"`; balance is the live
    mark-to-market of the simulated holdings, in USD)
  - **Net cash flow** (`source_ref="transactions:net"`; balance is computed
    live as `sum(amount_base)` over all the user's transactions)

There are no manual/user-created accounts — net worth is derived entirely
from these two automatic sources.
"""
from typing import Any

from bson import ObjectId

from app.extensions import mongo
from app.models.account import AccountPublic, category_for
from app.models.user import utcnow
from app.services import fx_service
from app.utils.errors import AppError


def _net_cashflow_balance(user_id: str) -> float:
    """Live aggregate over the user's non-deleted transactions in base currency."""
    pipeline = [
        {"$match": {"user_id": ObjectId(user_id), "deleted_at": None}},
        {"$group": {"_id": None, "net": {"$sum": "$amount_base"}}},
    ]
    row = next(mongo.db["transactions"].aggregate(pipeline), None)
    return float(row["net"]) if row else 0.0


def _hydrate_balance(user_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Replace stored balance with a live computation for the derived
    auto-accounts.

    Two derived flavors:
      - `transactions:net`  → sum of `amount_base` over the user's transactions
      - `portfolio`         → cash + mark-to-market of holdings (USD), provided
                              by `portfolio_service.market_value_usd`. Imported
                              lazily to avoid an import cycle.
    """
    src = doc.get("source_ref")
    if src == "transactions:net":
        return {**doc, "balance": _net_cashflow_balance(user_id)}
    if src == "portfolio":
        from app.services import portfolio_service  # lazy: avoids cycle on startup
        return {**doc, "balance": portfolio_service.market_value_usd(user_id)}
    return doc


def _to_public(doc: dict[str, Any]) -> AccountPublic:
    return AccountPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        type=doc["type"],
        category=category_for(doc["type"]),
        balance=float(doc.get("balance", 0.0)),
        currency=doc["currency"],
        is_automatic=bool(doc.get("is_automatic", False)),
        source_ref=doc.get("source_ref"),
        notes=doc.get("notes"),
        last_updated=doc.get("last_updated") or doc["created_at"],
        created_at=doc["created_at"],
    )


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_defaults(user_id: str, base_currency: str) -> None:
    """Insert Paper Portfolio + Net cash flow for a brand-new user.

    Idempotent — bails if the user already has any non-deleted account, so
    it's safe to call on every login (self-healing backfill for accounts
    created before account-seeding existed).
    """
    coll_existing = mongo.db["accounts"]
    if coll_existing.count_documents(
        {"user_id": ObjectId(user_id), "deleted_at": None}, limit=1
    ) > 0:
        return
    now = utcnow()
    docs = [
        {
            "user_id": ObjectId(user_id),
            "name": "Paper Portfolio",
            "type": "investment",
            "balance": 0.0,
            "currency": "USD",
            "is_automatic": True,
            "source_ref": "portfolio",  # hydrated live from the portfolio service
            "notes": None,
            "deleted_at": None,
            "last_updated": now,
            "created_at": now,
        },
        {
            "user_id": ObjectId(user_id),
            "name": "Net cash flow",
            "type": "other_asset",
            "balance": 0.0,  # live-computed at read time
            "currency": base_currency,
            "is_automatic": True,
            "source_ref": "transactions:net",
            "notes": "Running total across all your transactions.",
            "deleted_at": None,
            "last_updated": now,
            "created_at": now,
        },
    ]
    mongo.db["accounts"].insert_many(docs)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_for_user(user_id: str) -> list[AccountPublic]:
    cursor = mongo.db["accounts"].find(
        {"user_id": ObjectId(user_id), "deleted_at": None},
    ).sort([("is_automatic", -1), ("created_at", 1)])
    return [_to_public(_hydrate_balance(user_id, d)) for d in cursor]


def totals(user_id: str) -> dict[str, Any]:
    """Asset / liability / net totals across the user's accounts, **converted
    to the user's base currency** via the daily ECB rate.

    Returns the totals plus a `base_currency` echo so the frontend can pick
    the right symbol without re-querying `/me`. If FX conversion fails (live
    Frankfurter down + cache > 7 days old), each problematic account is
    summed at face value and the response includes a `mixed_currency=True`
    hint for the UI to surface a small notice.
    """
    user = mongo.db["users"].find_one({"_id": ObjectId(user_id)}, {"base_currency": 1})
    base = (user or {}).get("base_currency", "RON")

    accounts = list_for_user(user_id)
    fx_failed = False

    def to_base(balance: float, currency: str) -> float:
        nonlocal fx_failed
        if currency == base:
            return balance
        try:
            return fx_service.convert(balance, currency, base)
        except AppError:
            fx_failed = True
            return balance  # face-value fallback; UI flag will warn the user

    asset = sum(to_base(a.balance, a.currency) for a in accounts if a.category == "asset")
    liability = sum(to_base(a.balance, a.currency) for a in accounts if a.category == "liability")
    return {
        "assets": round(asset, 2),
        "liabilities": round(liability, 2),
        "net_worth": round(asset - liability, 2),
        "base_currency": base,
        "mixed_currency": fx_failed,
    }
