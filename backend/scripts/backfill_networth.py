"""One-shot net worth history backfill.

Reconstructs `net_worth_snapshots` for every user (or a single user with
`--user`) by walking back `--days` (default 180) from today and inserting
one snapshot per day. Idempotent on `(user_id, date)` — re-running
overwrites rather than dupes.

When to run:
  - First time after deploying Week 5 track 2 — without this, the dashboard
    sparkline and the NetWorthPage chart show only one day until tomorrow's
    scheduled job fires.
  - After bulk-importing historical transactions (CSV import of past months)
    — the backfill will pick up the time-accurate Net cash flow trajectory.
  - After fixing an FX outage that left some snapshots wrong — same idea
    as `repair_fx.py`.

Usage (from `backend/`):
    python -m scripts.backfill_networth                      # all users, 180d
    python -m scripts.backfill_networth --days 365           # all users, 1Y
    python -m scripts.backfill_networth --user <ObjectId>    # single user

Note: only the auto Net cash flow account is time-accurate at past dates.
Other accounts use their *current* balance for historical points (we don't
store per-day balance history). Fine for the chart's purpose; documented
as a Chapter 5 limitation.
"""
from __future__ import annotations

import argparse
import sys

from bson import ObjectId

from app import create_app
from app.extensions import mongo
from app.services import networth_service


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill net_worth_snapshots.")
    parser.add_argument("--user", help="Only backfill this user_id (ObjectId hex)")
    parser.add_argument("--days", type=int, default=180, help="Days back (default 180)")
    parser.add_argument("--step-days", type=int, default=1, help="Days between snapshots (default 1)")
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        if args.user:
            stats = networth_service.backfill(args.user, days=args.days, step_days=args.step_days)
            print(f"user {args.user}: inserted={stats['inserted']} from {stats['from']} to {stats['to']}")
            return 0

        user_ids = [str(u["_id"]) for u in mongo.db["users"].find({}, {"_id": 1})]
        print(f"Found {len(user_ids)} user(s); backfilling {args.days} days each.")
        total = 0
        for uid in user_ids:
            stats = networth_service.backfill(uid, days=args.days, step_days=args.step_days)
            print(f"  user {uid}: inserted={stats['inserted']}")
            total += stats["inserted"]
        print(f"Done — {total} snapshot(s) written.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
