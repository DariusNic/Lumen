import logging
import re
from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument, UpdateOne

from app.extensions import mongo
from app.ml.categorization.predict import categorize as run_cascade
from app.models.transaction import (
    TransactionCreate,
    TransactionListQuery,
    TransactionPublic,
    TransactionUpdate,
)
from app.models.user import to_utc_naive, utcnow
from app.services import category_service, fx_service
from app.utils.errors import NotFoundError, ValidationError

log = logging.getLogger(__name__)


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as e:
        raise NotFoundError("Not found") from e


def _to_public(doc: dict[str, Any], category_name: Optional[str] = None) -> TransactionPublic:
    return TransactionPublic(
        id=str(doc["_id"]),
        date=doc["date"],
        amount=doc["amount"],
        amount_base=doc["amount_base"],
        currency=doc["currency"],
        description=doc["description"],
        merchant=doc.get("merchant"),
        category_id=str(doc["category_id"]) if doc.get("category_id") else None,
        category_name=category_name,
        account_id=str(doc["account_id"]) if doc.get("account_id") else None,
        source=doc.get("source", "manual"),
        is_recurring=doc.get("is_recurring", False),
        created_at=doc["created_at"],
    )


def _resolve_category(user_id: str, payload_category_id: Optional[str], description: str) -> Optional[ObjectId]:
    """Pick a category: explicit id wins; otherwise run the rules cascade
    and look up the matching system category by name."""
    if payload_category_id:
        # Validate it belongs to this user (raises NotFoundError otherwise).
        category_service.get(user_id, payload_category_id)
        return _oid(payload_category_id)
    name = run_cascade(description)
    cat = category_service.find_by_name(user_id, name)
    return ObjectId(cat.id) if cat else None


def _to_base_amount(
    amount: float,
    currency: str,
    base_currency: str,
    on: Optional[Any] = None,
) -> float:
    """Convert `amount` from `currency` to `base_currency` using the daily ECB
    rate valid on `on` (default: today). Conversion happens once at insertion —
    `amount_base` is stored alongside `amount`.

    Same-currency short-circuit avoids a Mongo round-trip on the common case.
    Conversion errors propagate as `ValidationError` (rejected at the API
    boundary with the standard error envelope)."""
    if currency == base_currency:
        return amount
    return fx_service.convert(amount, currency, base_currency, on=on)


def _user_base_currency(user_id: str) -> str:
    user = mongo.db["users"].find_one({"_id": ObjectId(user_id)}, {"base_currency": 1})
    return user["base_currency"] if user else "RON"


