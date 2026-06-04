"""Net worth endpoints — thin wrappers over `networth_service`.

Routes (all `@jwt_required()`):
  - `GET  /api/networth`            — current totals + delta vs ~30 days ago
  - `GET  /api/networth/history`    — time series for a `range` preset
  - `POST /api/networth/snapshot`   — force a snapshot today (idempotent)
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.services import networth_service
from app.utils.errors import ValidationError

bp = Blueprint("networth", __name__)

_VALID_RANGES = {"1M", "3M", "6M", "1Y", "ALL"}


@bp.get("/networth")
@jwt_required()
def get_current():
    cur = networth_service.current(get_jwt_identity())
    return jsonify(cur.model_dump(mode="json"))


@bp.get("/networth/history")
@jwt_required()
def get_history():
    range_key = (request.args.get("range") or "3M").upper()
    if range_key not in _VALID_RANGES:
        raise ValidationError(
            "Invalid `range`",
            details={"value": range_key, "allowed": sorted(_VALID_RANGES)},
        )
    h = networth_service.history(get_jwt_identity(), range_key=range_key)  # type: ignore[arg-type]
    return jsonify(h.model_dump(mode="json"))


@bp.post("/networth/snapshot")
@jwt_required()
def post_snapshot():
    snap = networth_service.take_snapshot(get_jwt_identity(), source="manual")
    return jsonify({"snapshot": snap.model_dump(mode="json")}), 201
