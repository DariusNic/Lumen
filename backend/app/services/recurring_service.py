"""Recurring & one-off planned payments — CRUD + Levenshtein detection +
auto-materialization to real transactions.

`frequency = "once"` is a one-shot scheduled payment (a wedding gift, a planned
trip deposit, an annual tax bill). It still lives on the calendar and feeds the
forecast, but it does not roll forward — once materialized it transitions to
`status = "completed"` and stops appearing on the active list.
"""
import logging
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Any, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from app.extensions import mongo
from app.models.recurring import (
    DetectionResult,
    Frequency,
    RecurringCreate,
    RecurringPublic,
    RecurringUpdate,
)
from app.models.user import to_utc_naive, utcnow
from app.services import recurring_detection
from app.services.recurring_detection import TxRow
from app.utils.errors import NotFoundError, ValidationError

log = logging.getLogger(__name__)


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as e:
        raise NotFoundError("Recurring payment not found") from e


# ---------------------------------------------------------------------------
# Cadence math — used for "next_due" computation, calendar building, and the
# materialization roll-forward. Monthly/yearly walk calendar months (Jan 5 →
# Feb 5 → Mar 5), not 30-day strides, so an anchor on day-N stays on day-N
# across the year. Weekly/biweekly are fixed-step (no calendar drift).
# ---------------------------------------------------------------------------


def _add_cadence(d: datetime, frequency: str) -> datetime:
    """Advance `d` by one cadence step.

    Calendar-aware for `monthly` and `yearly` (so "every 5th of the month"
    rolls 5→5 across calendar months, not 5→4→3→… as `timedelta(days=30)`
    used to). Fixed-step for `weekly` / `biweekly` — no calendar drift
    concern there.

    Day clamps to the destination month's length to dodge ValueError on
    edge cases: Jan 31 + 1 month → Feb 28 (or Feb 29 in a leap year),
    Feb 29 + 1 year → Feb 28 (non-leap). Caller must guarantee
    `frequency != "once"` — one-off rows have no cadence to advance.
    """
    if frequency == "weekly":
        return d + timedelta(days=7)
    if frequency == "biweekly":
        return d + timedelta(days=14)
    if frequency == "monthly":
        year = d.year
        month = d.month + 1
        if month == 13:
            year += 1
            month = 1
        last_day = monthrange(year, month)[1]
        return d.replace(year=year, month=month, day=min(d.day, last_day))
    if frequency == "yearly":
        year = d.year + 1
        if d.month == 2 and d.day == 29:
            last_day = monthrange(year, 2)[1]
            return d.replace(year=year, day=last_day)
        return d.replace(year=year)
    raise ValueError(f"Unsupported frequency for cadence step: {frequency!r}")


def _compute_next_due(start: datetime, frequency: Frequency, now: Optional[datetime] = None) -> datetime:
    """The earliest scheduled occurrence on/after `now` (default: utcnow).

    For recurring frequencies, walks forward one cadence step at a time
    via `_add_cadence` — calendar-aware so a start anchored on day-5
    keeps surfacing on day-5 of each subsequent month, not drifting
    backward by ~1 day/month as the old 30-day stride did. For "once",
    the next_due is simply the start_date — there's no forward roll.
    """
    if frequency == "once":
        return start
    now = now or utcnow()
    cur = start
    while cur < now:
        cur = _add_cadence(cur, frequency)
    return cur


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _category_name(category_oid: Optional[ObjectId]) -> Optional[str]:
    if not category_oid:
        return None
    cat = mongo.db["categories"].find_one({"_id": category_oid}, {"name": 1})
    return cat["name"] if cat else None


def _user_base_currency(user_id: str) -> str:
    user = mongo.db["users"].find_one({"_id": ObjectId(user_id)}, {"base_currency": 1})
    return (user or {}).get("base_currency", "RON")


def _amount_base(amount: float, currency: str, base: str) -> Optional[float]:
    """Best-effort native→base conversion using today's rate. Returns None if
    FX is unavailable, so the frontend can fall back to the native amount
    rather than displaying a mixed-currency total."""
    if currency == base:
        return round(float(amount), 2)
    try:
        from app.services import fx_service  # local: avoid import cycle on startup
        return round(fx_service.convert(float(amount), currency, base), 2)
    except Exception:  # noqa: BLE001 — FX may be down in dev/tests
        return None


