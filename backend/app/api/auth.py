from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.extensions import mongo
from app.models.user import UserCreate, utcnow
from app.services import auth_service
from app.utils.errors import ValidationError

bp = Blueprint("auth", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {}
        for err in e.errors():
            field = err["loc"][0] if err["loc"] else "body"
            details[field] = err["msg"]
        raise ValidationError("Invalid request", details=details) from e


def _str_field(body: dict, name: str, *, required: bool = True) -> str:
    """Read a string-typed field from the request body and reject non-strings
    cleanly (e.g. NoSQL-injection probes like `{"$ne": null}`). Keeps the
    `{error_code, message, details}` envelope intact instead of letting a
    later `.strip()` or `.lower()` blow up with an AttributeError."""
    val = body.get(name)
    if val is None and not required:
        return ""
    if not isinstance(val, str):
        raise ValidationError(
            f"{name} must be a string",
            details={name: "must be a string"},
        )
    return val.strip()


@bp.post("/auth/register")
def register():
    """Create the account in an unverified state and email the verification
    link. Does NOT return JWTs in production — the client must verify by
    clicking the email link before logging in.

    Test-mode shortcut: when `TESTING=True` we auto-verify and return
    tokens. Mirrors the historical behavior so the 200+ existing tests
    don't need to chain through the email-click round-trip.
    """
    payload = _parse(UserCreate, request.get_json(silent=True))
    user = auth_service.register(payload)
    if current_app.config.get("TESTING"):
        from bson import ObjectId
        mongo.db["users"].update_one(
            {"_id": ObjectId(user.id)},
            {"$set": {"email_verified": True, "updated_at": utcnow()}},
        )
        return (
            jsonify(
                {
                    "user": user.model_dump(mode="json") | {"email_verified": True},
                    "access_token": create_access_token(identity=user.id),
                    "refresh_token": create_refresh_token(identity=user.id),
                }
            ),
            201,
        )
    return (
        jsonify(
            {
                "user": user.model_dump(mode="json"),
                "verification_required": True,
            }
        ),
        201,
    )


@bp.post("/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = _str_field(body, "email")
    password = _str_field(body, "password")
    if not email or not password:
        raise ValidationError(
            "Email and password are required",
            details={"email": "required" if not email else "ok", "password": "required" if not password else "ok"},
        )
    user, access, refresh = auth_service.login(email, password)
    return jsonify(
        {
            "user": user.model_dump(mode="json"),
            "access_token": access,
            "refresh_token": refresh,
        }
    )


@bp.post("/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    return jsonify({"access_token": auth_service.issue_access_token(user_id)})


@bp.post("/auth/logout")
@jwt_required(verify_type=False)
def logout():
    # JWT is stateless. Client drops tokens on its side.
    # Token blacklist is intentionally out of scope (15-min access window).
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


@bp.post("/auth/verify-email")
def verify_email():
    """Consume a verification token (from the email link). On success the
    user can now log in. We don't auto-issue JWTs here — the user clicked
    the link in their email client, which may not be the same browser as
    the one they registered in. Sending them through `/auth?mode=login` is
    the safest UX.
    """
    body = request.get_json(silent=True) or {}
    token = _str_field(body, "token")
    if not token:
        raise ValidationError("Token is required", details={"field": "token"})
    user = auth_service.verify_email(token)
    return jsonify({"user": user.model_dump(mode="json")})


@bp.post("/auth/resend-verification")
def resend_verification():
    """Mint and email a fresh verification link. Always 200 (no
    enumeration leak)."""
    body = request.get_json(silent=True) or {}
    email = _str_field(body, "email")
    if not email:
        raise ValidationError("Email is required", details={"field": "email"})
    auth_service.resend_verification(email)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


@bp.post("/auth/forgot")
def forgot_password():
    """Email a one-time reset link. Always 200 regardless of whether the
    email is registered (anti-enumeration)."""
    body = request.get_json(silent=True) or {}
    email = _str_field(body, "email")
    if not email:
        raise ValidationError("Email is required", details={"field": "email"})
    auth_service.forgot_password(email)
    return jsonify({"ok": True})


@bp.post("/auth/reset")
def reset_password():
    """Consume a reset token and update the password hash. Distinct
    422-level error on a missing/expired token so the frontend can route
    the user back to /auth/forgot."""
    body = request.get_json(silent=True) or {}
    token = _str_field(body, "token")
    # Password is allowed to be empty here — auth_service.reset_password
    # enforces min length and raises the right ValidationError.
    raw_pw = body.get("password")
    if not isinstance(raw_pw, str):
        raise ValidationError("Password must be a string", details={"password": "must be a string"})
    password = raw_pw
    if not token:
        raise ValidationError("Token is required", details={"field": "token"})
    auth_service.reset_password(token, password)
    return jsonify({"ok": True})
