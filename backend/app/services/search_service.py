"""Global search across the user's data + the stock universe.

The Topbar search bar uses this. It returns a flat, ranked list across:
  - transactions (description / merchant)
  - goals       (name)
  - categories  (name)
  - recurring   (name / merchant_pattern)
  - stocks      (ticker / company name from TICKER_META)

Accounts were dropped from the search surface — the standalone Accounts
page no longer exists, so a search result for an account name would link
nowhere useful. `_search_accounts` is left defined below in case the UI
returns; it just isn't called by `search()`.

Each result is shaped uniformly so the frontend can render any kind in one
list (kind, title, subtitle, link, score). Score is a simple "exact match
beats prefix beats substring" — good enough for an autocomplete dropdown.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from bson import ObjectId
from pymongo import DESCENDING

from app.extensions import mongo
from app.utils.constants import TICKER_META

PER_KIND_LIMIT = 5  # max results per resource kind in one response


def _score(query: str, *fields: str | None) -> int:
    """0–100 relevance score; 100 = exact, 60 = prefix, 30 = substring."""
    q = query.lower()
    best = 0
    for f in fields:
        if not f:
            continue
        s = f.lower()
        if s == q:
            return 100
        if s.startswith(q):
            best = max(best, 60)
        elif q in s:
            best = max(best, 30)
    return best


def _re_escape(query: str) -> str:
    return re.escape(query)


def _search_transactions(user_id: str, query: str) -> list[dict[str, Any]]:
    pattern = _re_escape(query)
    cursor = (
        mongo.db["transactions"]
        .find(
            {
                "user_id": ObjectId(user_id),
                "deleted_at": None,
                "$or": [
                    {"description": {"$regex": pattern, "$options": "i"}},
                    {"merchant": {"$regex": pattern, "$options": "i"}},
                ],
            },
            {"description": 1, "merchant": 1, "amount": 1, "currency": 1, "date": 1},
        )
        .sort("date", DESCENDING)
        .limit(PER_KIND_LIMIT)
    )
    out: list[dict[str, Any]] = []
    for d in cursor:
        amount = d.get("amount", 0)
        sign = "+" if amount > 0 else "−"
        title = (d.get("merchant") or d.get("description") or "Transaction")[:60]
        subtitle = (
            f"{sign}{abs(amount):,.2f} {d.get('currency', '')} · "
            f"{d['date'].strftime('%b %d, %Y') if d.get('date') else ''}"
        )
        out.append(
            {
                "kind": "transaction",
                "id": str(d["_id"]),
                "title": title,
                "subtitle": subtitle,
                "link": "/transactions",
                "score": _score(query, d.get("description"), d.get("merchant")),
            }
        )
    return out


def _search_goals(user_id: str, query: str) -> list[dict[str, Any]]:
    pattern = _re_escape(query)
    cursor = mongo.db["goals"].find(
        {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "name": {"$regex": pattern, "$options": "i"},
        },
        {"name": 1, "saved_amount": 1, "target_amount": 1, "currency": 1},
    ).limit(PER_KIND_LIMIT)
    out: list[dict[str, Any]] = []
    for d in cursor:
        saved = float(d.get("saved_amount", 0))
        target = float(d.get("target_amount", 1))
        pct = (saved / target * 100) if target else 0.0
        out.append(
            {
                "kind": "goal",
                "id": str(d["_id"]),
                "title": d.get("name", "Goal"),
                "subtitle": f"{pct:.0f}% saved · {saved:,.0f} of {target:,.0f} {d.get('currency', '')}",
                "link": "/goals",
                "score": _score(query, d.get("name")),
            }
        )
    return out


def _search_categories(user_id: str, query: str) -> list[dict[str, Any]]:
    pattern = _re_escape(query)
    cursor = mongo.db["categories"].find(
        {
            "user_id": ObjectId(user_id),
            "name": {"$regex": pattern, "$options": "i"},
        },
        {"name": 1, "monthly_budget": 1, "color": 1},
    ).limit(PER_KIND_LIMIT)
    out: list[dict[str, Any]] = []
    for d in cursor:
        budget = float(d.get("monthly_budget", 0) or 0)
        sub = f"Budget {budget:,.0f}/mo" if budget else "No budget set"
        out.append(
            {
                "kind": "category",
                "id": str(d["_id"]),
                "title": d.get("name", "Category"),
                "subtitle": sub,
                "link": "/budget",
                "score": _score(query, d.get("name")),
            }
        )
    return out


def _search_recurring(user_id: str, query: str) -> list[dict[str, Any]]:
    pattern = _re_escape(query)
    cursor = mongo.db["recurring_payments"].find(
        {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "$or": [
                {"name": {"$regex": pattern, "$options": "i"}},
                {"merchant_pattern": {"$regex": pattern, "$options": "i"}},
            ],
        },
        {
            "name": 1,
            "merchant_pattern": 1,
            "amount": 1,
            "currency": 1,
            "frequency": 1,
            "next_due": 1,
        },
    ).limit(PER_KIND_LIMIT)
    out: list[dict[str, Any]] = []
    for d in cursor:
        when = d["next_due"].strftime("%b %d") if d.get("next_due") else ""
        out.append(
            {
                "kind": "recurring",
                "id": str(d["_id"]),
                "title": d.get("name") or d.get("merchant_pattern", "Recurring"),
                "subtitle": (
                    f"{d.get('frequency', '')} · {d.get('amount', 0):,.0f} "
                    f"{d.get('currency', '')} · next {when}"
                ),
                "link": "/recurring",
                "score": _score(query, d.get("name"), d.get("merchant_pattern")),
            }
        )
    return out


def _search_accounts(user_id: str, query: str) -> list[dict[str, Any]]:
    """Search by account name. Auto-tracked accounts (Paper Portfolio,
    Net cash flow) need their balance hydrated live from
    `account_service` because the stored `balance` field is just a
    placeholder for those rows."""
    from app.services import account_service  # lazy: import cycle guard

    pattern = _re_escape(query)
    cursor = mongo.db["accounts"].find(
        {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "name": {"$regex": pattern, "$options": "i"},
        },
        {"name": 1, "type": 1, "balance": 1, "currency": 1, "source_ref": 1},
    ).limit(PER_KIND_LIMIT)
    out: list[dict[str, Any]] = []
    for d in cursor:
        hydrated = account_service._hydrate_balance(user_id, d)
        out.append(
            {
                "kind": "account",
                "id": str(d["_id"]),
                "title": d.get("name", "Account"),
                "subtitle": (
                    f"{d.get('type', '').replace('_', ' ').title()} · "
                    f"{hydrated.get('balance', 0):,.0f} {d.get('currency', '')}"
                ),
                "link": "/accounts",
                "score": _score(query, d.get("name")),
            }
        )
    return out


def _search_stocks(query: str) -> list[dict[str, Any]]:
    """Search the static ticker universe (TICKER_META). No DB hit."""
    q = query.lower()
    out: list[dict[str, Any]] = []
    for ticker, meta in TICKER_META.items():
        score = _score(query, ticker, meta.get("name"))
        if not score:
            continue
        out.append(
            {
                "kind": "stock",
                "id": ticker,
                "title": ticker,
                "subtitle": f"{meta.get('name', '')} · {meta.get('sector', '')}",
                "link": f"/markets/{ticker}",
                "score": score,
            }
        )
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:PER_KIND_LIMIT]


def search(user_id: str, query: str, limit: int = 20) -> dict[str, Any]:
    """Search across all kinds. Returns at most `limit` results, sorted by
    relevance. Empty query returns an empty list."""
    q = (query or "").strip()
    if not q or len(q) < 1:
        return {"query": q, "results": []}

    results: list[dict[str, Any]] = []
    results.extend(_search_transactions(user_id, q))
    results.extend(_search_goals(user_id, q))
    results.extend(_search_categories(user_id, q))
    results.extend(_search_recurring(user_id, q))
    # Accounts removed from search: the standalone Accounts page no longer
    # exists (Cash + Paper Portfolio + Net cash flow are system-managed,
    # there's no UI to view a single account), so a search result for an
    # account name would link nowhere useful. `_search_accounts` and its
    # docstring entry above are kept for now in case the UI returns.
    results.extend(_search_stocks(q))

    # Stable secondary sort by kind so identical-score results group together.
    KIND_ORDER = {"stock": 0, "goal": 1, "category": 2, "recurring": 3, "transaction": 4}
    results.sort(key=lambda r: (-r["score"], KIND_ORDER.get(r["kind"], 99)))

    return {"query": q, "results": results[:limit]}
