from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.category import CategoryCreate, CategoryUpdate
from app.services import category_service
from app.utils.errors import ValidationError

bp = Blueprint("categories", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/categories")
@jwt_required()
def list_categories():
    items = category_service.list_for_user(get_jwt_identity())
    return jsonify({"categories": [c.model_dump(mode="json") for c in items]})


@bp.post("/categories")
@jwt_required()
def create_category():
    payload = _parse(CategoryCreate, request.get_json(silent=True))
    cat = category_service.create(get_jwt_identity(), payload)
    return jsonify({"category": cat.model_dump(mode="json")}), 201


@bp.patch("/categories/<category_id>")
@jwt_required()
def update_category(category_id: str):
    payload = _parse(CategoryUpdate, request.get_json(silent=True))
    cat = category_service.update(get_jwt_identity(), category_id, payload)
    return jsonify({"category": cat.model_dump(mode="json")})


@bp.delete("/categories/<category_id>")
@jwt_required()
def delete_category(category_id: str):
    category_service.delete(get_jwt_identity(), category_id)
    return jsonify({"ok": True})
