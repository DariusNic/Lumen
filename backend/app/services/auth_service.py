import logging
from typing import Any

from bson import ObjectId
from flask_jwt_extended import create_access_token, create_refresh_token
from pymongo.errors import DuplicateKeyError

from app.extensions import bcrypt, mongo
from app.models.user import UserCreate, UserPublic, utcnow
from app.services import account_service, category_service, email_service, portfolio_service, token_service
from app.utils.errors import AppError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationError


class EmailNotVerifiedError(ForbiddenError):
    """Raised on a login attempt against an account that hasn't clicked the
    verification link yet. Carries the user's email in `details` so the
    frontend can prefill the resend-verification form."""

    error_code = "EMAIL_NOT_VERIFIED"


_ = AppError  # re-exported for callers that catch the base class

log = logging.getLogger(__name__)


def _to_public(doc: dict[str, Any]) -> UserPublic:
    return UserPublic(
        id=str(doc["_id"]),
        email=doc["email"],
        full_name=doc["full_name"],
        base_currency=doc["base_currency"],
        email_verified=bool(doc.get("email_verified", False)),
        created_at=doc["created_at"],
    )


def register(payload: UserCreate) -> UserPublic:
    """Create the account in an *unverified* state and email the
    verification link. Does NOT issue JWTs — the client must verify by
    clicking the email link before logging in.

    Concurrency: relies on the unique index on `users.email` rather than a
    racy find-then-insert pre-check. Two simultaneous registers with the
    same email both make it past Python-side validation; the loser is
    caught by `DuplicateKeyError` and surfaced as the standard
    `VALIDATION_ERROR` envelope.
    """
    users = mongo.db["users"]
    email = payload.email.lower()
    pw_hash = bcrypt.generate_password_hash(payload.password).decode("utf-8")
    now = utcnow()
    doc = {
        "email": email,
        "password_hash": pw_hash,
        "full_name": payload.full_name,
        "base_currency": payload.base_currency,
        "email_verified": False,
        "created_at": now,
        "updated_at": now,
    }
    try:
        res = users.insert_one(doc)
    except DuplicateKeyError as e:
        raise ValidationError(
            "An account with this email already exists",
            details={"field": "email"},
        ) from e
    doc["_id"] = res.inserted_id
    user = _to_public(doc)
    # Seed the 14 system categories so the user has somewhere to assign transactions.
    category_service.seed_defaults(user.id)
    # Seed the 3 default accounts (Cash + Paper Portfolio + Net cash flow).
    account_service.seed_defaults(user.id, payload.base_currency)
    # Seed the empty $10,000 paper-trading portfolio.
    portfolio_service.seed_for_user(user.id)
    # Mint a verification token and email the link. Failure here must not
    # roll back the account — the user can request a resend from /auth.
    try:
        token = token_service.mint(user.id, "verify_email")
        email_service.send_verification_email(
            to_email=user.email,
            full_name=user.full_name,
            token=token,
        )
    except Exception:  # noqa: BLE001 — email infra is best-effort
        log.exception("verification email failed for user=%s", user.id)
    return user


def login(email: str, password: str) -> tuple[UserPublic, str, str]:
    users = mongo.db["users"]
    doc = users.find_one({"email": email.lower()})
    if not doc or not bcrypt.check_password_hash(doc["password_hash"], password):
        raise UnauthorizedError("Email or password incorrect")
    if not doc.get("email_verified", False):
        # 403 with a distinct error_code so the frontend can show a
        # "verify your email" affordance instead of the generic auth error.
        raise EmailNotVerifiedError(
            "Please verify your email address before logging in. Check your inbox for the link we sent.",
            details={"email": doc["email"]},
        )
    user = _to_public(doc)
    # Self-heal anything that pre-dates the seeding logic. All three calls
    # are idempotent — if the user already has the data, they're cheap no-ops.
    category_service.seed_defaults(user.id)
    account_service.seed_defaults(user.id, user.base_currency)
    portfolio_service.seed_for_user(user.id)
    return user, create_access_token(identity=user.id), create_refresh_token(identity=user.id)


