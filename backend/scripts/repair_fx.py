"""One-shot repair: re-run `amount_base` for every user using real ECB rates.

When to run this:

- After deploying the FX wiring (Week 4), pre-existing transactions still have
  the old 1:1 stub values in `amount_base`. The live `/me` PATCH hook only
  fires on a base-currency *change*, so users whose base wasn't touched still
  see wrong totals on the dashboard.
- If the Frankfurter feed was down for more than 7 days and a window of
  transactions ended up rejected and later inserted under the stale-cache
  fallback.

Usage (from `backend/`):
    python -m scripts.repair_fx
    python -m scripts.repair_fx --user <ObjectId>     # single-user mode

Idempotent — running it twice on already-correct data is a no-op
(amount_base is recomputed but lands on the same number).
"""
from __future__ import annotations

import argparse
import sys

from bson import ObjectId

from app import create_app
from app.extensions import mongo
from app.services import tx_service


def _repair_user(user_id: str) -> dict[str, int]:
    user = mongo.db["users"].find_one({"_id": ObjectId(user_id)}, {"base_currency": 1})
    if not user:
        return {"updated": 0, "skipped": 0, "failed": 0}
    stats = tx_service.recompute_amount_base_for_user(user_id)
    # Re-stamp the auto Net cash flow account's currency to match the user's
    # current base — its balance is derived from amount_base which we just
    # rewrote.
    mongo.db["accounts"].update_one(
        {"user_id": ObjectId(user_id), "source_ref": "transactions:net", "deleted_at": None},
        {"$set": {"currency": user["base_currency"]}},
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair amount_base via Frankfurter rates.")
    parser.add_argument("--user", help="Only repair this user_id (ObjectId hex)")
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        if args.user:
            stats = _repair_user(args.user)
            print(f"user {args.user}: updated={stats['updated']} failed={stats['failed']}")
            return 0

        user_ids = [str(u["_id"]) for u in mongo.db["users"].find({}, {"_id": 1})]
        print(f"Found {len(user_ids)} user(s).")
        total_updated = 0
        total_failed = 0
        for uid in user_ids:
            stats = _repair_user(uid)
            print(f"  user {uid}: updated={stats['updated']} failed={stats['failed']}")
            total_updated += stats["updated"]
            total_failed += stats["failed"]
        print(f"Done — {total_updated} transaction(s) repaired, {total_failed} failed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
