"""Aggregations over transactions, used by the dashboard + reports pages."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId

from app.extensions import mongo
from app.models.user import to_utc_naive, utcnow


def spending_by_category(
    user_id: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> dict[str, Any]:
    """Sum expenses (negative `amount_base`) grouped by category.

    Returns:
        {
          "from": <ISO date or null>,
          "to":   <ISO date or null>,
          "total_expense": float,        # always positive (sum of |amount|)
          "total_income":  float,        # always positive
          "items": [{category_id, category_name, color, total, count, pct}, ...]
        }
    """
    match: dict[str, Any] = {"user_id": ObjectId(user_id), "deleted_at": None}
    if date_from or date_to:
        date_clause: dict[str, Any] = {}
        if date_from:
            date_clause["$gte"] = to_utc_naive(date_from)
        if date_to:
            date_clause["$lte"] = to_utc_naive(date_to)
        match["date"] = date_clause

    pipeline = [
        {"$match": match},
        {
            "$facet": {
                "expense_by_cat": [
                    {"$match": {"amount_base": {"$lt": 0}}},
                    {
                        "$group": {
                            "_id": "$category_id",
                            "total": {"$sum": {"$abs": "$amount_base"}},
                            "count": {"$sum": 1},
                        }
                    },
                ],
                "totals": [
                    {
                        "$group": {
                            "_id": None,
                            "expense": {
                                "$sum": {
                                    "$cond": [
                                        {"$lt": ["$amount_base", 0]},
                                        {"$abs": "$amount_base"},
                                        0,
                                    ]
                                }
                            },
                            "income": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": ["$amount_base", 0]},
                                        "$amount_base",
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
            }
        },
    ]
    result = next(mongo.db["transactions"].aggregate(pipeline), None) or {}
    expense_rows = result.get("expense_by_cat", [])
    totals = (result.get("totals") or [{}])[0]
    total_expense = float(totals.get("expense", 0.0) or 0.0)
    total_income = float(totals.get("income", 0.0) or 0.0)

    cat_ids = [r["_id"] for r in expense_rows if r.get("_id")]
    cat_lookup: dict[ObjectId, dict[str, Any]] = {}
    if cat_ids:
        for c in mongo.db["categories"].find({"_id": {"$in": cat_ids}}, {"name": 1, "color": 1}):
            cat_lookup[c["_id"]] = c

    items = []
    for r in expense_rows:
        cat = cat_lookup.get(r["_id"]) if r.get("_id") else None
        total = float(r["total"])
        items.append(
            {
                "category_id": str(r["_id"]) if r.get("_id") else None,
                "category_name": cat["name"] if cat else "Uncategorized",
                "color": cat.get("color") if cat else "#94a3b8",
                "total": round(total, 2),
                "count": int(r["count"]),
                "pct": round((total / total_expense * 100) if total_expense else 0.0, 1),
            }
        )
    items.sort(key=lambda x: -x["total"])

    return {
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "total_expense": round(total_expense, 2),
        "total_income": round(total_income, 2),
        "items": items,
    }


def top_merchants(
    user_id: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Aggregate expense transactions by merchant (or description fallback).

    Returns the top N merchants by total absolute spend, with count and
    average amount. Used by ReportsPage. The merchant key falls back to
    `description` because manual transactions sometimes leave merchant blank.
    """
    match: dict[str, Any] = {
        "user_id": ObjectId(user_id),
        "deleted_at": None,
        "amount_base": {"$lt": 0},
    }
    if date_from or date_to:
        date_clause: dict[str, Any] = {}
        if date_from:
            date_clause["$gte"] = to_utc_naive(date_from)
        if date_to:
            date_clause["$lte"] = to_utc_naive(date_to)
        match["date"] = date_clause

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "$ifNull": ["$merchant", "$description"],
                },
                "category_id": {"$first": "$category_id"},
                "total": {"$sum": {"$abs": "$amount_base"}},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"total": -1}},
        {"$limit": int(limit)},
    ]
    rows = list(mongo.db["transactions"].aggregate(pipeline))

    # Hydrate category names in one round trip.
    cat_ids = [r["category_id"] for r in rows if r.get("category_id")]
    cat_lookup: dict[ObjectId, dict[str, Any]] = {}
    if cat_ids:
        for c in mongo.db["categories"].find(
            {"_id": {"$in": cat_ids}}, {"name": 1}
        ):
            cat_lookup[c["_id"]] = c

    items = []
    for r in rows:
        cat = cat_lookup.get(r.get("category_id")) if r.get("category_id") else None
        total = float(r["total"])
        count = int(r["count"])
        items.append(
            {
                "merchant": r["_id"] or "(unspecified)",
                "category_name": cat["name"] if cat else "Uncategorized",
                "count": count,
                "total": round(total, 2),
                "avg": round(total / count, 2) if count else 0.0,
            }
        )
    return {
        "from": date_from.isoformat() if date_from else None,
        "to": date_to.isoformat() if date_to else None,
        "items": items,
    }


