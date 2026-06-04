from typing import Any

from bson import ObjectId
from pymongo import ReturnDocument

from app.extensions import mongo
from app.models.category import (
    DEFAULT_CATEGORIES,
    CategoryCreate,
    CategoryPublic,
    CategoryUpdate,
)
from app.models.user import utcnow
from app.utils.errors import NotFoundError, ValidationError


def _to_public(doc: dict[str, Any]) -> CategoryPublic:
    return CategoryPublic(
        id=str(doc["_id"]),
        name=doc["name"],
        color=doc["color"],
        monthly_budget=float(doc.get("monthly_budget", 0.0)),
        is_default=doc.get("is_default", False),
        created_at=doc["created_at"],
    )


def _oid(category_id: str) -> ObjectId:
    try:
        return ObjectId(category_id)
    except Exception as e:
        raise NotFoundError("Category not found") from e


def seed_defaults(user_id: str) -> None:
    """Insert any system category the user is missing.

    Per-name idempotent: looks at the user's existing category names, then
    inserts only the ones that aren't there yet. Called on every login so a
    newly-added default category (like "Goals") backfills onto pre-existing
    accounts without requiring a separate migration.
    """
    coll = mongo.db["categories"]
    user_oid = ObjectId(user_id)
    existing_names = {
        d["name"]
        for d in coll.find(
            {"user_id": user_oid, "deleted_at": None},
            {"name": 1},
        )
    }
    missing = [c for c in DEFAULT_CATEGORIES if c["name"] not in existing_names]
    if not missing:
        return
    now = utcnow()
    coll.insert_many([
        {
            "user_id": user_oid,
            "name": c["name"],
            "color": c["color"],
            "monthly_budget": 0.0,
            "is_default": True,
            "deleted_at": None,
            "created_at": now,
        }
        for c in missing
    ])


def list_for_user(user_id: str) -> list[CategoryPublic]:
    cursor = mongo.db["categories"].find(
        {"user_id": ObjectId(user_id), "deleted_at": None},
    ).sort("name", 1)
    return [_to_public(d) for d in cursor]


def create(user_id: str, payload: CategoryCreate) -> CategoryPublic:
    coll = mongo.db["categories"]
    name = payload.name.strip()
    existing = coll.find_one(
        {"user_id": ObjectId(user_id), "name": name, "deleted_at": None}
    )
    if existing:
        raise ValidationError(
            "A category with this name already exists",
            details={"field": "name"},
        )
    now = utcnow()
    doc = {
        "user_id": ObjectId(user_id),
        "name": name,
        "color": payload.color,
        "monthly_budget": float(payload.monthly_budget),
        "is_default": False,
        "deleted_at": None,
        "created_at": now,
    }
    res = coll.insert_one(doc)
    doc["_id"] = res.inserted_id
    return _to_public(doc)


def update(user_id: str, category_id: str, payload: CategoryUpdate) -> CategoryPublic:
    update_doc = payload.model_dump(exclude_none=True)
    if not update_doc:
        return get(user_id, category_id)
    if "name" in update_doc:
        update_doc["name"] = update_doc["name"].strip()
    doc = mongo.db["categories"].find_one_and_update(
        {"_id": _oid(category_id), "user_id": ObjectId(user_id), "deleted_at": None},
        {"$set": update_doc},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise NotFoundError("Category not found")
    return _to_public(doc)


def get(user_id: str, category_id: str) -> CategoryPublic:
    doc = mongo.db["categories"].find_one(
        {"_id": _oid(category_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not doc:
        raise NotFoundError("Category not found")
    return _to_public(doc)


def delete(user_id: str, category_id: str) -> None:
    """Soft delete. Refuse to delete system defaults."""
    cat = mongo.db["categories"].find_one(
        {"_id": _oid(category_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not cat:
        raise NotFoundError("Category not found")
    if cat.get("is_default"):
        raise ValidationError("System categories can't be deleted")
    mongo.db["categories"].update_one(
        {"_id": _oid(category_id)},
        {"$set": {"deleted_at": utcnow()}},
    )


def find_by_name(user_id: str, name: str) -> CategoryPublic | None:
    """Used by the categorization cascade to map a rule's output → ObjectId."""
    doc = mongo.db["categories"].find_one(
        {"user_id": ObjectId(user_id), "name": name, "deleted_at": None}
    )
    return _to_public(doc) if doc else None