def _to_public(doc: dict[str, Any], base_currency: Optional[str] = None) -> RecurringPublic:
    cat_id = doc.get("category_id")
    amount = float(doc["amount"])
    currency = doc["currency"]
    base = base_currency or _user_base_currency(str(doc["user_id"]))
    return RecurringPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        merchant_pattern=doc["merchant_pattern"],
        amount=amount,
        amount_base=_amount_base(amount, currency, base),
        currency=currency,
        frequency=doc["frequency"],
        start_date=doc["start_date"],
        end_date=doc.get("end_date"),
        category_id=str(cat_id) if cat_id else None,
        category_name=_category_name(cat_id) if cat_id else None,
        goal_id=str(doc["goal_id"]) if doc.get("goal_id") else None,
        is_income=bool(doc.get("is_income", False)),
        auto_create_transaction=bool(doc.get("auto_create_transaction", False)),
        status=doc.get("status", "active"),
        next_due=doc["next_due"],
        created_at=doc["created_at"],
    )


def _default_auto_create(frequency: Frequency, override: Optional[bool]) -> bool:
    """A one-off planned payment defaults to auto-creating the transaction (the
    user explicitly committed to it). A recurring payment defaults to OFF to
    avoid double-counting against CSV imports of bank statements."""
    if override is not None:
        return bool(override)
    return frequency == "once"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_for_user(user_id: str, include_completed: bool = False) -> list[RecurringPublic]:
    filt: dict[str, Any] = {"user_id": ObjectId(user_id), "deleted_at": None}
    if not include_completed:
        filt["status"] = {"$ne": "completed"}
    cursor = mongo.db["recurring_payments"].find(filt).sort("next_due", 1)
    base = _user_base_currency(user_id)
    return [_to_public(d, base_currency=base) for d in cursor]


