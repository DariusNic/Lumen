"""Generate alerts on-demand from current state.

No scheduled job, no materialized rows: every `GET /alerts` request rebuilds
the list from the underlying data (budgets, goals, recurring payments) and
applies the user's persisted "read" state from the
`alert_states` collection. This keeps alerts perfectly in sync with the
data — when a budget overrun goes away because the user re-categorized a
transaction, the alert disappears with no cleanup job needed.

Each rule produces alerts whose `id` is deterministic for the underlying
condition (e.g. `goal_behind:<goal_id>`), so dismiss/read state survives
across requests as long as the underlying condition holds.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable

from bson import ObjectId

from app.extensions import mongo
from app.models.alert import AlertGroup, AlertPublic
from app.models.user import to_utc_naive, utcnow

log = logging.getLogger(__name__)

# When a recurring payment's `next_due` is within this many days, we surface
# it as a reminder. Single global cutoff — there's intentionally no per-row
# override (the form doesn't expose one).
RECURRING_REMINDER_DAYS = 7

# Budget overrun thresholds (% of monthly budget consumed).
BUDGET_OVERRUN_PCT = 1.0   # >= 100% → critical
BUDGET_AT_RISK_PCT = 0.8   # 80–100% → warning


def _group_for(ts: datetime, now: datetime) -> AlertGroup:
    """Bucket a timestamp into one of the four UI sections."""
    delta = now - ts
    if delta.days <= 0:
        return "Today"
    if delta.days == 1:
        return "Yesterday"
    if delta.days <= 7:
        return "This week"
    return "Earlier"


def _read_ids(user_id: str) -> set[str]:
    doc = mongo.db["alert_states"].find_one({"user_id": ObjectId(user_id)})
    if not doc:
        return set()
    return set(doc.get("read_ids", []))


def list_for_user(user_id: str) -> dict[str, Any]:
    """Build the alert feed for a user. Returns `{alerts, unread_count}`."""
    now = utcnow()
    read = _read_ids(user_id)

    alerts: list[AlertPublic] = []
    # Each rule is independent — failures should not block the rest.
    for rule in (
        _budget_overruns,
        _goal_status,
        _recurring_due,
    ):
        try:
            alerts.extend(rule(user_id, now))
        except Exception as exc:  # noqa: BLE001 — alerts are best-effort
            log.warning("Alert rule %s failed: %s", rule.__name__, exc)

    # Stamp read state + group bucket from the alert's own timestamp.
    for a in alerts:
        a.unread = a.id not in read
        a.group = _group_for(a.timestamp, now)

    alerts.sort(key=lambda a: a.timestamp, reverse=True)
    return {
        "alerts": [a.model_dump(mode="json") for a in alerts],
        "unread_count": sum(1 for a in alerts if a.unread),
    }


def mark_read(user_id: str, ids: Iterable[str]) -> None:
    id_list = [i for i in ids if i]
    if not id_list:
        return
    mongo.db["alert_states"].update_one(
        {"user_id": ObjectId(user_id)},
        {
            "$addToSet": {"read_ids": {"$each": id_list}},
            "$set": {"updated_at": utcnow()},
            "$setOnInsert": {"user_id": ObjectId(user_id), "created_at": utcnow()},
        },
        upsert=True,
    )


def mark_all_read(user_id: str) -> int:
    """Recompute the live alert set and dismiss every visible id. Returns
    the number of alerts marked. Used by the 'Mark all as read' button."""
    feed = list_for_user(user_id)
    ids = [a["id"] for a in feed["alerts"] if a.get("unread")]
    if ids:
        mark_read(user_id, ids)
    return len(ids)


# --- Rule implementations --------------------------------------------------


def _budget_overruns(user_id: str, now: datetime) -> list[AlertPublic]:
    """Compare this month's category spend to each category's
    `monthly_budget`. Skip categories with budget=0 (means "no budget set").
    """
    cats = list(
        mongo.db["categories"].find(
            {"user_id": ObjectId(user_id), "monthly_budget": {"$gt": 0}},
            {"_id": 1, "name": 1, "monthly_budget": 1},
        )
    )
    if not cats:
        return []

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent_pipeline = [
        {
            "$match": {
                "user_id": ObjectId(user_id),
                "deleted_at": None,
                "date": {"$gte": month_start},
                "amount_base": {"$lt": 0},
                "category_id": {"$in": [c["_id"] for c in cats]},
            }
        },
        {
            "$group": {
                "_id": "$category_id",
                "spent": {"$sum": {"$abs": "$amount_base"}},
            }
        },
    ]
    spent_by_cat: dict[ObjectId, float] = {
        r["_id"]: float(r["spent"]) for r in mongo.db["transactions"].aggregate(spent_pipeline)
    }

    out: list[AlertPublic] = []
    month_key = now.strftime("%Y-%m")
    for c in cats:
        budget = float(c["monthly_budget"])
        spent = spent_by_cat.get(c["_id"], 0.0)
        if spent <= 0 or budget <= 0:
            continue
        ratio = spent / budget
        if ratio < BUDGET_AT_RISK_PCT:
            continue
        is_over = ratio >= BUDGET_OVERRUN_PCT
        cat_name = c["name"]
        cat_id = str(c["_id"])
        out.append(
            AlertPublic(
                id=f"budget_overrun:{cat_id}:{month_key}",
                severity="critical" if is_over else "warning",
                icon="pie-chart",
                title=(
                    f"You're over budget on {cat_name}"
                    if is_over
                    else f"{cat_name} is approaching its budget"
                ),
                message=(
                    f"Spent {spent:,.2f} of {budget:,.2f} this month "
                    f"— {ratio * 100:.0f}% of limit."
                ),
                timestamp=now,
                group="Today",  # overwritten by caller
                unread=True,
                link="/budget",
                source="budget_overrun",
            )
        )
    return out


def _goal_status(user_id: str, now: datetime) -> list[AlertPublic]:
    """Surface goals that are behind schedule. Imported lazily because
    goal_service is heavier than the others."""
    from app.services import goal_service

    out: list[AlertPublic] = []
    try:
        goals = goal_service.list_for_user(user_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("goal_service.list_for_user failed: %s", exc)
        return out

    for g in goals:
        if g.status != "behind":
            continue
        if g.months_remaining <= 0:
            message = (
                f"The deadline has passed and only {g.progress_pct:.0f}% is saved. "
                f"Adjust the target date or contribute the remaining amount."
            )
        else:
            message = (
                f"{g.progress_pct:.0f}% saved with {g.months_remaining} month"
                f"{'s' if g.months_remaining != 1 else ''} left — "
                f"needs {g.monthly_simple:,.0f}/month to catch up."
            )
        out.append(
            AlertPublic(
                id=f"goal_behind:{g.id}",
                severity="warning",
                icon="flag",
                title=f"{g.name} is behind schedule",
                message=message,
                timestamp=now,
                group="Today",
                unread=True,
                link="/goals",
                source="goal_behind",
            )
        )
    return out


def _recurring_due(user_id: str, now: datetime) -> list[AlertPublic]:
    """One alert per recurring payment due in the next N days."""
    cutoff = now + timedelta(days=RECURRING_REMINDER_DAYS)
    cursor = mongo.db["recurring_payments"].find(
        {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "status": "active",
            "is_income": False,
            "next_due": {"$gte": now, "$lte": cutoff},
        }
    ).sort([("next_due", 1)])

    out: list[AlertPublic] = []
    for r in cursor:
        next_due: datetime = r["next_due"]
        days_to = (next_due.date() - now.date()).days
        when = (
            "tomorrow" if days_to == 1
            else "today" if days_to == 0
            else f"in {days_to} days"
        )
        out.append(
            AlertPublic(
                id=f"recurring_due:{r['_id']}:{next_due.date().isoformat()}",
                severity="info",
                icon="repeat",
                title=f"Planned payment due {when}",
                message=(
                    f"{r.get('name', r.get('merchant_pattern', 'Payment'))} "
                    f"({r.get('amount', 0):,.0f} {r.get('currency', '')}) "
                    f"is scheduled for {next_due.strftime('%b %d')}."
                ),
                timestamp=now,
                group="Today",
                unread=True,
                link="/recurring",
                source="recurring_due",
            )
        )
    return out
