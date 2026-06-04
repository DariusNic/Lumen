import logging

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import OperationFailure

log = logging.getLogger(__name__)


def _safe_create(collection, keys, **kwargs) -> None:
    """Tolerant `create_index` wrapper.

    The historical failure mode is `IndexKeySpecsConflict` (code 86) when the
    collection already has an index with the same generated name but
    different options (e.g. legacy `user_id_1` without `unique=True` vs the
    current spec with `unique=True`). When that happens we drop the legacy
    index and recreate it. Without this, **a single mismatched index aborts
    `ensure_indexes` and every subsequent index in the function is skipped
    silently** — a real defect surfaced in the v2.2 testing session where
    `email_tokens` ended up with no indexes at all (no `token` uniqueness,
    no `expires_at` TTL).
    """
    name = "_".join(f"{k}_{v}" for k, v in keys)
    try:
        collection.create_index(keys, **kwargs)
    except OperationFailure as e:
        # 86 = IndexKeySpecsConflict
        if e.code == 86:
            log.warning("re-creating mismatched index %s.%s", collection.name, name)
            try:
                collection.drop_index(name)
            except OperationFailure:
                log.exception("drop_index %s.%s failed", collection.name, name)
                return
            collection.create_index(keys, **kwargs)
        else:
            raise


def ensure_indexes(db: Database) -> None:
    """Create compound indexes for all 11 collections. Idempotent — safe to run on every startup."""
    _safe_create(db["users"], [("email", ASCENDING)], unique=True)

    _safe_create(db["transactions"], [("user_id", ASCENDING), ("date", DESCENDING)])
    _safe_create(db["transactions"], [("user_id", ASCENDING), ("category_id", ASCENDING)])

    _safe_create(db["categories"], [("user_id", ASCENDING)])

    _safe_create(db["goals"], [("user_id", ASCENDING)])

    _safe_create(db["recurring_payments"], [("user_id", ASCENDING), ("next_due", ASCENDING)])

    # Exactly one portfolio per user. Unique enforces the seed_for_user
    # idempotency contract at the DB level — a duplicate insert raises
    # rather than silently creating two portfolios for the same user.
    _safe_create(db["portfolios"], [("user_id", ASCENDING)], unique=True)
    # Trades log — hot reads are by user, sorted by date desc.
    _safe_create(db["portfolio_trades"], [("user_id", ASCENDING), ("date", DESCENDING)])

    _safe_create(db["stock_data"], [("ticker", ASCENDING), ("date", ASCENDING)], unique=True)

    _safe_create(db["ml_predictions"], [("ticker", ASCENDING), ("date", DESCENDING)])

    _safe_create(db["alerts"], [("user_id", ASCENDING), ("created_at", DESCENDING)])

    # v3 additions
    _safe_create(db["accounts"], [("user_id", ASCENDING)])
    _safe_create(db["net_worth_snapshots"], [("user_id", ASCENDING), ("date", DESCENDING)])
    # One alert-state document per user — holds the set of dismissed alert ids.
    _safe_create(db["alert_states"], [("user_id", ASCENDING)], unique=True)
    # FX rate cache — one document per (date, base) pair. Lookups always hit the
    # newest row at-or-before the transaction date, so date is the hot index key.
    _safe_create(db["fx_rates"], [("date", DESCENDING)], unique=True)

    # Email tokens (verification + password reset). Unique on token + TTL
    # cleanup on `expires_at` (Mongo auto-deletes expired rows).
    _safe_create(db["email_tokens"], [("token", ASCENDING)], unique=True)
    # `expireAfterSeconds=0` makes Mongo auto-delete rows once `expires_at`
    # passes. Use a string key (not a list) because that's the form
    # `create_index` requires for a TTL-on-single-field index.
    try:
        db["email_tokens"].create_index("expires_at", expireAfterSeconds=0)
    except OperationFailure as e:
        if e.code == 86:
            db["email_tokens"].drop_index("expires_at_1")
            db["email_tokens"].create_index("expires_at", expireAfterSeconds=0)
        else:
            raise
    _safe_create(db["email_tokens"], [("user_id", ASCENDING), ("purpose", ASCENDING)])

    # One-time migration: mark all pre-existing users as email-verified so
    # they aren't locked out when the verification gate ships. Newly created
    # users default to email_verified=False at insert time.
    db["users"].update_many(
        {"email_verified": {"$exists": False}},
        {"$set": {"email_verified": True}},
    )
