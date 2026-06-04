from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError as PydanticValidationError

from app.models.transaction import (
    TransactionCreate,
    TransactionListQuery,
    TransactionUpdate,
)
from app.services import csv_import_service, tx_service
from app.services.csv_import_service import ImportMapping
from app.utils.errors import ValidationError

bp = Blueprint("transactions", __name__)


def _parse(model, data):
    try:
        return model(**(data or {}))
    except PydanticValidationError as e:
        details = {(err["loc"][0] if err["loc"] else "body"): err["msg"] for err in e.errors()}
        raise ValidationError("Invalid request", details=details) from e


@bp.get("/transactions")
@jwt_required()
def list_transactions():
    q = _parse(TransactionListQuery, request.args.to_dict())
    result = tx_service.list_for_user(get_jwt_identity(), q)
    return jsonify(
        {
            "transactions": [t.model_dump(mode="json") for t in result["transactions"]],
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
        }
    )


@bp.post("/transactions")
@jwt_required()
def create_transaction():
    payload = _parse(TransactionCreate, request.get_json(silent=True))
    tx = tx_service.create(get_jwt_identity(), payload)
    return jsonify({"transaction": tx.model_dump(mode="json")}), 201


@bp.get("/transactions/<tx_id>")
@jwt_required()
def get_transaction(tx_id: str):
    tx = tx_service.get(get_jwt_identity(), tx_id)
    return jsonify({"transaction": tx.model_dump(mode="json")})


@bp.patch("/transactions/<tx_id>")
@jwt_required()
def update_transaction(tx_id: str):
    payload = _parse(TransactionUpdate, request.get_json(silent=True))
    tx = tx_service.update(get_jwt_identity(), tx_id, payload)
    return jsonify({"transaction": tx.model_dump(mode="json")})


@bp.delete("/transactions/<tx_id>")
@jwt_required()
def delete_transaction(tx_id: str):
    tx_service.delete(get_jwt_identity(), tx_id)
    return jsonify({"ok": True})


@bp.post("/transactions/<tx_id>/categorize")
@jwt_required()
def recategorize_transaction(tx_id: str):
    """Re-run the rules cascade on this transaction's description and update."""
    tx = tx_service.categorize_existing(get_jwt_identity(), tx_id)
    return jsonify({"transaction": tx.model_dump(mode="json")})


@bp.post("/transactions/import/preview")
@jwt_required()
def import_preview():
    """Step 1 of the CSV wizard: parse + suggest mapping."""
    f = request.files.get("file")
    if not f:
        raise ValidationError("Missing file", details={"field": "file"})
    result = csv_import_service.preview(f.read())
    return jsonify(result.model_dump(mode="json"))


@bp.post("/transactions/import/commit")
@jwt_required()
def import_commit():
    """Step 3 of the CSV wizard: commit confirmed mapping. Multipart with
    `file` (the CSV bytes again) and `mapping` (JSON string of ImportMapping)."""
    f = request.files.get("file")
    raw_mapping = request.form.get("mapping")
    if not f or not raw_mapping:
        raise ValidationError(
            "Both `file` and `mapping` are required",
            details={"file": "required" if not f else "ok",
                     "mapping": "required" if not raw_mapping else "ok"},
        )
    try:
        import json
        mapping = ImportMapping(**json.loads(raw_mapping))
    except Exception as e:
        raise ValidationError(f"Invalid mapping JSON: {e}") from e
    result = csv_import_service.commit(get_jwt_identity(), f.read(), mapping)
    return jsonify(result.model_dump(mode="json")), 201
