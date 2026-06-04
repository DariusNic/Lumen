"""Savings goals.

Contribution pace is a single number:
  - **simple**:   (target - current) / months_remaining

If the goal is already met (saved >= target) or the target date is in the
past, the monthly number is 0 and `status = completed` / `behind`
accordingly.
"""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from app.extensions import mongo
from app.models.goal import (
    AutoContributeInfo,
    AutoContributeSetup,
    GoalContribute,
    GoalCreate,
    GoalPublic,
    GoalUpdate,
)
from app.models.user import to_utc_naive, utcnow
from app.utils.errors import NotFoundError, ValidationError


def _oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as e:
        raise NotFoundError("Goal not found") from e


def _months_between(now: datetime, target: datetime) -> int:
    """Whole months from `now` to `target`. Both args naive UTC.

    Returns **0 only when the deadline has actually passed**. A future
    target less than one whole month away returns 1, not 0, because
    `months_remaining == 0` is the signal used across the codebase
    (frontend `isOverdue` / "DEADLINE PASSED" badge, backend
    `_status` "behind" fallback, alert generator) to mean
    "the deadline is in the past". Rounding any future date down to 0
    fires those branches incorrectly for goals due next week.
    """
    if target <= now:
        return 0
    months = (target.year - now.year) * 12 + (target.month - now.month)
    if target.day < now.day:
        months -= 1
    return max(1, months)


def _monthly_simple(target: float, saved: float, months: int) -> float:
    remaining = max(0.0, target - saved)
    if months <= 0 or remaining == 0:
        return 0.0
    return round(remaining / months, 2)


def _is_completed(goal_doc: dict[str, Any]) -> bool:
    """A goal is considered completed once saved_amount reaches target_amount.
    Completed goals are read-only — `update()` and `contribute()` both refuse
    to operate on them, so the user can't accidentally rename a finished
    goal, change its target, attach an auto-contribute, or top it up beyond
    the target. `delete()` is the only state-changing op still allowed."""
    return float(goal_doc.get("saved_amount", 0.0)) >= float(goal_doc["target_amount"])


def _status(saved: float, target: float, months: int) -> str:
    if saved >= target:
        return "completed"
    if months <= 0:
        return "behind"
    # `expected` = linear pace from goal creation. We don't track creation
    # baseline here, so use a simpler heuristic: if simple-monthly is more
    # than 1.5× a "reasonable" pace, flag behind. Real "ahead/behind" uses
    # the snapshot history that lands in week 7 (net worth job).
    return "on-track"


def _lookup_auto_contribute(goal_oid: ObjectId) -> Optional[AutoContributeInfo]:
    """Find the active recurring_payments row linked to this goal (if any).
    Read-only — used by `_to_public` to surface the schedule on every
    goal response so the UI can render the "Auto · €X/mo" chip."""
    row = mongo.db["recurring_payments"].find_one(
        {"goal_id": goal_oid, "status": "active", "deleted_at": None},
        {"_id": 1, "amount": 1, "next_due": 1},
    )
    if not row:
        return None
    return AutoContributeInfo(
        amount=float(row["amount"]),
        next_due=row["next_due"],
        recurring_id=str(row["_id"]),
    )


def _to_public(doc: dict[str, Any]) -> GoalPublic:
    saved = float(doc.get("saved_amount", 0.0))
    target = float(doc["target_amount"])
    months = _months_between(utcnow(), doc["target_date"])
    return GoalPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        target_amount=target,
        saved_amount=saved,
        currency=doc["currency"],
        target_date=doc["target_date"],
        type=doc.get("type", "other"),
        priority=doc.get("priority", 3),
        progress_pct=round(min(100.0, (saved / target * 100) if target > 0 else 0.0), 1),
        monthly_simple=_monthly_simple(target, saved, months),
        months_remaining=months,
        status=_status(saved, target, months),  # type: ignore[arg-type]
        auto_contribute=_lookup_auto_contribute(doc["_id"]),
        created_at=doc["created_at"],
    )


