from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.user import UserUpdate
from app.services import user_service
from app.utils.errors import ValidationError

bp = Blueprint("me", __name__)


@bp.get("/me")
@jwt_required()
def get_me():
    user = user_service.get_me(get_jwt_identity())
    return jsonify({"user": user.model_dump(mode="json")})


@bp.patch("/me")
@jwt_required()
def patch_me():
    body = request.get_json(silent=True) or {}
    try:
        payload = UserUpdate(**body)
    except PydanticValidationError as e:
        details = {}
        for err in e.errors():
            field = err["loc"][0] if err["loc"] else "body"
            details[field] = err["msg"]
        raise ValidationError("Invalid request", details=details) from e
    user = user_service.update_me(get_jwt_identity(), payload)
    return jsonify({"user": user.model_dump(mode="json")})
