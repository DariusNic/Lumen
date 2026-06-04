from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.recurring import RecurringCreate, RecurringUpdate
from app.services import recurring_service
from app.utils.errors import ValidationError

bp = Blueprint("recurring", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/recurring")
@jwt_required()
def list_recurring():
    items = recurring_service.list_for_user(get_jwt_identity())
    return jsonify({"recurring": [r.model_dump(mode="json") for r in items]})


@bp.post("/recurring")
@jwt_required()
def create_recurring():
    payload = _parse(RecurringCreate, request.get_json(silent=True))
    r = recurring_service.create(get_jwt_identity(), payload)
    return jsonify({"recurring": r.model_dump(mode="json")}), 201


@bp.get("/recurring/<recurring_id>")
@jwt_required()
def get_recurring(recurring_id: str):
    r = recurring_service.get(get_jwt_identity(), recurring_id)
    return jsonify({"recurring": r.model_dump(mode="json")})


@bp.patch("/recurring/<recurring_id>")
@jwt_required()
def update_recurring(recurring_id: str):
    payload = _parse(RecurringUpdate, request.get_json(silent=True))
    r = recurring_service.update(get_jwt_identity(), recurring_id, payload)
    return jsonify({"recurring": r.model_dump(mode="json")})


@bp.delete("/recurring/<recurring_id>")
@jwt_required()
def delete_recurring(recurring_id: str):
    recurring_service.delete(get_jwt_identity(), recurring_id)
    return jsonify({"ok": True})


@bp.post("/recurring/<recurring_id>/mark-paid")
@jwt_required()
def mark_paid(recurring_id: str):
    """User-initiated "I paid this" — creates the transaction for the
    current cycle and rolls next_due forward by one frequency step. Use
    when the recurring has `auto_create_transaction=False` and the user
    just paid out-of-band (e.g. bank transfer for rent). The Planned
    page's "Pay" button hits this endpoint."""
    rec = recurring_service.mark_paid(get_jwt_identity(), recurring_id)
    return jsonify({"recurring": rec.model_dump(mode="json")})


@bp.get("/recurring/calendar")
@jwt_required()
def calendar_view():
    """Calendar grid for a given (year, month). Defaults to the current month."""
    now = datetime.now(timezone.utc)
    try:
        year = int(request.args.get("year", str(now.year)))
        month = int(request.args.get("month", str(now.month)))
    except ValueError as e:
        raise ValidationError("`year` and `month` must be integers") from e
    if month < 1 or month > 12:
        raise ValidationError("`month` must be between 1 and 12")
    return jsonify(recurring_service.calendar(get_jwt_identity(), year, month))


@bp.post("/recurring/detect")
@jwt_required()
def detect_recurring():
    """Run the Levenshtein-based detection scan and return suggestions.

    The user confirms each suggestion via a follow-up POST /api/recurring; we
    do not auto-create anything from this endpoint.
    """
    result = recurring_service.detect(get_jwt_identity())
    return jsonify(result.model_dump(mode="json"))
