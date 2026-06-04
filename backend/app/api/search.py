from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.services import search_service
from app.utils.errors import ValidationError

bp = Blueprint("search", __name__)


@bp.get("/search")
@jwt_required()
def search():
    q = request.args.get("q", "").strip()
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError as e:
        raise ValidationError("`limit` must be an integer") from e
    if limit < 1 or limit > 50:
        raise ValidationError("`limit` must be between 1 and 50")
    return jsonify(search_service.search(get_jwt_identity(), q, limit))
