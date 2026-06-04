from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.alert import AlertReadRequest
from app.services import alert_service
from app.utils.errors import ValidationError

bp = Blueprint("alerts", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/alerts")
@jwt_required()
def list_alerts():
    return jsonify(alert_service.list_for_user(get_jwt_identity()))


@bp.post("/alerts/read")
@jwt_required()
def mark_read():
    """Mark one or more alerts as read.

    Body `{ids: [...]}` marks those specific ids; `{}` (or `{ids: []}`)
    marks every currently-visible alert as read.
    """
    payload = _parse(AlertReadRequest, request.get_json(silent=True))
    user_id = get_jwt_identity()
    if payload.ids:
        alert_service.mark_read(user_id, payload.ids)
        return jsonify({"ok": True, "marked": len(payload.ids)})
    marked = alert_service.mark_all_read(user_id)
    return jsonify({"ok": True, "marked": marked})