def create(user_id: str, payload: TransactionCreate) -> TransactionPublic:
    base = _user_base_currency(user_id)
    category_oid = _resolve_category(user_id, payload.category_id, payload.description)
    now = utcnow()
    tx_date = to_utc_naive(payload.date)
    doc = {
        "user_id": ObjectId(user_id),
        "date": tx_date,
        "amount": float(payload.amount),
        "amount_base": _to_base_amount(payload.amount, payload.currency, base, on=tx_date),
        "currency": payload.currency,
        "description": payload.description.strip(),
        "merchant": payload.merchant.strip() if payload.merchant else None,
        "category_id": category_oid,
        "account_id": _oid(payload.account_id) if payload.account_id else None,
        "source": payload.source,
        "is_recurring": False,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    res = mongo.db["transactions"].insert_one(doc)
    doc["_id"] = res.inserted_id
    cat_name = _category_name(category_oid)
    return _to_public(doc, cat_name)


def _category_name(category_oid: Optional[ObjectId]) -> Optional[str]:
    if not category_oid:
        return None
    cat = mongo.db["categories"].find_one({"_id": category_oid}, {"name": 1})
    return cat["name"] if cat else None


def list_for_user(user_id: str, q: TransactionListQuery) -> dict[str, Any]:
    filt: dict[str, Any] = {"user_id": ObjectId(user_id), "deleted_at": None}
    if q.date_from or q.date_to:
        date_clause: dict[str, Any] = {}
        if q.date_from:
            date_clause["$gte"] = to_utc_naive(q.date_from)
        if q.date_to:
            date_clause["$lte"] = to_utc_naive(q.date_to)
        filt["date"] = date_clause
    if q.category_id:
        filt["category_id"] = _oid(q.category_id)
    if q.search:
        # Escape regex metacharacters — `q.search` is user-controlled, and
        # passing raw `.*` or `^` would let a user run regex queries beyond a
        # plain substring match. Search is already user-scoped via `user_id`
        # in `filt`, so this is hardening, not exfiltration prevention.
        pattern = re.escape(q.search)
        filt["$or"] = [
            {"description": {"$regex": pattern, "$options": "i"}},
            {"merchant": {"$regex": pattern, "$options": "i"}},
        ]

    total = mongo.db["transactions"].count_documents(filt)
    cursor = (
        mongo.db["transactions"]
        .find(filt)
        .sort("date", DESCENDING)
        .skip((q.page - 1) * q.page_size)
        .limit(q.page_size)
    )
    docs = list(cursor)

    # Hydrate category names in one round trip.
    cat_ids = {d["category_id"] for d in docs if d.get("category_id")}
    name_map: dict[ObjectId, str] = {}
    if cat_ids:
        for c in mongo.db["categories"].find({"_id": {"$in": list(cat_ids)}}, {"name": 1}):
            name_map[c["_id"]] = c["name"]

    items = [_to_public(d, name_map.get(d.get("category_id"))) for d in docs]
    return {
        "transactions": items,
        "total": total,
        "page": q.page,
        "page_size": q.page_size,
    }


def get(user_id: str, tx_id: str) -> TransactionPublic:
    doc = mongo.db["transactions"].find_one(
        {"_id": _oid(tx_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not doc:
        raise NotFoundError("Transaction not found")
    return _to_public(doc, _category_name(doc.get("category_id")))


def update(user_id: str, tx_id: str, payload: TransactionUpdate) -> TransactionPublic:
    update_doc = payload.model_dump(exclude_none=True)
    if not update_doc:
        return get(user_id, tx_id)

    # Guard: goal contributions are paired with `goals.saved_amount` which
    # lives outside this collection. Editing the tx without re-syncing the
    # goal would silently desync the two — UI hides Edit for these rows, but
    # also reject any direct PATCH that would change financial fields. Allow
    # category-only edits since they don't affect saved_amount.
    if any(k in update_doc for k in ("amount", "currency", "date", "description")):
        existing_source = mongo.db["transactions"].find_one(
            {"_id": _oid(tx_id), "user_id": ObjectId(user_id), "deleted_at": None},
            {"source": 1},
        )
        if existing_source and existing_source.get("source") == "goal_contribution":
            raise ValidationError(
                "Goal contribution transactions are managed from the Goals page. "
                "Use the Goals page to adjust or delete this contribution."
            )

    if "category_id" in update_doc:
        # Manual recategorization: validate ownership AND log into corrections
        # collection so the (week 5) ML retrain has fresh feedback.
        cat_id = update_doc["category_id"]
        category_service.get(user_id, cat_id)
        update_doc["category_id"] = _oid(cat_id)
        existing = mongo.db["transactions"].find_one(
            {"_id": _oid(tx_id), "user_id": ObjectId(user_id)},
            {"description": 1, "category_id": 1},
        )
        if existing and existing.get("category_id") != _oid(cat_id):
            cat = mongo.db["categories"].find_one({"_id": _oid(cat_id)}, {"name": 1})
            if cat:
                mongo.db["corrections"].insert_one(
                    {
                        "user_id": ObjectId(user_id),
                        "description": existing["description"],
                        "chosen_category": cat["name"],
                        "created_at": utcnow(),
                    }
                )

    if "amount" in update_doc or "currency" in update_doc or "date" in update_doc:
        # Recompute amount_base whenever any of the conversion inputs change.
        existing_doc = mongo.db["transactions"].find_one(
            {"_id": _oid(tx_id), "user_id": ObjectId(user_id)},
            {"amount": 1, "currency": 1, "date": 1},
        )
        if not existing_doc:
            raise NotFoundError("Transaction not found")
        amount = update_doc.get("amount", existing_doc["amount"])
        currency = update_doc.get("currency", existing_doc["currency"])
        on_date = update_doc.get("date", existing_doc["date"])
        if isinstance(on_date, str):
            on_date = datetime.fromisoformat(on_date)
        base = _user_base_currency(user_id)
        update_doc["amount_base"] = _to_base_amount(amount, currency, base, on=on_date)

    update_doc["updated_at"] = utcnow()
    doc = mongo.db["transactions"].find_one_and_update(
        {"_id": _oid(tx_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": update_doc},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise NotFoundError("Transaction not found")
    return _to_public(doc, _category_name(doc.get("category_id")))


def delete(user_id: str, tx_id: str) -> None:
    # Same guard as update(): a deleted goal-contribution tx would leave
    # `goals.saved_amount` overstated. Route the user back through the
    # Goals page (which can manage the contribution + saved_amount
    # atomically).
    existing = mongo.db["transactions"].find_one(
        {"_id": _oid(tx_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"source": 1},
    )
    if existing and existing.get("source") == "goal_contribution":
        raise ValidationError(
            "Goal contribution transactions are managed from the Goals page. "
            "Use the Goals page to adjust or delete this contribution."
        )
    # Recurring-sourced transactions: the parent recurring_payments row
    # already rolled `next_due` forward when this tx was created (either
    # by the cron or by the manual "Pay" button). Deleting the tx in
    # isolation would leave the Planned page silently marked "paid" with
    # no matching ledger row — a desync the user can see as "I paid May
    # 1 rent" stuck rolled past while the transaction is gone. Edits are
    # still allowed (the actual paid amount can differ from the template);
    # only the destructive path is blocked.
    if existing and existing.get("source") == "recurring":
        raise ValidationError(
            "Planned-payment transactions are managed from the Planned page. "
            "Adjust or undo this payment from there."
        )
    res = mongo.db["transactions"].update_one(
        {"_id": _oid(tx_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"deleted_at": utcnow()}},
    )
    if res.matched_count == 0:
        raise NotFoundError("Transaction not found")


def recompute_amount_base_for_user(user_id: str) -> dict[str, int]:
    """Re-run FX conversion on every non-deleted transaction.

    Used when the user changes their base currency: the historical `amount_base`
    snapshots are no longer denominated in the right currency, so we rewrite
    them using the rate **at the transaction's own date** (Frankfurter
    historical endpoint, cached per date in `fx_rates`).

    Pre-warm pass: find the span of non-base-currency tx dates and ask
    Frankfurter for ALL ECB rates in that range in one HTTP call
    (`/v1/YYYY-MM-DD..YYYY-MM-DD`). Drops the previous "N tx → N
    Frankfurter calls" cost to "1 call, regardless of N" — the dominant
    factor in the 80-second base-currency swap users were hitting. The
    subsequent per-tx loop then resolves every `get_rate(..., on=date)`
    out of the local `fx_rates` cache.

    Returns counters for logging / smoke testing.
    """
    base = _user_base_currency(user_id)
    coll = mongo.db["transactions"]
    docs = list(coll.find(
        {"user_id": ObjectId(user_id), "deleted_at": None},
        {"amount": 1, "currency": 1, "date": 1},
    ))

    # Pre-warm FX cache for the entire date span of non-base-currency tx,
    # then load every cached row in that range into an in-memory dict so
    # the per-tx loop resolves rates without touching Mongo or HTTP.
    # Same-currency tx need no FX, so they don't contribute to the range.
    non_base_docs = [
        d for d in docs
        if (d.get("currency") or base) != base and d.get("date") is not None
    ]
    fx_cache: dict = {}
    if non_base_docs:
        min_date = min(d["date"] for d in non_base_docs)
        max_date = max(d["date"] for d in non_base_docs)
        try:
            fx_service.prewarm_range(min_date, max_date)
        except Exception:  # noqa: BLE001 — fall through to the per-tx live fetch
            log.exception("FX pre-warm failed; per-tx fetch will be slower")
        try:
            fx_cache = fx_service.load_range_cache(min_date, max_date)
        except Exception:  # noqa: BLE001 — empty cache forces per-tx fallback below
            log.exception("FX range cache load failed; per-tx fetch will be slower")

    # Stage updates as (filter, update) tuples so the fallback path can
    # re-issue per-row update_one without poking at UpdateOne internals.
    now = utcnow()
    updated = 0
    skipped = 0
    failed = 0
    ops_payload: list[tuple[dict, dict]] = []
    for doc in docs:
        currency = doc.get("currency") or base
        amount = float(doc.get("amount", 0))
        if currency == base:
            new_base = amount
        else:
            tx_date = doc.get("date")
            # Fast path: cached cross-rate from the pre-loaded range dict.
            # Falls back to the regular `get_rate` round-trip if the dict
            # has nothing on/before this tx's date (gap in Frankfurter
            # response or pre-warm failed).
            rate = fx_service.cross_rate_from_cache(fx_cache, currency, base, tx_date) if tx_date else None
            if rate is not None:
                new_base = float(amount) * rate
            else:
                try:
                    new_base = _to_base_amount(amount, currency, base, on=tx_date)
                except Exception:  # noqa: BLE001 — keep the backfill best-effort per row
                    failed += 1
                    continue
        ops_payload.append((
            {"_id": doc["_id"]},
            {"$set": {"amount_base": float(new_base), "updated_at": now}},
        ))
        if new_base == amount and currency != base:
            skipped += 1
        updated += 1

    if ops_payload:
        try:
            coll.bulk_write(
                [UpdateOne(f, u) for f, u in ops_payload],
                ordered=False,
            )
        except Exception:  # noqa: BLE001 — mongomock can't bulk_write, fall back
            log.exception("amount_base bulk_write failed; per-row fallback")
            failed_in_fallback = 0
            for f, u in ops_payload:
                try:
                    coll.update_one(f, u)
                except Exception:  # noqa: BLE001
                    failed_in_fallback += 1
            failed += failed_in_fallback
            updated -= failed_in_fallback
    return {"updated": updated, "skipped": skipped, "failed": failed}


def categorize_existing(user_id: str, tx_id: str) -> TransactionPublic:
    """Force re-run the rules cascade against the description and update."""
    doc = mongo.db["transactions"].find_one(
        {"_id": _oid(tx_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not doc:
        raise NotFoundError("Transaction not found")
    name = run_cascade(doc["description"])
    cat = category_service.find_by_name(user_id, name)
    if not cat:
        raise ValidationError("Category not found")
    return update(user_id, tx_id, TransactionUpdate(category_id=cat.id))
