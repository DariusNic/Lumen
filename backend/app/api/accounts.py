from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.account import AccountCreate, AccountUpdate
from app.services import account_service
from app.utils.errors import ValidationError

bp = Blueprint("accounts", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/accounts")
@jwt_required()
def list_accounts():
    items = account_service.list_for_user(get_jwt_identity())
    return jsonify(
        {
            "accounts": [a.model_dump(mode="json") for a in items],
            "totals": account_service.totals(get_jwt_identity()),
        }
    )


@bp.post("/accounts")
@jwt_required()
def create_account():
    payload = _parse(AccountCreate, request.get_json(silent=True))
    a = account_service.create(get_jwt_identity(), payload)
    return jsonify({"account": a.model_dump(mode="json")}), 201


@bp.get("/accounts/<account_id>")
@jwt_required()
def get_account(account_id: str):
    a = account_service.get(get_jwt_identity(), account_id)
    return jsonify({"account": a.model_dump(mode="json")})


@bp.patch("/accounts/<account_id>")
@jwt_required()
def update_account(account_id: str):
    payload = _parse(AccountUpdate, request.get_json(silent=True))
    a = account_service.update(get_jwt_identity(), account_id, payload)
    return jsonify({"account": a.model_dump(mode="json")})


@bp.delete("/accounts/<account_id>")
@jwt_required()
def delete_account(account_id: str):
    account_service.delete(get_jwt_identity(), account_id)
    return jsonify({"ok": True})
