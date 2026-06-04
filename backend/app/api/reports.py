from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.services import report_service
from app.utils.errors import ValidationError

bp = Blueprint("reports", __name__)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Accept "2026-05-01" and full ISO 8601 alike.
        if len(value) == 10:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValidationError(f"Invalid date format: {value}") from e


@bp.get("/reports/spending")
@jwt_required()
def spending():
    date_from = _parse_iso(request.args.get("from"))
    date_to = _parse_iso(request.args.get("to"))
    return jsonify(
        report_service.spending_by_category(get_jwt_identity(), date_from, date_to)
    )


@bp.get("/reports/monthly")
@jwt_required()
def monthly():
    try:
        months = int(request.args.get("months", "6"))
    except ValueError as e:
        raise ValidationError("`months` must be an integer") from e
    if months < 1 or months > 24:
        raise ValidationError("`months` must be between 1 and 24")
    # Optional `end=YYYY-MM` query param anchors the window to that month
    # (inclusive). When omitted the service falls back to the current month.
    end_raw = request.args.get("end")
    end_dt = None
    if end_raw:
        try:
            # Accept either "YYYY-MM" or a full ISO date — only the month
            # boundary matters downstream.
            end_dt = datetime.strptime(end_raw, "%Y-%m") if len(end_raw) == 7 else _parse_iso(end_raw)
        except (ValueError, TypeError) as e:
            raise ValidationError("`end` must be YYYY-MM or ISO date") from e
    return jsonify(report_service.monthly_summary(get_jwt_identity(), months, end=end_dt))


@bp.get("/reports/merchants")
@jwt_required()
def top_merchants():
    date_from = _parse_iso(request.args.get("from"))
    date_to = _parse_iso(request.args.get("to"))
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError as e:
        raise ValidationError("`limit` must be an integer") from e
    if limit < 1 or limit > 50:
        raise ValidationError("`limit` must be between 1 and 50")
    return jsonify(
        report_service.top_merchants(get_jwt_identity(), date_from, date_to, limit)
    )