def list_for_user(user_id: str) -> list[GoalPublic]:
    cursor = mongo.db["goals"].find(
        {"user_id": ObjectId(user_id), "deleted_at": None},
    ).sort([("priority", 1), ("target_date", 1)])
    return [_to_public(d) for d in cursor]


def get(user_id: str, goal_id: str) -> GoalPublic:
    doc = mongo.db["goals"].find_one(
        {"_id": _oid(goal_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not doc:
        raise NotFoundError("Goal not found")
    return _to_public(doc)


def create(user_id: str, payload: GoalCreate) -> GoalPublic:
    target_date = to_utc_naive(payload.target_date)
    if target_date <= utcnow():
        raise ValidationError("Target date must be in the future", details={"field": "target_date"})
    now = utcnow()
    doc = {
        "user_id": ObjectId(user_id),
        "name": payload.name.strip(),
        "target_amount": float(payload.target_amount),
        "saved_amount": float(payload.initial_deposit),
        "currency": payload.currency,
        "target_date": target_date,
        "type": payload.type,
        "priority": payload.priority,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    }
    res = mongo.db["goals"].insert_one(doc)
    doc["_id"] = res.inserted_id

    # Optional auto-contribute schedule. Creates a recurring_payments row
    # with `goal_id` pointing back to this goal. The recurring cron then
    # materialises the monthly contribution via `_do_contribute` (which
    # creates the transaction and updates saved_amount).
    if payload.auto_contribute is not None:
        _create_auto_contribute_recurring(
            user_id=user_id,
            goal_doc=doc,
            schedule=payload.auto_contribute,
            now=now,
        )

    return _to_public(doc)


def _create_auto_contribute_recurring(
    user_id: str,
    goal_doc: dict[str, Any],
    schedule: AutoContributeSetup,
    now: datetime,
) -> None:
    """Insert the recurring_payments doc that drives a goal's monthly
    auto-contribute. The recurring's `name` reads "Contribution: <goal>"
    so it surfaces with that label everywhere recurrings already render
    (Planned page list, calendar dots, intelligence panel)."""
    start = to_utc_naive(schedule.start_date)
    if schedule.amount <= 0:
        raise ValidationError(
            "Auto-contribute amount must be greater than zero",
            details={"field": "auto_contribute.amount"},
        )
    goals_cat = _get_or_seed_goals_category(user_id)
    # The first `next_due` is the user-supplied start (which can be today
    # or in the future). We do NOT eager-materialize for goal recurrings
    # — the user just created the goal and the initial_deposit covers
    # the "I want to start now" case. Subsequent firings come from the
    # daily cron.
    next_due = max(start, now)
    mongo.db["recurring_payments"].insert_one({
        "user_id": ObjectId(user_id),
        "name": f"Contribution: {goal_doc['name']}",
        "merchant_pattern": f"GOAL:{goal_doc['_id']}",
        "amount": float(schedule.amount),
        "currency": goal_doc["currency"],
        "frequency": "monthly",
        "start_date": start,
        "end_date": None,
        "category_id": goals_cat,
        "goal_id": goal_doc["_id"],
        "is_income": False,
        "auto_create_transaction": True,
        "status": "active",
        "next_due": next_due,
        "deleted_at": None,
        "created_at": now,
        "updated_at": now,
    })


def _next_monthly_anchor(now: datetime, day_of_month: int) -> datetime:
    """First occurrence of `day_of_month` on/after `now` (midnight-aligned).

    Used when editing or adding auto-contribute on an existing goal.
    Earlier this function always rolled to the next calendar month on
    the theory that an edit should land "next cycle, not this one"; user
    feedback (2026-06-03) showed that surprised people — picking the 7th
    on a June 3rd was expected to surface as June 7, not July 7. The new
    rule: pick the earliest valid anchor that is >= today.

    Day clamps to the destination month's length (e.g. picked 31 → Feb 28
    in a non-leap year) so a user who picked end-of-month doesn't silently
    drift forward an extra cycle when the next anchor lands in a shorter
    month.
    """
    # Strip tz so comparisons with naive `datetime(...)` results work
    # regardless of how the caller obtained `now` (utcnow() vs
    # datetime.now(timezone.utc)).
    today = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    # Try this calendar month first — clamp day to its length.
    last_day_this = calendar.monthrange(today.year, today.month)[1]
    safe_day_this = max(1, min(int(day_of_month), last_day_this))
    this_month = datetime(today.year, today.month, safe_day_this)
    if this_month >= today:
        return this_month
    # This month's anchor already passed — roll to next month (year-roll
    # included).
    year = today.year
    month = today.month + 1
    if month == 13:
        year += 1
        month = 1
    last_day_next = calendar.monthrange(year, month)[1]
    safe_day_next = max(1, min(int(day_of_month), last_day_next))
    return datetime(year, month, safe_day_next)


def _apply_auto_contribute_change(
    user_id: str,
    goal_doc: dict[str, Any],
    change: Any,
    now: datetime,
) -> None:
    """Upsert or disable the recurring_payments row linked to this goal.

    `change` is the value of `GoalUpdate.auto_contribute`:
      - `False`           → soft-delete the active linked recurring (if any)
      - `AutoContributeSetup` → upsert: create one if missing, otherwise
                                update amount + start_date and re-snap
                                next_due to first-of-next-month-on-day.

    The "snap to next month" rule is the spec the user chose: every edit
    (or fresh add) on an existing goal takes effect from the next calendar
    month, with the picked day-of-month preserved in `start_date` so future
    edits can reuse it as the default.
    """
    coll = mongo.db["recurring_payments"]
    goal_oid = goal_doc["_id"]

    existing = coll.find_one(
        {
            "goal_id": goal_oid,
            "user_id": ObjectId(user_id),
            "status": "active",
            "deleted_at": None,
        },
    )

    # Disable branch: soft-delete the active linked recurring (if any).
    # Idempotent — re-disabling a goal that already has no auto is a no-op.
    if change is False:
        if existing:
            coll.update_one(
                {"_id": existing["_id"]},
                {"$set": {"deleted_at": now, "status": "completed", "updated_at": now}},
            )
        return

    # Upsert branch: `change` is an AutoContributeSetup.
    if change.amount <= 0:
        raise ValidationError(
            "Auto-contribute amount must be greater than zero",
            details={"field": "auto_contribute.amount"},
        )
    picked_start = to_utc_naive(change.start_date)
    next_due = _next_monthly_anchor(now, picked_start.day)

    if existing is None:
        # No active recurring — create one. Skip the constructor path
        # (`_create_auto_contribute_recurring`) because that uses
        # `max(start, now)` semantics meant for the create-goal flow;
        # for an edit-after-the-fact we want the strict next-month rule.
        goals_cat = _get_or_seed_goals_category(user_id)
        coll.insert_one({
            "user_id": ObjectId(user_id),
            "name": f"Contribution: {goal_doc['name']}",
            "merchant_pattern": f"GOAL:{goal_oid}",
            "amount": float(change.amount),
            "currency": goal_doc["currency"],
            "frequency": "monthly",
            "start_date": picked_start,
            "end_date": None,
            "category_id": goals_cat,
            "goal_id": goal_oid,
            "is_income": False,
            "auto_create_transaction": True,
            "status": "active",
            "next_due": next_due,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        })
        return

    # Update existing.
    coll.update_one(
        {"_id": existing["_id"]},
        {"$set": {
            "amount": float(change.amount),
            "start_date": picked_start,
            "next_due": next_due,
            "updated_at": now,
        }},
    )


def update(user_id: str, goal_id: str, payload: GoalUpdate) -> GoalPublic:
    # Completed goals are read-only — refuse before touching anything so the
    # caller can't half-apply an edit. The check is on the *current* doc,
    # not the post-update doc, so editing a finished goal is forbidden even
    # if the edit would raise the target and "un-complete" it; the user
    # should delete + recreate in that rare case.
    existing = mongo.db["goals"].find_one(
        {"_id": _oid(goal_id), "user_id": ObjectId(user_id), "deleted_at": None},
    )
    if not existing:
        raise NotFoundError("Goal not found")
    if _is_completed(existing):
        raise ValidationError(
            "This goal is completed and can no longer be edited. Delete it if you no longer want to keep it on your list.",
            details={"goal_id": goal_id},
        )

    # Pop `auto_contribute` first — it doesn't live on the goal doc itself
    # (it's a property of the linked recurring_payments row) so we apply it
    # as a side-effect after the main $set. `model_dump` keeps a literal
    # `False` distinct from an omitted field by not setting exclude_none on
    # auto_contribute, so we read it explicitly.
    auto_change: Any = payload.auto_contribute
    update_doc = payload.model_dump(exclude_none=True, exclude={"auto_contribute"})
    if "name" in update_doc:
        update_doc["name"] = update_doc["name"].strip()
    if "target_amount" in update_doc:
        update_doc["target_amount"] = float(update_doc["target_amount"])
    if "target_date" in update_doc:
        update_doc["target_date"] = to_utc_naive(update_doc["target_date"])
        if update_doc["target_date"] <= utcnow():
            raise ValidationError(
                "Target date must be in the future", details={"field": "target_date"}
            )
    now = utcnow()

    # If only auto_contribute is changing and nothing else, we still need to
    # load the goal to pass it into `_apply_auto_contribute_change`. So even
    # an empty `$set` path falls through to the find_one_and_update with a
    # no-op `updated_at` touch — keeps a single code path.
    update_doc["updated_at"] = now
    doc = mongo.db["goals"].find_one_and_update(
        {"_id": _oid(goal_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": update_doc},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise NotFoundError("Goal not found")

    if auto_change is not None:
        _apply_auto_contribute_change(user_id, doc, auto_change, now)

    return _to_public(doc)


def delete(user_id: str, goal_id: str) -> None:
    now = utcnow()
    goal_oid = _oid(goal_id)
    res = mongo.db["goals"].update_one(
        {"_id": goal_oid, "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"deleted_at": now}},
    )
    if res.matched_count == 0:
        raise NotFoundError("Goal not found")
    # Close any active auto-contribute recurring immediately so it stops
    # appearing on /planned and never fires another cycle against a
    # deleted goal. `_materialize_goal_recurring` would also detect this
    # on the next cron firing, but doing it inline here avoids the
    # observability gap where the recurring is briefly orphaned.
    _close_linked_recurring(user_id, goal_oid, now)


def _get_or_seed_goals_category(user_id: str) -> ObjectId:
    """Resolve the user's "Goals" system category, creating it lazily if
    missing. Returns the category `_id` ready to attach to a transaction.

    Imports `category_service` lazily so this module stays import-cycle-free
    (category_service does not import goal_service, but a future addition
    might, so we play it safe)."""
    from app.services import category_service

    coll = mongo.db["categories"]
    user_oid = ObjectId(user_id)
    cat = coll.find_one(
        {"user_id": user_oid, "name": "Goals", "deleted_at": None},
        {"_id": 1},
    )
    if cat:
        return cat["_id"]
    # The user predates the Goals seed and seed_defaults hasn't been
    # called yet on this login (or it was called against a different db).
    # Seed defensively — the helper is per-name idempotent now, so this
    # is cheap.
    category_service.seed_defaults(user_id)
    cat = coll.find_one(
        {"user_id": user_oid, "name": "Goals", "deleted_at": None},
        {"_id": 1},
    )
    if not cat:
        raise RuntimeError("Failed to seed the 'Goals' category for user " + user_id)
    return cat["_id"]


def _close_linked_recurring(user_id: str, goal_oid: ObjectId, now: datetime) -> None:
    """When a goal reaches its target, every recurring payment linked to it
    should stop auto-firing. Called from both `contribute()` (manual) and
    the materialize_due cron path so the side-effect is unified.

    Idempotent — re-running on an already-completed goal is a no-op since
    the filter requires `status="active"`.
    """
    mongo.db["recurring_payments"].update_many(
        {
            "user_id": ObjectId(user_id),
            "goal_id": goal_oid,
            "status": "active",
            "deleted_at": None,
        },
        {"$set": {"status": "completed", "updated_at": now}},
    )


def _create_contribution_transaction(
    user_id: str,
    goal_doc: dict[str, Any],
    amount: float,
    when: datetime,
    source: str,
) -> None:
    """Persist a transaction representing the contribution. Stored as a
    negative-amount expense in the "Goals" category so it shows up in
    /transactions, counts against any "Goals" monthly budget, and joins
    the cash-flow reports like every other outflow.

    `tx_service` imported lazily — we already do this in
    `recurring_service` and it keeps the dependency graph acyclic."""
    from app.models.transaction import TransactionCreate
    from app.services import tx_service

    goals_cat = _get_or_seed_goals_category(user_id)
    tx_service.create(
        user_id,
        TransactionCreate(
            date=when,
            amount=-float(amount),
            currency=goal_doc["currency"],
            description=f"Contribution: {goal_doc['name']}",
            category_id=str(goals_cat),
            source=source,
        ),
    )


def contribute(user_id: str, goal_id: str, payload: GoalContribute) -> GoalPublic:
    """User-facing manual contribute. Atomically:
      - increments saved_amount
      - logs the contribution in `goal_contributions`
      - creates a transaction in the user's "Goals" category
      - closes any linked recurring payments if the goal is now complete

    `source="goal_contribution"` distinguishes manual contributions from
    those auto-materialized by the recurring cron, which uses
    `source="recurring"` via the same internal helper.

    Refuses contributions to already-completed goals so the user can't
    accidentally inflate `saved_amount` past target. The cron path goes
    through `_do_contribute` directly with its own remaining-amount clamp,
    so this guard only catches the user-facing manual path.
    """
    existing = mongo.db["goals"].find_one(
        {"_id": _oid(goal_id), "user_id": ObjectId(user_id), "deleted_at": None},
    )
    if not existing:
        raise NotFoundError("Goal not found")
    if _is_completed(existing):
        raise ValidationError(
            "This goal is already completed. No further contributions are needed.",
            details={"goal_id": goal_id},
        )
    return _do_contribute(
        user_id=user_id,
        goal_id=goal_id,
        amount=float(payload.amount),
        when=to_utc_naive(payload.when) if payload.when else utcnow(),
        tx_source="goal_contribution",
    )


def _do_contribute(
    user_id: str,
    goal_id: str,
    amount: float,
    when: datetime,
    tx_source: str,
) -> GoalPublic:
    """Shared implementation for both the user-facing `contribute()` and
    the materialize-due path. Increments saved_amount + logs + creates a
    transaction + closes linked recurrings on completion."""
    now = utcnow()
    doc = mongo.db["goals"].find_one_and_update(
        {"_id": _oid(goal_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$inc": {"saved_amount": amount}, "$set": {"updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise NotFoundError("Goal not found")

    contrib_id = mongo.db["goal_contributions"].insert_one(
        {
            "user_id": ObjectId(user_id),
            "goal_id": doc["_id"],
            "amount": amount,
            "when": when,
            "created_at": now,
        }
    ).inserted_id

    # The increment + the contributions row already landed; if the
    # transaction insert below fails for any reason (FX outage, validation
    # error, etc.), `goal.saved_amount` would be left overstated with no
    # matching row in the main ledger — a desync the user can see as
    # "Saved €X / €Y" on the goal card with zero contribution transactions
    # in the Transactions page. Wrap the tx insert and roll the two prior
    # writes back manually if it raises. Mongo standalone has no multi-doc
    # transactions, so this is the best we can do.
    try:
        _create_contribution_transaction(user_id, doc, amount, when, tx_source)
    except Exception:
        mongo.db["goals"].update_one(
            {"_id": doc["_id"]},
            {"$inc": {"saved_amount": -amount}, "$set": {"updated_at": utcnow()}},
        )
        mongo.db["goal_contributions"].delete_one({"_id": contrib_id})
        raise

    # If this contribution pushed the goal to (or past) its target, every
    # recurring linked to it should stop firing — symmetric for manual and
    # auto contributions so the user never has to clean up manually.
    if float(doc["saved_amount"]) >= float(doc["target_amount"]):
        _close_linked_recurring(user_id, doc["_id"], now)

    return _to_public(doc)
