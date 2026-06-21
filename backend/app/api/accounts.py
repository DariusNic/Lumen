from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.services import account_service

bp = Blueprint("accounts", __name__)


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
