"""Net worth tracking — current view, history, snapshots, backfill.

A snapshot is `(user_id, date)` unique; the daily APScheduler job at 02:30
UTC walks every user, recomputes net worth from the live `accounts` table
(FX-converted to the user's base via `account_service`), and upserts into
`net_worth_snapshots`.

Historical accuracy:
  - The auto **Net cash flow** account is reconstructed exactly at any past
    date by summing `amount_base` over transactions on or before that date.
  - The **Paper Portfolio** account uses its *current* balance for historical
    points — we don't store per-day balance history for it. Documented as a
    known limitation in Chapter 5; the Net cash flow account is the dominant
    time-varying signal anyway.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from app.extensions import mongo
from app.models.networth import (
    AccountBreakdownEntry,
    HistoryRange,
    NetWorthCurrent,
    NetWorthHistory,
    NetWorthHistoryPoint,
    NetWorthSnapshotPublic,
    SnapshotSource,
)
from app.models.user import to_utc_naive, utcnow
from app.services import fx_service

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _midnight(d: datetime) -> datetime:
    n = to_utc_naive(d)
    return n.replace(hour=0, minute=0, second=0, microsecond=0)


def _user_base_currency(user_id: str) -> str:
    user = mongo.db["users"].find_one({"_id": ObjectId(user_id)}, {"base_currency": 1})
    return (user or {}).get("base_currency", "RON")


def _category_for_type(account_type: str) -> str:
    """Mirror of `app.models.account.category_for` without the import cycle."""
    asset_types = {
        "cash", "savings", "investment", "real_estate", "vehicle", "other_asset",
    }
    return "asset" if account_type in asset_types else "liability"


# ---------------------------------------------------------------------------
# Building blocks: live & historical net worth computation
# ---------------------------------------------------------------------------

def _net_cashflow_at(user_id: str, on: datetime) -> float:
    """`sum(amount_base)` over the user's non-deleted transactions whose
    `date <= on`. Drives the historical reconstruction of the auto Net cash
    flow account."""
    pipeline = [
        {"$match": {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "date": {"$lte": _midnight(on) + timedelta(days=1) - timedelta(microseconds=1)},
        }},
        {"$group": {"_id": None, "net": {"$sum": "$amount_base"}}},
    ]
    row = next(mongo.db["transactions"].aggregate(pipeline), None)
    return float(row["net"]) if row else 0.0


def _account_balance_base(account: dict[str, Any], base: str, on: Optional[datetime] = None) -> float:
    """Convert an account's stored balance to the user's base currency.

    For the auto **Net cash flow** account: balance is computed live from
    transactions at-or-before `on` (or today if `on` is None).
    For the auto **Paper Portfolio** account: the stored `balance` is a
    placeholder (0.0 at seed, never written back); the live mark-to-market
    in USD comes from `portfolio_service.market_value_usd`. Imported lazily
    to avoid an import cycle.
    For everything else: use the stored balance, FX-converted to base.
    """
    user_id = str(account["user_id"])
    src = account.get("source_ref")
    if src == "transactions:net":
        return _net_cashflow_at(user_id, on or utcnow())
    if src == "portfolio":
        from app.services import portfolio_service  # lazy: avoids cycle on startup
        balance = portfolio_service.market_value_usd(user_id)
    else:
        balance = float(account.get("balance", 0.0))
    currency = account.get("currency", base)
    if currency == base:
        return balance
    try:
        return fx_service.convert(balance, currency, base, on=on)
    except Exception:  # noqa: BLE001 — face-value fallback; surfaces via mixed_currency in totals()
        log.warning("FX convert failed for account %s — using face value", account.get("_id"))
        return balance


def _compute_breakdown(user_id: str, base: str, on: Optional[datetime] = None) -> tuple[list[AccountBreakdownEntry], float, float]:
    """Walk every active account and return (breakdown, total_assets, total_liabilities)."""
    cursor = mongo.db["accounts"].find(
        {"user_id": ObjectId(user_id), "deleted_at": None},
    ).sort([("is_automatic", -1), ("created_at", 1)])

    breakdown: list[AccountBreakdownEntry] = []
    assets = 0.0
    liabilities = 0.0
    for acc in cursor:
        category = _category_for_type(acc["type"])
        balance = round(_account_balance_base(acc, base, on=on), 2)
        breakdown.append(AccountBreakdownEntry(
            account_id=str(acc["_id"]),
            name=acc["name"],
            type=acc["type"],
            category=category,
            balance_base=balance,
        ))
        if category == "asset":
            assets += balance
        else:
            liabilities += balance
    return breakdown, round(assets, 2), round(liabilities, 2)


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------

def _to_public_snapshot(doc: dict[str, Any]) -> NetWorthSnapshotPublic:
    return NetWorthSnapshotPublic(
        id=str(doc["_id"]),
        date=doc["date"],
        total_assets=float(doc["total_assets"]),
        total_liabilities=float(doc["total_liabilities"]),
        net_worth=float(doc["net_worth"]),
        base_currency=doc["base_currency"],
        breakdown=[
            AccountBreakdownEntry(**b) if not isinstance(b, AccountBreakdownEntry) else b
            for b in doc.get("breakdown", [])
        ],
        source=doc["source"],
    )


def take_snapshot(
    user_id: str,
    *,
    source: SnapshotSource = "manual",
    on: Optional[datetime] = None,
) -> NetWorthSnapshotPublic:
    """Compute net worth at `on` (default: today) and upsert one snapshot row.

    Idempotent on `(user_id, date)` — re-running on the same day overwrites
    the prior row, so a manual snapshot replaces the morning's scheduled one
    and a backfill replay can rebuild history without dupes.
    """
    base = _user_base_currency(user_id)
    snapshot_date = _midnight(on or utcnow())
    breakdown, assets, liabilities = _compute_breakdown(user_id, base, on=snapshot_date)
    net = round(assets - liabilities, 2)

    doc = {
        "user_id": ObjectId(user_id),
        "date": snapshot_date,
        "total_assets": assets,
        "total_liabilities": liabilities,
        "net_worth": net,
        "base_currency": base,
        "breakdown": [b.model_dump() for b in breakdown],
        "source": source,
        "created_at": utcnow(),
    }
    res = mongo.db["net_worth_snapshots"].update_one(
        {"user_id": ObjectId(user_id), "date": snapshot_date},
        {"$set": doc},
        upsert=True,
    )
    # Re-read the committed row so the public model has a real `_id`.
    saved = mongo.db["net_worth_snapshots"].find_one(
        {"user_id": ObjectId(user_id), "date": snapshot_date}
    )
    assert saved is not None  # we just upserted it
    return _to_public_snapshot(saved)


# ---------------------------------------------------------------------------
# Public API: current, history, backfill, scheduled job
# ---------------------------------------------------------------------------

def current(user_id: str) -> NetWorthCurrent:
    base = _user_base_currency(user_id)
    breakdown, assets, liabilities = _compute_breakdown(user_id, base)
    net = round(assets - liabilities, 2)

    # Snapshot stats — last seen, total count, and the closest snapshot to
    # ~30 days ago for a delta. We tolerate ±5 days when looking up the
    # comparison snapshot so users with sparse history still get a number.
    today = _midnight(utcnow())
    target = today - timedelta(days=30)
    window_lo = target - timedelta(days=5)
    window_hi = target + timedelta(days=5)

    coll = mongo.db["net_worth_snapshots"]
    snapshot_count = coll.count_documents({"user_id": ObjectId(user_id)})
    last_doc = coll.find_one(
        {"user_id": ObjectId(user_id)},
        sort=[("date", DESCENDING)],
        projection={"date": 1},
    )
    comp_doc = coll.find_one(
        {
            "user_id": ObjectId(user_id),
            "date": {"$gte": window_lo, "$lte": window_hi},
        },
        sort=[("date", ASCENDING)],
        projection={"net_worth": 1, "date": 1},
    )

    delta_30d: Optional[float] = None
    delta_30d_pct: Optional[float] = None
    if comp_doc and float(comp_doc["net_worth"]) != 0:
        comp_value = float(comp_doc["net_worth"])
        delta_30d = round(net - comp_value, 2)
        delta_30d_pct = round((net - comp_value) / abs(comp_value) * 100, 2)
    elif comp_doc:
        delta_30d = round(net - float(comp_doc["net_worth"]), 2)

    return NetWorthCurrent(
        total_assets=assets,
        total_liabilities=liabilities,
        net_worth=net,
        base_currency=base,
        breakdown=breakdown,
        delta_30d=delta_30d,
        delta_30d_pct=delta_30d_pct,
        last_snapshot_date=last_doc["date"] if last_doc else None,
        snapshot_count=snapshot_count,
    )


_RANGE_DAYS: dict[str, Optional[int]] = {
    "1M": 31,
    "3M": 92,
    "6M": 183,
    "1Y": 366,
    "ALL": None,
}


def history(user_id: str, range_key: HistoryRange = "3M") -> NetWorthHistory:
    base = _user_base_currency(user_id)
    days = _RANGE_DAYS[range_key]
    filt: dict[str, Any] = {"user_id": ObjectId(user_id)}
    if days is not None:
        filt["date"] = {"$gte": _midnight(utcnow()) - timedelta(days=days)}
    cursor = mongo.db["net_worth_snapshots"].find(
        filt,
        projection={"date": 1, "total_assets": 1, "total_liabilities": 1, "net_worth": 1},
    ).sort("date", ASCENDING)

    points = [
        NetWorthHistoryPoint(
            date=d["date"],
            total_assets=float(d["total_assets"]),
            total_liabilities=float(d["total_liabilities"]),
            net_worth=float(d["net_worth"]),
        )
        for d in cursor
    ]
    return NetWorthHistory(range=range_key, points=points, base_currency=base)


# ---------------------------------------------------------------------------
# Backfill — reconstruct historical snapshots from transaction history
# ---------------------------------------------------------------------------

def backfill(user_id: str, *, days: int = 180, step_days: int = 1) -> dict[str, int]:
    """Walk back `days` from today inserting one snapshot per `step_days`.

    Only the auto Net cash flow account is time-accurate — manual account
    balances use the *current* value at every historical point. This is good
    enough for a useful chart and is documented as a Chapter 5 limitation.

    Re-runnable: each (user_id, date) is upserted, so re-backfilling overwrites
    rather than dupes.
    """
    today = _midnight(utcnow())
    start = today - timedelta(days=days)

    # Walk forward from `start` so the chart's earliest point lands first.
    cur = start
    inserted = 0
    while cur <= today:
        take_snapshot(user_id, source="backfill", on=cur)
        inserted += 1
        cur = cur + timedelta(days=step_days)
    return {"inserted": inserted, "from": start.date().isoformat(), "to": today.date().isoformat()}


# ---------------------------------------------------------------------------
# Scheduled job entry point
# ---------------------------------------------------------------------------

def snapshot_all_users() -> dict[str, int]:
    """Run by APScheduler daily at 02:30 UTC. Iterates every user and takes
    today's snapshot. Failures on individual users are logged and do not
    abort the loop — one user's bad FX state shouldn't block the rest.
    """
    user_ids = [str(u["_id"]) for u in mongo.db["users"].find({}, {"_id": 1})]
    ok = 0
    failed = 0
    for uid in user_ids:
        try:
            take_snapshot(uid, source="scheduled_daily")
            ok += 1
        except Exception:  # noqa: BLE001 — keep the daily job resilient
            log.exception("snapshot_networth failed for user=%s", uid)
            failed += 1
    return {"users_total": len(user_ids), "ok": ok, "failed": failed}