def monthly_summary(
    user_id: str,
    months: int = 6,
    *,
    end: Optional[datetime] = None,
) -> dict[str, Any]:
    """Income vs expenses per month for the last `months` months ending at
    `end` (or the current month if `end` is None). The window always
    includes the `end` month — for `end=2026-01` and `months=6`, the
    returned set is Aug 2025 → Jan 2026.

    `end` can be any date inside the target month; it's normalised to the
    first of that month internally."""
    anchor = end or utcnow()
    # First day of the end month (inclusive in the window).
    end_first = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # First day of the month AFTER the end month — used as the exclusive
    # upper bound so transactions on the last day of `end` are included.
    if end_first.month == 12:
        end_excl = end_first.replace(year=end_first.year + 1, month=1)
    else:
        end_excl = end_first.replace(month=end_first.month + 1)
    # First day of the start month — walk back (months - 1) calendar months
    # so the window length is exactly `months`.
    start = end_first
    for _ in range(months - 1):
        if start.month == 1:
            start = start.replace(year=start.year - 1, month=12)
        else:
            start = start.replace(month=start.month - 1)

    pipeline = [
        {
            "$match": {
                "user_id": ObjectId(user_id),
                "deleted_at": None,
                "date": {"$gte": start, "$lt": end_excl},
            }
        },
        {
            "$group": {
                "_id": {
                    "year": {"$year": "$date"},
                    "month": {"$month": "$date"},
                },
                "income": {
                    "$sum": {
                        "$cond": [{"$gt": ["$amount_base", 0]}, "$amount_base", 0]
                    }
                },
                "expense": {
                    "$sum": {
                        "$cond": [
                            {"$lt": ["$amount_base", 0]},
                            {"$abs": "$amount_base"},
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1}},
    ]
    rows = list(mongo.db["transactions"].aggregate(pipeline))
    # Index aggregator output by (year, month) so we can fill gaps.
    by_ym: dict[tuple[int, int], dict[str, float]] = {
        (int(r["_id"]["year"]), int(r["_id"]["month"])): {
            "income": float(r["income"]),
            "expense": float(r["expense"]),
        }
        for r in rows
    }
    # Walk the calendar from `start` to `end_first` inclusive, emitting one
    # row per month so the response always has exactly `months` entries —
    # otherwise months with zero transactions are silently dropped and
    # the dashboard sparklines lose ticks.
    out: list[dict[str, Any]] = []
    cur = start
    while cur <= end_first:
        ym = (cur.year, cur.month)
        income = by_ym.get(ym, {}).get("income", 0.0)
        expense = by_ym.get(ym, {}).get("expense", 0.0)
        out.append({
            "year": cur.year,
            "month": cur.month,
            "income": round(income, 2),
            "expense": round(expense, 2),
            "savings_rate": round(
                (income - expense) / income if income > 0 else 0.0,
                3,
            ),
        })
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return {"months": out}
