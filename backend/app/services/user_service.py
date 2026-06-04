import logging

from bson import ObjectId
from pymongo import ReturnDocument

from app.extensions import mongo
from app.models.user import UserPublic, UserUpdate, utcnow
from app.services.auth_service import _to_public
from app.utils.errors import NotFoundError

log = logging.getLogger(__name__)


def _oid(user_id: str) -> ObjectId:
    try:
        return ObjectId(user_id)
    except Exception as e:
        raise NotFoundError("User not found") from e


def get_me(user_id: str) -> UserPublic:
    doc = mongo.db["users"].find_one({"_id": _oid(user_id)})
    if not doc:
        raise NotFoundError("User not found")
    return _to_public(doc)


def update_me(user_id: str, payload: UserUpdate) -> UserPublic:
    from app.services import fx_service
    from app.utils.errors import ValidationError

    update = payload.model_dump(exclude_none=True)
    if not update:
        return get_me(user_id)

    # Detect a base-currency change so we can backfill derived data after the
    # write. Read the current value once before the update.
    new_base = update.get("base_currency")
    old_doc = mongo.db["users"].find_one({"_id": _oid(user_id)}, {"base_currency": 1})
    old_base = (old_doc or {}).get("base_currency")
    base_changed = new_base is not None and new_base != old_base

    # Pre-flight FX: refuse to flip the base if Frankfurter (and the cache) are
    # unavailable, BEFORE writing the new base. Otherwise we'd end up with
    # `users.base_currency=EUR` but `transactions.amount_base` still in RON,
    # which is exactly the corruption the user reported. Failing loudly here
    # is the right move — the user retries when the feed is back.
    if base_changed:
        try:
            fx_service.get_rate(old_base, new_base)
        except ValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface unexpected failures
            log.exception("FX pre-flight failed: %s", exc)
            raise ValidationError(
                "Can't change base currency right now — exchange-rate feed is "
                "unavailable. Please try again in a few minutes.",
                details={"reason": "fx_preflight_failed"},
            ) from exc

    update["updated_at"] = utcnow()
    doc = mongo.db["users"].find_one_and_update(
        {"_id": _oid(user_id)},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise NotFoundError("User not found")

    if base_changed:
        _on_base_currency_change(user_id, new_base, old_base)

    return _to_public(doc)


def _on_base_currency_change(user_id: str, new_base: str, old_base: str) -> None:
    """Three derived bits of state must move when a user's base currency changes:

    1. **Every transaction's `amount_base`.** It was stored at the rate valid
       on the transaction date relative to the *old* base. We re-run the
       conversion against the *new* base, fetching historical Frankfurter
       rates per transaction date.
    2. **The auto-tracked "Net cash flow" account's `currency`.** Its balance
       is computed live as `sum(amount_base)`, so the currency stamp on it
       must equal the user's base, otherwise the Accounts totals re-conversion
       layer would double-convert.
    3. **Every category's `monthly_budget`.** The field has no currency stamp
       — the implicit contract is "in the user's base currency". When base
       flips, we convert with today's rate (budgets are forward-looking, not
       historical, so a date-stamped historical lookup would be wrong).

    The user's manual accounts (Cash, plus anything they added) keep their own
    currency — base-currency change should not silently rewrite a "BCR Cash
    RON 5000" account into "BCR Cash EUR 5000". Same for goals + recurring
    payments which already carry their own `currency` field.
    """
    # Lazy imports avoid an import cycle (tx_service depends on fx_service,
    # user_service is on the auth path).
    from app.services import fx_service, tx_service

    try:
        stats = tx_service.recompute_amount_base_for_user(user_id)
        log.info(
            "base-currency change for user=%s → recomputed %s tx (%s failed)",
            user_id, stats["updated"], stats["failed"],
        )
    except Exception:  # noqa: BLE001 — never fail the /me PATCH on a backfill error
        log.exception("amount_base backfill failed for user=%s", user_id)

    mongo.db["accounts"].update_one(
        {
            "user_id": ObjectId(user_id),
            "source_ref": "transactions:net",
            "deleted_at": None,
        },
        {"$set": {"currency": new_base, "last_updated": utcnow()}},
    )

    # Convert monthly_budget on every category from old_base → new_base. We
    # only touch rows where the budget is > 0 (zero budgets are "not set" and
    # don't need rewriting). Today's rate is the right choice for forward-
    # looking targets.
    try:
        rate = fx_service.get_rate(old_base, new_base)
    except Exception:  # noqa: BLE001 — leave budgets untouched if FX is unavailable
        log.exception("monthly_budget conversion skipped for user=%s — FX unavailable", user_id)
        return
    if rate == 1.0:
        return
    cursor = mongo.db["categories"].find(
        {
            "user_id": ObjectId(user_id),
            "deleted_at": None,
            "monthly_budget": {"$gt": 0},
        },
        {"monthly_budget": 1},
    )
    for cat in cursor:
        new_budget = round(float(cat["monthly_budget"]) * rate, 2)
        mongo.db["categories"].update_one(
            {"_id": cat["_id"]},
            {"$set": {"monthly_budget": new_budget}},
        )
