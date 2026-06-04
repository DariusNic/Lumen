"""One-time tokens for email verification and password reset.

Tokens live in a single collection `email_tokens` keyed by random opaque
string. Each row tracks: user, purpose, expiry, consumed-at timestamp.

Two reasons for a single collection instead of stuffing tokens onto the
user document: per-token TTL indexing (Mongo can auto-delete expired
rows), and a clean audit trail for security analysis.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, Literal, Optional

from bson import ObjectId
from flask import current_app

from app.extensions import mongo
from app.models.user import utcnow

TokenPurpose = Literal["verify_email", "reset_password"]

_COLLECTION = "email_tokens"
# 32 url-safe characters → 256 bits of entropy. Long enough to make brute force
# infeasible while staying short in URLs.
_TOKEN_BYTES = 32

# Per-(user, purpose) cooldown. Anti-abuse: stops attackers / bugs from
# flooding a victim's inbox with verification or reset emails.
RESEND_COOLDOWN = timedelta(seconds=60)


def can_mint(user_id: str, purpose: TokenPurpose) -> bool:
    """Return False when the previous token of the same purpose was created
    within `RESEND_COOLDOWN`. Used by resend-verification and forgot-password
    routes to absorb spam without leaking whether the email exists."""
    if purpose not in ("verify_email", "reset_password"):
        return True
    cutoff = utcnow() - RESEND_COOLDOWN
    latest = mongo.db[_COLLECTION].find_one(
        {
            "user_id": ObjectId(user_id),
            "purpose": purpose,
            "created_at": {"$gte": cutoff},
        },
        sort=[("created_at", -1)],
    )
    return latest is None


def mint(user_id: str, purpose: TokenPurpose) -> str:
    """Create a fresh token and persist it. Returns the opaque string the
    caller must email out — we never re-derive it from the DB."""
    if purpose not in ("verify_email", "reset_password"):
        raise ValueError(f"Unknown token purpose: {purpose}")

    ttl: timedelta = (
        current_app.config["EMAIL_VERIFICATION_TTL"]
        if purpose == "verify_email"
        else current_app.config["PASSWORD_RESET_TTL"]
    )
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = utcnow()
    mongo.db[_COLLECTION].insert_one(
        {
            "token": token,
            "user_id": ObjectId(user_id),
            "purpose": purpose,
            "created_at": now,
            "expires_at": now + ttl,
            "consumed_at": None,
        }
    )
    return token


def consume(token: str, purpose: TokenPurpose) -> Optional[str]:
    """Look up + atomically mark a token as used.

    Returns the user_id (as string) on success, or None if the token is
    missing, expired, already consumed, or for the wrong purpose.
    """
    if not token:
        return None
    now = utcnow()
    doc: Optional[dict[str, Any]] = mongo.db[_COLLECTION].find_one_and_update(
        {
            "token": token,
            "purpose": purpose,
            "consumed_at": None,
            "expires_at": {"$gt": now},
        },
        {"$set": {"consumed_at": now}},
    )
    if not doc:
        return None
    return str(doc["user_id"])


def invalidate_for_user(user_id: str, purpose: TokenPurpose) -> None:
    """Burn every outstanding token of the given purpose for a user.

    Used when resending verification (kill old links) or after a successful
    password reset (kill sibling reset links so they can't be reused).
    """
    mongo.db[_COLLECTION].update_many(
        {
            "user_id": ObjectId(user_id),
            "purpose": purpose,
            "consumed_at": None,
        },
        {"$set": {"consumed_at": utcnow()}},
    )


def ensure_index() -> None:
    """Idempotent TTL + lookup indexes. Called once at app startup."""
    coll = mongo.db[_COLLECTION]
    coll.create_index("token", unique=True)
    # Mongo will auto-delete expired rows shortly after `expires_at` passes.
    coll.create_index("expires_at", expireAfterSeconds=0)
    coll.create_index([("user_id", 1), ("purpose", 1)])


__all__ = [
    "TokenPurpose",
    "mint",
    "consume",
    "invalidate_for_user",
    "ensure_index",
    "can_mint",
    "RESEND_COOLDOWN",
]