def get(user_id: str, recurring_id: str) -> RecurringPublic:
    doc = mongo.db["recurring_payments"].find_one(
        {"_id": _oid(recurring_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not doc:
        raise NotFoundError("Recurring payment not found")
    return _to_public(doc)


def create(user_id: str, payload: RecurringCreate) -> RecurringPublic:
    start = to_utc_naive(payload.start_date)
    end = to_utc_naive(payload.end_date) if payload.end_date else None
    now = utcnow()
    cat_oid: Optional[ObjectId] = None
    if payload.category_id:
        cat_oid = _oid(payload.category_id)
        if not mongo.db["categories"].find_one(
            {"_id": cat_oid, "user_id": ObjectId(user_id), "deleted_at": None}
        ):
            raise ValidationError("Category not found", details={"field": "category_id"})

    auto_create = _default_auto_create(payload.frequency, payload.auto_create_transaction)
    # Backdated start_date semantics:
    #   - Recurring (weekly / biweekly / monthly / yearly): treat the picked
    #     date as a *cadence anchor*. The first firing is the next future
    #     instance ≥ now produced by `_compute_next_due`. No back-fill ever,
    #     even when auto_create is on — back-filling weeks/months of past
    #     transactions on a single click is a UX trap (user clicked once;
    #     ten transactions appeared). The cron picks the first cycle up at
    #     its real future date.
    #   - One-off (`once`): there's no cadence to roll, so a backdated start
    #     is almost always a mistake. Refuse with a clear error; the form's
    #     date picker also blocks past dates client-side.
    if payload.frequency == "once" and start.date() < now.date():
        raise ValidationError(
            "Pick today or a future date for a one-off planned payment",
            details={"field": "start_date"},
        )
    initial_next_due = _compute_next_due(start, payload.frequency, now)

    doc = {
        "user_id": ObjectId(user_id),
        "name": payload.name.strip(),
        "merchant_pattern": payload.merchant_pattern.strip(),
        "amount": float(payload.amount),
        "currency": payload.currency,
        "frequency": payload.frequency,
        "start_date": start,
        # `end_date` is meaningless for "once" — the payment ends after one occurrence.
        "end_date": None if payload.frequency == "once" else end,
        "category_id": cat_oid,
        "is_income": bool(payload.is_income),
        "auto_create_transaction": auto_create,
        "status": "active",
        "next_due": initial_next_due,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    res = mongo.db["recurring_payments"].insert_one(doc)
    doc["_id"] = res.inserted_id

    return _to_public(doc)


def update(user_id: str, recurring_id: str, payload: RecurringUpdate) -> RecurringPublic:
    update_doc = payload.model_dump(exclude_none=True)
    if not update_doc:
        return get(user_id, recurring_id)

    # Read the existing doc up-front — we need it to detect actual value
    # changes vs no-op re-submits, and to decide whether to materialize
    # after an auto-toggle.
    previous = mongo.db["recurring_payments"].find_one(
        {"_id": _oid(recurring_id), "user_id": ObjectId(user_id), "deleted_at": None},
    )
    if not previous:
        raise NotFoundError("Recurring payment not found")

    # Normalize dates + validate category_id ownership
    if "start_date" in update_doc:
        update_doc["start_date"] = to_utc_naive(update_doc["start_date"])
    if "end_date" in update_doc:
        update_doc["end_date"] = to_utc_naive(update_doc["end_date"])
    if "category_id" in update_doc:
        cat_id = update_doc["category_id"]
        cat_oid = _oid(cat_id)
        if not mongo.db["categories"].find_one(
            {"_id": cat_oid, "user_id": ObjectId(user_id), "deleted_at": None}
        ):
            raise ValidationError("Category not found", details={"field": "category_id"})
        update_doc["category_id"] = cat_oid

    # Only recompute next_due when start_date or frequency *value* actually
    # changed. The edit form re-submits start_date on every save, so a
    # naive `"start_date" in update_doc` check rolls next_due forward on
    # every save (silently dropping the overdue badge with no transaction
    # logged — the bug fixed here).
    #
    # Compare DATE only — the form exposes only the date portion of
    # `start_date`, so the JS round-trip reconstructs it at noon local
    # time, producing a different *instant* even when the user changed
    # nothing. Datetime equality would treat that as a change.
    start_changed = (
        "start_date" in update_doc
        and update_doc["start_date"].date() != previous["start_date"].date()
    )
    freq_changed = (
        "frequency" in update_doc and update_doc["frequency"] != previous["frequency"]
    )
    if start_changed or freq_changed:
        new_start = update_doc.get("start_date", previous["start_date"])
        new_freq = update_doc.get("frequency", previous["frequency"])
        update_doc["next_due"] = _compute_next_due(new_start, new_freq)
        # Switching to "once" wipes any end_date the user had set under a recurring frequency.
        if new_freq == "once":
            update_doc["end_date"] = None

    # Detect a fresh auto-toggle (false → true). If the row is overdue
    # we materialize immediately so the user sees the missed transaction
    # straight away instead of waiting for the next 02:00 UTC cron.
    became_auto = (
        update_doc.get("auto_create_transaction") is True
        and not previous.get("auto_create_transaction", False)
    )

    update_doc["updated_at"] = utcnow()
    doc = mongo.db["recurring_payments"].find_one_and_update(
        {"_id": _oid(recurring_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": update_doc},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise NotFoundError("Recurring payment not found")

    if (
        became_auto
        and doc.get("status") == "active"
        and doc.get("next_due") is not None
        and doc["next_due"] <= utcnow()
    ):
        try:
            materialize_due(recurring_ids=[recurring_id])
        except Exception:  # noqa: BLE001 — never fail the update on materialize errors
            log.exception("auto-toggle materialize failed for recurring=%s", recurring_id)
        # Re-read to return the post-materialize state (rolled next_due / completed).
        refreshed = mongo.db["recurring_payments"].find_one({"_id": doc["_id"]})
        if refreshed:
            doc = refreshed
    return _to_public(doc)


def delete(user_id: str, recurring_id: str) -> None:
    res = mongo.db["recurring_payments"].update_one(
        {"_id": _oid(recurring_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"deleted_at": utcnow()}},
    )
    if res.matched_count == 0:
        raise NotFoundError("Recurring payment not found")


def calendar(user_id: str, year: int, month: int) -> dict[str, Any]:
    """Return all planned-payment occurrences that fall inside the given
    calendar month, keyed by day-of-month for easy rendering. Each
    recurring's `next_due` is the EARLIEST un-materialized firing — for
    future months we project forward by repeatedly adding the frequency's
    delta until we either land inside the month (record it) or pass it
    (give up on that recurring). One-offs only ever appear on their
    `next_due` day. Completed rows are excluded — they've already been
    materialized — by `list_for_user`'s default filter.
    """
    items = list_for_user(user_id)
    by_day: dict[int, list[dict[str, Any]]] = {}

    # First-of-month and first-of-next-month bounds for the projection.
    # Using day=1 + first-of-next-month gives us a clean `[month_start,
    # month_end_excl)` half-open interval without juggling end-of-month
    # day numbers.
    month_start = datetime(year, month, 1)
    if month == 12:
        month_end_excl = datetime(year + 1, 1, 1)
    else:
        month_end_excl = datetime(year, month + 1, 1)

    for r in items:
        nd = r.next_due
        end_date = r.end_date

        if r.frequency == "once":
            # Single firing — only show if its one date falls in this month.
            if nd.year == year and nd.month == month:
                by_day.setdefault(nd.day, []).append(r.model_dump(mode="json"))
            continue

        cur = nd
        # Safety bound: a yearly cadence at the absolute minimum needs
        # 5 iterations to cross a 5-year window; monthly needs ~60;
        # weekly needs ~260. Cap generously.
        for _ in range(400):
            if end_date is not None and cur > end_date:
                break
            if cur >= month_end_excl:
                # Walked past the target month — done with this row.
                break
            if cur >= month_start:
                by_day.setdefault(cur.day, []).append(r.model_dump(mode="json"))
                # Don't stop — a weekly recurring fires ~4 times per month.
            cur = _add_cadence(cur, r.frequency)

    return {"year": year, "month": month, "by_day": by_day}


# ---------------------------------------------------------------------------
# Detection runner — pulls transactions from Mongo, hands them to the pure
# algorithm, returns suggestions. Caller (the API) is the only piece touching
# Flask request state.
# ---------------------------------------------------------------------------

def detect(user_id: str, lookback_days: int = 90) -> DetectionResult:
    cutoff = utcnow() - timedelta(days=lookback_days)
    cursor = mongo.db["transactions"].find(
        {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "date": {"$gte": cutoff},
        },
        {"description": 1, "amount": 1, "currency": 1, "date": 1},
    )
    rows = [
        TxRow(
            description=d["description"],
            amount=float(d["amount"]),
            currency=d["currency"],
            date=d["date"],
        )
        for d in cursor
    ]
    return recurring_detection.detect(rows)


# ---------------------------------------------------------------------------
# Auto-materialization to real transactions
# ---------------------------------------------------------------------------

def mark_paid(
    user_id: str,
    recurring_id: str,
    *,
    when: Optional[datetime] = None,
) -> RecurringPublic:
    """User-initiated "I paid this" for a non-auto recurring payment.

    Use case: the user has a recurring with `auto_create_transaction=False`
    (e.g. rent paid by bank transfer the user types in manually). When the
    next_due date passes, the row shows "Xd overdue" on the Planned page.
    Clicking "Mark paid" should:
      1. Create the transaction for this cycle (same shape the cron would
         have made for an auto-recurring), so the user doesn't have to
         type it manually.
      2. Roll `next_due` forward exactly ONE cadence step. (Not "forward
         until > now" — the user is telling us about ONE specific payment
         they made; if there are multiple overdue cycles, they click
         "Mark paid" once per cycle.)
      3. For "once" frequency: mark `status="completed"` instead of
         rolling next_due — a one-off can only be paid once.
      4. For a goal-linked recurring: route through `_do_contribute` so
         saved_amount increments + completion auto-closes the recurring.

    Returns the refreshed RecurringPublic (next_due rolled, possibly
    status=completed). Raises NotFoundError if the row doesn't exist.
    """
    # Lazy imports to avoid the import cycle with goal_service/tx_service.
    from app.models.transaction import TransactionCreate
    from app.services import goal_service, tx_service

    when = when or utcnow()
    coll = mongo.db["recurring_payments"]
    doc = coll.find_one(
        {"_id": _oid(recurring_id), "user_id": ObjectId(user_id), "deleted_at": None},
    )
    if not doc:
        raise NotFoundError("Recurring payment not found")
    if doc.get("status") != "active":
        raise ValidationError(
            "Only active planned payments can be marked paid",
            details={"status": doc.get("status", "unknown")},
        )

    freq = doc["frequency"]
    amount_signed = float(doc["amount"]) * (1.0 if doc.get("is_income", False) else -1.0)
    category_id_str = str(doc["category_id"]) if doc.get("category_id") else None

    # Goal-linked → same path the cron uses, so saved_amount + tx + auto-close
    # all happen consistently.
    if doc.get("goal_id"):
        goal_service._do_contribute(
            user_id=user_id,
            goal_id=str(doc["goal_id"]),
            amount=float(doc["amount"]),
            when=when,
            tx_source="recurring",
        )
        # Refresh the recurring — _do_contribute may have closed it via
        # _close_linked_recurring if the goal hit its target.
        refreshed = coll.find_one({"_id": doc["_id"]})
        if refreshed and refreshed.get("status") == "active":
            # Still active → roll next_due forward one cycle.
            new_next_due = _add_cadence(refreshed["next_due"], freq)
            coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"next_due": new_next_due, "updated_at": utcnow()}},
            )
        doc = coll.find_one({"_id": doc["_id"]}) or refreshed
        return _to_public(doc)

    # Non-goal, non-auto: create the transaction the user just paid.
    # Use the cycle date when it's in the past (the natural overdue
    # case — "user paid the May 1 rent"), but clamp to `now` when
    # next_due is already in the future (Pydantic rejects future-dated
    # transactions, and "I paid it today" is more honest anyway).
    tx_date = doc["next_due"] if doc["next_due"] <= when else when
    tx_service.create(
        user_id,
        TransactionCreate(
            date=tx_date,
            amount=amount_signed,
            currency=doc["currency"],
            description=doc["name"],
            category_id=category_id_str,
            source="recurring",
        ),
    )

    if freq == "once":
        coll.update_one(
            {"_id": doc["_id"]},
            {"$set": {"status": "completed", "updated_at": utcnow()}},
        )
    else:
        new_next_due = _add_cadence(doc["next_due"], freq)
        coll.update_one(
            {"_id": doc["_id"]},
            {"$set": {"next_due": new_next_due, "updated_at": utcnow()}},
        )

    doc = coll.find_one({"_id": doc["_id"]})
    return _to_public(doc)


def materialize_due(
    now: Optional[datetime] = None,
    *,
    recurring_ids: Optional[list[str]] = None,
) -> dict[str, int]:
    """Scan active planned payments with `auto_create_transaction=True` and
    `next_due <= now`. For each due occurrence:
      - Insert a transaction (signed by `is_income`).
      - For "once": mark the row `status="completed"`.
      - For recurring: roll `next_due` forward in cadence steps until it's > now,
        creating one transaction per missed occurrence (handles offline catch-up).

    By default scans every user (used by the 02:00 UTC daily job). When
    `recurring_ids` is supplied, only those rows are considered — used by
    `create()` to eager-materialize a backdated payment without scanning the
    full universe (Q-ARCH-12 fix).

    Returns a small counter dict for logging / smoke-testing.
    Importing the tx service lazily so this module stays import-cycle-free.
    """
    from app.models.transaction import TransactionCreate
    from app.services import tx_service

    now = now or utcnow()
    coll = mongo.db["recurring_payments"]
    filt: dict[str, Any] = {
        "deleted_at": None,
        "status": "active",
        "auto_create_transaction": True,
        "next_due": {"$lte": now},
    }
    if recurring_ids is not None:
        filt["_id"] = {"$in": [_oid(rid) for rid in recurring_ids]}
    cursor = coll.find(filt)

    created = 0
    rolled = 0
    completed = 0

    for doc in cursor:
        user_id_str = str(doc["user_id"])
        freq = doc["frequency"]
        amount_signed = float(doc["amount"]) * (1.0 if doc.get("is_income", False) else -1.0)
        category_id_str = str(doc["category_id"]) if doc.get("category_id") else None

        # Goal-linked recurring: route through goal_service so the
        # contribution increments saved_amount AND creates a transaction
        # AND closes the recurring on completion — all in one place.
        # On the final cycle (saved would otherwise overshoot the target),
        # the contribution is clamped to the remaining amount.
        if doc.get("goal_id"):
            # Concurrency guard (same rationale as the regular path below):
            # claim the row by flipping `status` to a sentinel before doing
            # the work; if the claim fails, another process is already
            # handling it.
            n_created, n_rolled, n_completed, new_next_due, finished = _materialize_goal_recurring(
                doc, now=now, coll=coll,
            )
            created += n_created
            rolled += n_rolled
            completed += n_completed
            if finished:
                # status is updated inside _materialize_goal_recurring's
                # final cycle when target hit; here just stamp updated_at.
                coll.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"status": "completed", "updated_at": now}},
                )
            continue

        if freq == "once":
            # Single-shot: atomically claim by flipping status to "completed",
            # then create the transaction. Loser of the race skips silently.
            claim = coll.find_one_and_update(
                {"_id": doc["_id"], "status": "active"},
                {"$set": {"status": "completed", "updated_at": now}},
            )
            if claim is None:
                continue
            tx_service.create(
                user_id_str,
                TransactionCreate(
                    date=doc["next_due"],
                    amount=amount_signed,
                    currency=doc["currency"],
                    description=doc["name"],
                    category_id=category_id_str,
                    source="recurring",
                ),
            )
            created += 1
            completed += 1
            continue

        # Recurring: catch up on every missed occurrence.
        #
        # Concurrency guard: the cron and the boot catch-up can both fire
        # `materialize_due` within milliseconds of each other (different
        # APScheduler job IDs, no shared lock). Both open their cursors
        # before either has rolled `next_due` forward → both see the same
        # overdue row → both used to create a transaction. Symptom seen on
        # demo data: Salariu / Spotify duplicated, created_at deltas of 2-70 ms.
        #
        # Fix: advance `next_due` atomically *before* creating the tx, using
        # a conditional filter on the previous value. The first writer wins;
        # the second sees `matched_count == 0` and breaks out without
        # duplicating. Trade-off: if `tx_service.create` raises after the
        # claim succeeds, the cycle is silently dropped — but that's
        # rare (FX outage etc.) and the user can re-mark-paid manually.
        cur = doc["next_due"]
        while cur <= now:
            new_next_due = _add_cadence(cur, freq)
            claim = coll.find_one_and_update(
                {"_id": doc["_id"], "next_due": cur},
                {"$set": {"next_due": new_next_due, "updated_at": now}},
            )
            if claim is None:
                # Another process already advanced next_due for this row.
                break
            tx_service.create(
                user_id_str,
                TransactionCreate(
                    date=cur,
                    amount=amount_signed,
                    currency=doc["currency"],
                    description=doc["name"],
                    category_id=category_id_str,
                    source="recurring",
                ),
            )
            created += 1
            cur = new_next_due
            rolled += 1

    return {"created": created, "rolled": rolled, "completed": completed}


def _materialize_goal_recurring(
    doc: dict[str, Any],
    *,
    now: datetime,
    coll: Any,
) -> tuple[int, int, int, datetime, bool]:
    """Process one cycle of a goal-linked recurring. Returns
    `(created, rolled, completed, new_next_due, finished)` so the
    caller can write back the `status` (next_due is rolled inside this
    function, atomically).

    Each iteration of the catch-up loop re-reads the goal because each
    `_do_contribute` call updates `saved_amount` and may itself close
    the recurring (via `_close_linked_recurring`). The loop bails as
    soon as the goal is fully funded — and on the very last cycle,
    clamps the contribution to the exact remaining amount so the goal
    never overshoots its target.

    Concurrency: each cycle is claimed atomically by advancing
    `next_due` *before* the contribution lands. If a concurrent
    materialize_due already advanced it, the claim returns None and
    the loop exits — preventing duplicate contributions.
    """
    from app.services import goal_service

    goal_id = doc["goal_id"]
    user_id_str = str(doc["user_id"])
    freq = doc["frequency"]
    cur = doc["next_due"]
    monthly = float(doc["amount"])

    created = 0
    rolled = 0
    completed = 0
    finished = False

    while cur <= now:
        # Re-read the goal each iteration — prior contributions in this
        # loop may have completed it or shrunk the remaining amount.
        goal_doc = mongo.db["goals"].find_one(
            {"_id": goal_id, "user_id": doc["user_id"], "deleted_at": None},
        )
        if not goal_doc:
            # Goal was deleted out from under us — close the recurring.
            finished = True
            completed += 1
            break
        remaining = float(goal_doc["target_amount"]) - float(goal_doc.get("saved_amount", 0.0))
        if remaining <= 0:
            finished = True
            completed += 1
            break

        # Atomic claim: advance next_due before contributing. If the row's
        # next_due has changed since we read it, another process owns this
        # cycle.
        new_next_due = _add_cadence(cur, freq)
        claim = coll.find_one_and_update(
            {"_id": doc["_id"], "next_due": cur},
            {"$set": {"next_due": new_next_due, "updated_at": now}},
        )
        if claim is None:
            break

        payment = min(monthly, remaining)
        goal_service._do_contribute(
            user_id=user_id_str,
            goal_id=str(goal_id),
            amount=payment,
            when=cur,
            tx_source="recurring",
        )
        created += 1
        rolled += 1
        # After the contribute we might have hit exactly target — stop.
        new_saved = float(goal_doc.get("saved_amount", 0.0)) + payment
        if new_saved >= float(goal_doc["target_amount"]):
            finished = True
            completed += 1
            break
        cur = new_next_due

    return (created, rolled, completed, cur, finished)