def issue_access_token(user_id: str) -> str:
    return create_access_token(identity=user_id)


def get_user_by_id(user_id: str) -> UserPublic:
    users = mongo.db["users"]
    try:
        oid = ObjectId(user_id)
    except Exception as e:
        raise NotFoundError("User not found") from e
    doc = users.find_one({"_id": oid})
    if not doc:
        raise NotFoundError("User not found")
    return _to_public(doc)


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def verify_email(token: str) -> UserPublic:
    """Consume a verification token and mark the user verified. Returns the
    updated public user record so the frontend can confirm which account
    was activated."""
    user_id = token_service.consume(token, "verify_email")
    if not user_id:
        raise ValidationError(
            "This verification link is invalid or has expired. Request a new one from the login screen.",
            details={"field": "token"},
        )
    users = mongo.db["users"]
    doc = users.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": {"email_verified": True, "updated_at": utcnow()}},
        return_document=True,
    )
    if not doc:
        raise NotFoundError("User not found")
    # The atomic update returns the *pre*-update doc; reload to surface the
    # new flag value in the response.
    doc = users.find_one({"_id": ObjectId(user_id)}) or doc
    return _to_public(doc)


def resend_verification(email: str) -> None:
    """Mint a fresh verification token and email it. No-op (and no error)
    for unknown emails, already-verified accounts, or accounts within the
    per-user cooldown window — protects against email-enumeration AND
    spam-flooding of a victim's inbox.
    """
    users = mongo.db["users"]
    doc = users.find_one({"email": email.lower()})
    if not doc or doc.get("email_verified", False):
        return
    user_id = str(doc["_id"])
    # Throttle: refuse to mint if the last send was within the cooldown
    # window. Silent (no error response) for anti-enumeration.
    if not token_service.can_mint(user_id, "verify_email"):
        log.info("resend verification throttled for user=%s", user_id)
        return
    # Burn any older outstanding verification links so the inbox isn't
    # littered with stale ones (only the latest one works).
    token_service.invalidate_for_user(user_id, "verify_email")
    try:
        token = token_service.mint(user_id, "verify_email")
        email_service.send_verification_email(
            to_email=doc["email"],
            full_name=doc["full_name"],
            token=token,
        )
    except Exception:  # noqa: BLE001
        log.exception("resend verification failed for user=%s", user_id)


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def forgot_password(email: str) -> None:
    """Mint a reset token and email the link. No-op for unknown emails or
    callers within the per-user cooldown window — anti-enumeration AND
    anti-spam-flood. Returns nothing so the route can always 200."""
    users = mongo.db["users"]
    doc = users.find_one({"email": email.lower()})
    if not doc:
        return
    user_id = str(doc["_id"])
    if not token_service.can_mint(user_id, "reset_password"):
        log.info("forgot-password throttled for user=%s", user_id)
        return
    token_service.invalidate_for_user(user_id, "reset_password")
    try:
        token = token_service.mint(user_id, "reset_password")
        email_service.send_password_reset_email(
            to_email=doc["email"],
            full_name=doc["full_name"],
            token=token,
        )
    except Exception:  # noqa: BLE001
        log.exception("password-reset email failed for user=%s", user_id)


def reset_password(token: str, new_password: str) -> None:
    """Consume a reset token and update the user's password hash. Raises
    ValidationError on a bad/expired token."""
    if len(new_password) < 8:
        raise ValidationError(
            "Password must be at least 8 characters",
            details={"field": "password"},
        )
    user_id = token_service.consume(token, "reset_password")
    if not user_id:
        raise ValidationError(
            "This password reset link is invalid or has expired. Request a new one.",
            details={"field": "token"},
        )
    pw_hash = bcrypt.generate_password_hash(new_password).decode("utf-8")
    users = mongo.db["users"]
    res = users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": pw_hash, "updated_at": utcnow()}},
    )
    if res.matched_count == 0:
        raise NotFoundError("User not found")
    # Burn any other outstanding reset links the user might have requested
    # — the password is now changed; old links should not work either.
    token_service.invalidate_for_user(user_id, "reset_password")
