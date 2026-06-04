from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.goal import GoalContribute, GoalCreate, GoalUpdate
from app.services import goal_service
from app.utils.errors import ValidationError

bp = Blueprint("goals", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/goals")
@jwt_required()
def list_goals():
    items = goal_service.list_for_user(get_jwt_identity())
    return jsonify({"goals": [g.model_dump(mode="json") for g in items]})


@bp.post("/goals")
@jwt_required()
def create_goal():
    payload = _parse(GoalCreate, request.get_json(silent=True))
    g = goal_service.create(get_jwt_identity(), payload)
    return jsonify({"goal": g.model_dump(mode="json")}), 201


@bp.get("/goals/<goal_id>")
@jwt_required()
def get_goal(goal_id: str):
    g = goal_service.get(get_jwt_identity(), goal_id)
    return jsonify({"goal": g.model_dump(mode="json")})


@bp.patch("/goals/<goal_id>")
@jwt_required()
def update_goal(goal_id: str):
    payload = _parse(GoalUpdate, request.get_json(silent=True))
    g = goal_service.update(get_jwt_identity(), goal_id, payload)
    return jsonify({"goal": g.model_dump(mode="json")})


@bp.delete("/goals/<goal_id>")
@jwt_required()
def delete_goal(goal_id: str):
    goal_service.delete(get_jwt_identity(), goal_id)
    return jsonify({"ok": True})


@bp.post("/goals/<goal_id>/contribute")
@jwt_required()
def contribute_to_goal(goal_id: str):
    payload = _parse(GoalContribute, request.get_json(silent=True))
    g = goal_service.contribute(get_jwt_identity(), goal_id, payload)
    return jsonify({"goal": g.model_dump(mode="json")})
