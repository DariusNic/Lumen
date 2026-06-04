"""FX endpoint — thin wrapper over `fx_service`.

`GET /api/fx/convert?from=USD&to=RON&amount=100&on=2026-05-08`
  → `{ "from": "USD", "to": "RON", "amount": 100, "converted": 497.0, "rate": 4.97, "on": "2026-05-08" }`

`on` is optional; defaults to today. The conversion uses the same cached daily
ECB rate that's applied to transactions, so the user sees consistent numbers
between this endpoint and what's stored in `amount_base`.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.models.user import utcnow
from app.services import fx_service
from app.utils.errors import ValidationError

bp = Blueprint("fx", __name__)


@bp.get("/fx/convert")
@jwt_required()
def convert_endpoint():
    from_ccy = (request.args.get("from") or "").upper()
    to_ccy = (request.args.get("to") or "").upper()
    amount_raw = request.args.get("amount")
    on_raw = request.args.get("on")

    if not from_ccy or not to_ccy:
        raise ValidationError("Both `from` and `to` are required")
    try:
        amount = float(amount_raw) if amount_raw is not None else 1.0
    except (TypeError, ValueError) as e:
        raise ValidationError("`amount` must be a number") from e
    on_dt = None
    if on_raw:
        try:
            on_dt = datetime.fromisoformat(on_raw)
        except ValueError as e:
            raise ValidationError("`on` must be ISO-8601 (YYYY-MM-DD)") from e

    rate = fx_service.get_rate(from_ccy, to_ccy, on=on_dt)
    return jsonify({
        "from": from_ccy,
        "to": to_ccy,
        "amount": amount,
        "converted": round(amount * rate, 4),
        "rate": rate,
        "on": (on_dt or utcnow()).date().isoformat(),
    })
