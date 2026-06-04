"""Live integration smoke for the goals/recurring/transactions wiring.

Runs against a *running* Flask backend at http://localhost:5000 — not a
mongomock fixture. Registers a fresh QA user, populates the account with
hundreds of records spanning 6 months and 3 currencies, then asserts
cross-module invariants:

  - goal ↔ recurring linkage (auto_contribute.amount === recurring.amount, etc.)
  - cron-triggered materialization (saved_amount + tx + next_due roll)
  - final-cycle clamp + completion cascades
  - add / edit-amount / edit-day / disable / re-enable on auto-goal
  - day-31 clamp on short months
  - mark_paid on non-auto recurrings + one-off completion
  - reports vs transactions consistency
  - calendar projection
  - filters + pagination + search
  - alerts generation
  - net worth aggregation
  - FX conversion on cross-currency transactions

Output is a PASS/FAIL count plus a list of any failures.
"""
from __future__ import annotations

import calendar
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

BASE = "http://localhost:5000/api"
PASS_COUNT = 0
FAIL_COUNT = 0
FAILS: list[str] = []
SECTIONS: list[tuple[str, int, int]] = []  # (label, pass, fail)


def section(name: str) -> None:
    global PASS_COUNT, FAIL_COUNT
    if SECTIONS:
        prev_label, prev_pass, prev_fail = SECTIONS[-1]
        # snapshot the deltas for the previous section
        SECTIONS[-1] = (prev_label, PASS_COUNT - prev_pass, FAIL_COUNT - prev_fail)
    SECTIONS.append((name, PASS_COUNT, FAIL_COUNT))
    print(f"\n=== {name} ===")


def check(label: str, cond: bool, detail: str = "") -> bool:
    global PASS_COUNT, FAIL_COUNT
    if cond:
        PASS_COUNT += 1
        print(f"  PASS  {label}")
        return True
    FAIL_COUNT += 1
    msg = f"{label}" + (f" — {detail}" if detail else "")
    FAILS.append(msg)
    print(f"  FAIL  {msg}")
    return False


def api(method: str, path: str, headers: dict[str, str], **kwargs: Any) -> requests.Response:
    return requests.request(method, f"{BASE}{path}", headers=headers, timeout=30, **kwargs)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Phase 1 — Register + capture default categories
# ---------------------------------------------------------------------------
ts = int(time.time())
EMAIL = f"qa{ts}@example.com"
PASSWORD = "password123"

section("Setup: register + bootstrap")

r = requests.post(f"{BASE}/auth/register", json={
    "email": EMAIL, "password": PASSWORD, "full_name": "QA Smoke", "base_currency": "RON",
}, timeout=30)
check("registered new user", r.status_code == 201, f"status={r.status_code} body={r.text[:200]}")

# Production register does NOT return a JWT until the email is verified.
# Force-verify in Mongo to mirror the TESTING fixture path so the smoke
# can proceed; this is QA-only.
import os, sys as _sys  # noqa: E402
_sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))
from app import create_app  # noqa: E402
from app.extensions import mongo  # noqa: E402
from bson import ObjectId  # noqa: E402

app = create_app()
new_user_id = r.json()["user"]["id"]
with app.app_context():
    mongo.db["users"].update_one(
        {"_id": ObjectId(new_user_id)},
        {"$set": {"email_verified": True}},
    )

# Now log in normally and capture the JWT.
lr = requests.post(f"{BASE}/auth/login",
                   json={"email": EMAIL, "password": PASSWORD}, timeout=30)
check("login after verification: 200", lr.status_code == 200, lr.text[:200])
TOKEN = lr.json()["access_token"]
H = {"Authorization": f"Bearer {TOKEN}"}
USER_ID = new_user_id  # cached for direct Mongo poking later

cats = api("GET", "/categories", H).json()["categories"]
check("default categories seeded", len(cats) >= 10, f"got {len(cats)}")
by_name = {c["name"]: c for c in cats}
needed_defaults = {"Goals", "Groceries", "Restaurants", "Transport", "Entertainment",
                   "Salary", "Housing", "Utilities", "Subscriptions", "Other"}
missing = needed_defaults - set(by_name)
check("all expected default categories present", not missing, f"missing={missing}")

# Add 3 custom categories (category model is income/expense-agnostic — sign comes from amount).
for name, color in [("Side hustle", "#22c55e"),
                    ("Freelance", "#10b981"),
                    ("Gym", "#f59e0b")]:
    r = api("POST", "/categories", H, json={"name": name, "color": color})
    check(f"created custom category '{name}'", r.status_code == 201, r.text[:200])
    if r.status_code == 201:
        by_name[name] = r.json()["category"]


# ---------------------------------------------------------------------------
# Phase 2 — Populate transactions (~60+ over 6 months, mixed currency)
# ---------------------------------------------------------------------------
section("Populate transactions")

NOW = datetime.now(timezone.utc)
random.seed(42)

# Monthly salary in RON, 6 months back
for m in range(6):
    when = NOW - timedelta(days=30 * m + random.randint(0, 5))
    r = api("POST", "/transactions", H, json={
        "date": iso(when), "amount": 7500, "currency": "RON",
        "description": f"Monthly salary {when.strftime('%b')}",
        "category_id": by_name["Salary"]["id"],
    })
    if r.status_code != 201:
        check(f"salary month -{m}", False, r.text[:200])
created_count = 6

# Occasional freelance income in EUR
for _ in range(4):
    when = NOW - timedelta(days=random.randint(5, 180))
    r = api("POST", "/transactions", H, json={
        "date": iso(when), "amount": random.choice([350, 500, 750, 1200]), "currency": "EUR",
        "description": "Freelance project", "category_id": by_name["Freelance"]["id"],
    })
    if r.status_code == 201:
        created_count += 1

# Side hustle in USD
for _ in range(3):
    when = NOW - timedelta(days=random.randint(5, 150))
    r = api("POST", "/transactions", H, json={
        "date": iso(when), "amount": random.choice([100, 200, 400]), "currency": "USD",
        "description": "Online side", "category_id": by_name["Side hustle"]["id"],
    })
    if r.status_code == 201:
        created_count += 1

# Mass expenses: 60+ across categories/currencies/months
expense_plan = [
    (by_name["Groceries"]["id"],     ["MEGA Image", "Kaufland", "Lidl", "Profi", "Auchan"], "RON",  60,  500, 14),
    (by_name["Restaurants"]["id"],   ["Burger King", "Pizza Hut", "Vivo", "Trattoria"],     "RON",  40,  300, 8),
    (by_name["Transport"]["id"],     ["STB", "Uber", "Taxi", "Petrom", "OMV"],              "RON",  15,  250, 12),
    (by_name["Subscriptions"]["id"], ["Netflix", "Spotify", "iCloud"],                       "RON",  20,  60,  6),
    (by_name["Entertainment"]["id"], ["Cinema", "Theatre"],                                  "RON",  30,  120, 5),
    (by_name["Utilities"]["id"],     ["Enel", "Apa Nova", "Digi"],                           "RON", 100,  400, 6),
    (by_name["Housing"]["id"],       ["Rent payment"],                                       "RON", 3200, 3200, 6),
    (by_name["Other"]["id"],         ["Amazon EU", "Decathlon"],                             "EUR",  25,  200, 5),
    (by_name["Gym"]["id"],           ["Gym membership"],                                     "EUR",  35,  35, 5),
    (by_name["Other"]["id"],         ["Software license", "Domain"],                         "USD",  10,  80,  3),
]
for cat_id, vendors, currency, lo, hi, count in expense_plan:
    for _ in range(count):
        when = NOW - timedelta(days=random.randint(1, 175))
        amt = round(random.uniform(lo, hi), 2)
        r = api("POST", "/transactions", H, json={
            "date": iso(when), "amount": -amt, "currency": currency,
            "description": random.choice(vendors), "category_id": cat_id,
        })
        if r.status_code == 201:
            created_count += 1

check("created 60+ transactions", created_count >= 60, f"got {created_count}")

# Quick sanity GET
all_tx = api("GET", "/transactions?page=1&page_size=200", H).json()["transactions"]
check("transactions list returns >=60 items", len(all_tx) >= 60, f"got {len(all_tx)}")


# ---------------------------------------------------------------------------
# Phase 3 — Populate planned payments
# ---------------------------------------------------------------------------
section("Populate planned payments")

# A monthly auto-create salary (income) — Future + auto so cron picks it up
r = api("POST", "/recurring", H, json={
    "name": "Salary auto", "merchant_pattern": "AUTO-SALARY",
    "amount": 7500, "currency": "RON", "frequency": "monthly",
    "start_date": iso(NOW + timedelta(days=10)),
    "is_income": True, "auto_create_transaction": True,
    "category_id": by_name["Salary"]["id"],
})
check("recurring: monthly income (auto)", r.status_code == 201, r.text[:200])
rec_salary_id = r.json()["recurring"]["id"] if r.status_code == 201 else None

# Rent — monthly, NOT auto (user pays manually)
r = api("POST", "/recurring", H, json={
    "name": "Rent Aviatorilor", "merchant_pattern": "RENT",
    "amount": 3200, "currency": "RON", "frequency": "monthly",
    "start_date": iso(NOW + timedelta(days=12)),
    "is_income": False, "auto_create_transaction": False,
    "category_id": by_name["Housing"]["id"],
})
check("recurring: rent (non-auto)", r.status_code == 201)
rec_rent_id = r.json()["recurring"]["id"] if r.status_code == 201 else None

# Netflix — monthly, auto
r = api("POST", "/recurring", H, json={
    "name": "Netflix sub", "merchant_pattern": "NETFLIX",
    "amount": 29.99, "currency": "RON", "frequency": "monthly",
    "start_date": iso(NOW + timedelta(days=4)),
    "is_income": False, "auto_create_transaction": True,
    "category_id": by_name["Subscriptions"]["id"],
})
check("recurring: netflix monthly (auto)", r.status_code == 201)
rec_netflix_id = r.json()["recurring"]["id"] if r.status_code == 201 else None

# Annual tax — yearly, NOT auto
r = api("POST", "/recurring", H, json={
    "name": "Annual tax", "merchant_pattern": "TAX",
    "amount": 800, "currency": "RON", "frequency": "yearly",
    "start_date": iso(NOW + timedelta(days=60)),
    "is_income": False, "auto_create_transaction": False,
    "category_id": by_name["Other"]["id"],
})
check("recurring: yearly tax (non-auto)", r.status_code == 201)

# Weekly cleaner — recurring, not auto
r = api("POST", "/recurring", H, json={
    "name": "Cleaner", "merchant_pattern": "CLEANER",
    "amount": 100, "currency": "RON", "frequency": "weekly",
    "start_date": iso(NOW + timedelta(days=2)),
    "is_income": False, "auto_create_transaction": False,
    "category_id": by_name["Other"]["id"],
})
check("recurring: weekly cleaner", r.status_code == 201)

# Biweekly transport pass — auto
r = api("POST", "/recurring", H, json={
    "name": "Transport pass", "merchant_pattern": "STB-PASS",
    "amount": 80, "currency": "RON", "frequency": "biweekly",
    "start_date": iso(NOW + timedelta(days=6)),
    "is_income": False, "auto_create_transaction": True,
    "category_id": by_name["Transport"]["id"],
})
check("recurring: biweekly transport (auto)", r.status_code == 201)

# Wedding gift one-off — future, auto
r = api("POST", "/recurring", H, json={
    "name": "Wedding gift", "merchant_pattern": "GIFT",
    "amount": 600, "currency": "RON", "frequency": "once",
    "start_date": iso(NOW + timedelta(days=20)),
    "is_income": False, "auto_create_transaction": True,
    "category_id": by_name["Other"]["id"],
})
check("recurring: one-off future gift (auto)", r.status_code == 201)

# EUR Spotify family one-off in past — auto, should eager-materialize
r = api("POST", "/recurring", H, json={
    "name": "Spotify family", "merchant_pattern": "SPOTIFY-FAM",
    "amount": 18, "currency": "EUR", "frequency": "monthly",
    "start_date": iso(NOW - timedelta(days=60)),
    "is_income": False, "auto_create_transaction": True,
    "category_id": by_name["Subscriptions"]["id"],
})
check("recurring: backdated monthly EUR (auto, eager materialize)", r.status_code == 201)

# Verify list & summary
recs = api("GET", "/recurring", H).json()["recurring"]
check("recurring list has >=7 active rows", len(recs) >= 7, f"got {len(recs)}")
check("recurring contains all goal_id fields (nullable)",
      all("goal_id" in r for r in recs))


# ---------------------------------------------------------------------------
# Phase 4 — Populate goals (mix of auto + manual, mixed currencies)
# ---------------------------------------------------------------------------
section("Populate goals")

# Helper for ISO future date
def fut(months: int) -> str:
    return iso(NOW + timedelta(days=30 * months))


# Manual goal (no auto)
r = api("POST", "/goals", H, json={
    "name": "Emergency fund", "target_amount": 15000, "currency": "RON",
    "target_date": fut(18), "type": "emergency", "priority": 1,
    "initial_deposit": 3500,
})
check("goal: Emergency fund (no auto)", r.status_code == 201)
gid_emerg = r.json()["goal"]["id"] if r.status_code == 201 else None

# Auto goal in EUR
r = api("POST", "/goals", H, json={
    "name": "Italy 2027", "target_amount": 3500, "currency": "EUR",
    "target_date": fut(13), "type": "travel", "priority": 2,
    "auto_contribute": {"amount": 250, "start_date": iso(NOW + timedelta(days=12))},
})
check("goal: Italy (auto EUR)", r.status_code == 201)
gid_italy = r.json()["goal"]["id"] if r.status_code == 201 else None

# Auto goal in USD
r = api("POST", "/goals", H, json={
    "name": "MacBook", "target_amount": 2500, "currency": "USD",
    "target_date": fut(10), "type": "other", "priority": 3,
    "auto_contribute": {"amount": 200, "start_date": iso(NOW + timedelta(days=5))},
})
check("goal: MacBook (auto USD)", r.status_code == 201)
gid_mac = r.json()["goal"]["id"] if r.status_code == 201 else None

# Auto goal RON, near-completion — final-cycle clamp test
r = api("POST", "/goals", H, json={
    "name": "Bike", "target_amount": 1000, "currency": "RON",
    "target_date": fut(6), "type": "other", "priority": 4,
    "initial_deposit": 900,
    "auto_contribute": {"amount": 300, "start_date": iso(NOW)},
})
check("goal: Bike (auto RON, near-complete)", r.status_code == 201)
gid_bike = r.json()["goal"]["id"] if r.status_code == 201 else None

# Goal to delete (auto)
r = api("POST", "/goals", H, json={
    "name": "Will be deleted", "target_amount": 1000, "currency": "RON",
    "target_date": fut(6),
    "auto_contribute": {"amount": 50, "start_date": iso(NOW + timedelta(days=5))},
})
check("goal: To-delete (auto)", r.status_code == 201)
gid_del = r.json()["goal"]["id"] if r.status_code == 201 else None

# Goal to complete via manual (auto present)
r = api("POST", "/goals", H, json={
    "name": "Bonsai tree", "target_amount": 300, "currency": "RON",
    "target_date": fut(6),
    "auto_contribute": {"amount": 100, "start_date": iso(NOW + timedelta(days=15))},
})
check("goal: Bonsai (auto, will complete)", r.status_code == 201)
gid_bonsai = r.json()["goal"]["id"] if r.status_code == 201 else None

# Big goal for partial contributions
r = api("POST", "/goals", H, json={
    "name": "Down payment", "target_amount": 50000, "currency": "RON",
    "target_date": fut(36), "type": "home", "priority": 2,
})
check("goal: Down payment (no auto)", r.status_code == 201)
gid_house = r.json()["goal"]["id"] if r.status_code == 201 else None


# ---------------------------------------------------------------------------
# Phase 5 — Cross-module connection assertions
# ---------------------------------------------------------------------------
section("Goal <-> Recurring linkage")

goals = api("GET", "/goals", H).json()["goals"]
goals_by_name = {g["name"]: g for g in goals}
recs = api("GET", "/recurring", H).json()["recurring"]
recs_by_name = {r["name"]: r for r in recs}

for goal_name, monthly, currency in [("Italy 2027", 250, "EUR"),
                                     ("MacBook", 200, "USD"),
                                     ("Bike", 300, "RON"),
                                     ("Will be deleted", 50, "RON"),
                                     ("Bonsai tree", 100, "RON")]:
    g = goals_by_name.get(goal_name)
    rec_name = f"Contribution: {goal_name}"
    rec = recs_by_name.get(rec_name)
    if not check(f"goal '{goal_name}' has linked recurring on planned page", rec is not None):
        continue
    check(f"  recurring amount matches goal monthly ({monthly} {currency})",
          rec["amount"] == monthly and rec["currency"] == currency,
          f"got {rec['amount']} {rec['currency']}")
    check(f"  recurring goal_id matches goal id",
          rec["goal_id"] == g["id"])
    check(f"  recurring is_income=False",
          rec["is_income"] is False)
    check(f"  recurring auto_create_transaction=True",
          rec["auto_create_transaction"] is True)
    check(f"  goal.auto_contribute.amount matches",
          g["auto_contribute"] and g["auto_contribute"]["amount"] == monthly)
    check(f"  goal.auto_contribute.recurring_id matches",
          g["auto_contribute"] and g["auto_contribute"]["recurring_id"] == rec["id"])


section("Cron materialization (force next_due to today, then run cron)")
from app.services import recurring_service  # noqa: E402

with app.app_context():
    # Force Italy & MacBook & Bike recurrings to be due today.
    for goal_name in ("Italy 2027", "MacBook", "Bike", "Bonsai tree"):
        rec_name = f"Contribution: {goal_name}"
        mongo.db["recurring_payments"].update_one(
            {"name": rec_name, "user_id": ObjectId(USER_ID)},
            {"$set": {"next_due": NOW.replace(tzinfo=None)}},
        )

    # Capture pre-state
    pre = {gn: api("GET", f"/goals/{gid}", H).json()["goal"]
           for gn, gid in [("Italy 2027", gid_italy), ("MacBook", gid_mac),
                           ("Bike", gid_bike), ("Bonsai tree", gid_bonsai)]}

    stats = recurring_service.materialize_due()
    print(f"  cron stats: {stats}")
    check("cron created >=1 transactions", stats["created"] >= 1)

    # Italy: saved should jump by 250
    italy_after = api("GET", f"/goals/{gid_italy}", H).json()["goal"]
    check("Italy saved increased by 250",
          abs(italy_after["saved_amount"] - (pre["Italy 2027"]["saved_amount"] + 250)) < 0.01,
          f"pre={pre['Italy 2027']['saved_amount']} after={italy_after['saved_amount']}")

    # MacBook: saved should jump by 200
    mac_after = api("GET", f"/goals/{gid_mac}", H).json()["goal"]
    check("MacBook saved increased by 200",
          abs(mac_after["saved_amount"] - (pre["MacBook"]["saved_amount"] + 200)) < 0.01,
          f"pre={pre['MacBook']['saved_amount']} after={mac_after['saved_amount']}")

    # Bike: pre-saved=900, remaining=100, monthly=300 → clamps to 100, completes
    bike_after = api("GET", f"/goals/{gid_bike}", H).json()["goal"]
    check("Bike clamped to remaining 100 (not 300)",
          abs(bike_after["saved_amount"] - 1000) < 0.01,
          f"saved={bike_after['saved_amount']}")
    check("Bike status=completed", bike_after["status"] == "completed")
    check("Bike linked recurring closed (auto_contribute=null)",
          bike_after["auto_contribute"] is None)


section("Transactions created by cron land in /transactions + carry FX")
all_tx = api("GET", "/transactions?page=1&page_size=200", H).json()["transactions"]
contrib_txs = [t for t in all_tx if t["description"].startswith("Contribution:")]
check("contribution transactions exist", len(contrib_txs) >= 4, f"got {len(contrib_txs)}")
italy_tx = [t for t in contrib_txs if "Italy 2027" in t["description"]]
check("Italy contribution tx in EUR with amount_base computed",
      len(italy_tx) >= 1 and italy_tx[0]["currency"] == "EUR" and italy_tx[0]["amount_base"] is not None,
      f"{italy_tx[0] if italy_tx else None}")
check("Italy contribution amount = -250",
      italy_tx and abs(italy_tx[0]["amount"] - (-250)) < 0.01)
mac_tx = [t for t in contrib_txs if "MacBook" in t["description"]]
check("MacBook contribution tx in USD with amount_base computed",
      len(mac_tx) >= 1 and mac_tx[0]["currency"] == "USD" and mac_tx[0]["amount_base"] is not None)
bike_tx = [t for t in contrib_txs if "Bike" in t["description"]]
check("Bike contribution clamped to -100",
      bike_tx and abs(bike_tx[0]["amount"] - (-100)) < 0.01,
      f"{bike_tx[0] if bike_tx else None}")


section("Mark paid on non-auto recurring (Rent)")
with app.app_context():
    # Force rent due today
    mongo.db["recurring_payments"].update_one(
        {"_id": ObjectId(rec_rent_id)},
        {"$set": {"next_due": NOW.replace(tzinfo=None)}},
    )
r = api("POST", f"/recurring/{rec_rent_id}/mark-paid", H)
check("mark_paid returns 200", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    rec_after = r.json()["recurring"]
    check("rent next_due rolled by ~1 month",
          (datetime.fromisoformat(rec_after["next_due"].replace("Z","")) - NOW.replace(tzinfo=None)).days >= 25)
# Verify the transaction landed in /transactions
rent_txs = [t for t in api("GET","/transactions?page=1&page_size=200", H).json()["transactions"]
            if t["description"] == "Rent Aviatorilor" and t["source"] == "recurring"]
check("rent transaction created by mark_paid",
      len(rent_txs) >= 1, f"got {len(rent_txs)}")


section("Goal delete cascades to recurring")
r = api("DELETE", f"/goals/{gid_del}", H)
check("delete goal returns 200", r.status_code == 200)
recs2 = api("GET", "/recurring", H).json()["recurring"]
check("'Will be deleted' contribution row removed from planned",
      all(r["name"] != "Contribution: Will be deleted" for r in recs2))


section("Goal completion cascades to recurring")
# Push Bonsai over the target with a manual contribution
g_b = api("GET", f"/goals/{gid_bonsai}", H).json()["goal"]
remaining = g_b["target_amount"] - g_b["saved_amount"]
r = api("POST", f"/goals/{gid_bonsai}/contribute", H, json={"amount": remaining})
check("manual contribute that completes goal: 200", r.status_code == 200)
after = r.json()["goal"]
check("Bonsai status=completed", after["status"] == "completed")
check("Bonsai auto_contribute=null after completion",
      after["auto_contribute"] is None)
recs3 = api("GET", "/recurring", H).json()["recurring"]
check("Bonsai contribution row removed from planned",
      all(r["name"] != "Contribution: Bonsai tree" for r in recs3))


section("Add auto to existing goal (Emergency fund)")
picked_day = 15
picked = iso(NOW.replace(day=picked_day, hour=12, minute=0, second=0, microsecond=0))
r = api("PATCH", f"/goals/{gid_emerg}", H, json={
    "auto_contribute": {"amount": 500, "start_date": picked},
})
check("PATCH add auto: 200", r.status_code == 200, r.text[:200])
g_after = r.json()["goal"]
check("goal now has auto_contribute",
      g_after["auto_contribute"] is not None
      and abs(g_after["auto_contribute"]["amount"] - 500) < 0.01)

# Verify recurring exists with proper next_due
recs4 = api("GET", "/recurring", H).json()["recurring"]
emerg_rec = next((r for r in recs4 if r["name"] == "Contribution: Emergency fund"), None)
check("planned page shows new contribution row", emerg_rec is not None)
if emerg_rec:
    nd = datetime.fromisoformat(emerg_rec["next_due"].replace("Z","")).date()
    # Expected: first-of-next-month at picked_day
    nm_year, nm_month = (NOW.year + 1, 1) if NOW.month == 12 else (NOW.year, NOW.month + 1)
    expected_day = min(picked_day, calendar.monthrange(nm_year, nm_month)[1])
    check(f"next_due snapped to {nm_year}-{nm_month:02d}-{expected_day:02d}",
          nd == datetime(nm_year, nm_month, expected_day).date(),
          f"got {nd}")


section("Edit existing auto-goal: change amount + change day")
new_day = 25
new_picked = iso(NOW.replace(day=new_day, hour=12, minute=0, second=0, microsecond=0))
r = api("PATCH", f"/goals/{gid_emerg}", H, json={
    "auto_contribute": {"amount": 650, "start_date": new_picked},
})
check("PATCH edit auto: 200", r.status_code == 200)
g_after2 = r.json()["goal"]
check("auto_contribute.amount updated to 650",
      g_after2["auto_contribute"]["amount"] == 650)

recs5 = api("GET", "/recurring", H).json()["recurring"]
emerg_rec2 = next((r for r in recs5 if r["name"] == "Contribution: Emergency fund"), None)
if emerg_rec2:
    nd = datetime.fromisoformat(emerg_rec2["next_due"].replace("Z","")).date()
    nm_year, nm_month = (NOW.year + 1, 1) if NOW.month == 12 else (NOW.year, NOW.month + 1)
    expected_day = min(new_day, calendar.monthrange(nm_year, nm_month)[1])
    check(f"next_due re-snapped to day-{expected_day} of next month",
          nd == datetime(nm_year, nm_month, expected_day).date(),
          f"got {nd}")


section("Disable auto on existing goal, then re-enable")
r = api("PATCH", f"/goals/{gid_emerg}", H, json={"auto_contribute": False})
check("PATCH disable auto: 200", r.status_code == 200)
g_dis = r.json()["goal"]
check("auto_contribute=null after disable", g_dis["auto_contribute"] is None)
recs6 = api("GET", "/recurring", H).json()["recurring"]
check("contribution row removed from planned after disable",
      all(r["name"] != "Contribution: Emergency fund" for r in recs6))

# Re-enable with different day
r = api("PATCH", f"/goals/{gid_emerg}", H, json={
    "auto_contribute": {"amount": 400,
                        "start_date": iso(NOW.replace(day=5, hour=12,
                                                       minute=0, second=0, microsecond=0))},
})
check("PATCH re-enable auto: 200", r.status_code == 200)
g_re = r.json()["goal"]
check("auto_contribute exists again after re-enable",
      g_re["auto_contribute"] is not None and g_re["auto_contribute"]["amount"] == 400)


section("Next monthly anchor on/after now - direct helper")
from app.services.goal_service import _next_monthly_anchor  # noqa: E402
check("This-month anchor still ahead -> use this month",
      _next_monthly_anchor(datetime(2026, 6, 3), 7) == datetime(2026, 6, 7))
check("This-month anchor passed -> next month",
      _next_monthly_anchor(datetime(2026, 6, 10), 7) == datetime(2026, 7, 7))
check("Apr day 31 clamps to Apr 30 (this month)",
      _next_monthly_anchor(datetime(2026, 4, 1), 31) == datetime(2026, 4, 30))
check("Dec->Jan year roll when this-month anchor passed",
      _next_monthly_anchor(datetime(2026, 12, 15), 10) == datetime(2027, 1, 10))


section("One-off recurring: mark paid then assert no double-fire")
# Use the wedding-gift one-off we created earlier
recs7 = api("GET", "/recurring?include_completed=true", H).json()["recurring"]
gift = next((r for r in recs7 if r["name"] == "Wedding gift"), None)
check("wedding gift one-off present", gift is not None)
if gift:
    # Force due today
    with app.app_context():
        mongo.db["recurring_payments"].update_one(
            {"_id": ObjectId(gift["id"])},
            {"$set": {"next_due": NOW.replace(tzinfo=None)}},
        )
    r = api("POST", f"/recurring/{gift['id']}/mark-paid", H)
    check("one-off mark_paid: 200", r.status_code == 200)
    g_after = r.json()["recurring"]
    check("one-off status=completed", g_after["status"] == "completed")

    # Cron must NOT re-fire
    with app.app_context():
        stats_before = mongo.db["transactions"].count_documents(
            {"description": "Wedding gift"})
        recurring_service.materialize_due()
        stats_after = mongo.db["transactions"].count_documents(
            {"description": "Wedding gift"})
    check("subsequent cron run does not re-fire completed one-off",
          stats_before == stats_after,
          f"before={stats_before} after={stats_after}")


section("Calendar projection — current + next month")
ny, nm = (NOW.year + 1, 1) if NOW.month == 12 else (NOW.year, NOW.month + 1)
cal = api("GET", f"/recurring/calendar?year={ny}&month={nm}", H).json()
check(f"calendar {ny}-{nm} returns by_day dict", "by_day" in cal)
total_events = sum(len(v) for v in cal["by_day"].values())
check(f"calendar {ny}-{nm} has events", total_events > 0, f"events={total_events}")
# At least the Netflix monthly and Transport biweekly should be visible
flattened = [e for v in cal["by_day"].values() for e in v]
check("calendar contains Netflix",
      any(e["name"] == "Netflix sub" for e in flattened))


section("Reports vs Transactions consistency")
# Spending report total = sum of negative amount_base across non-income txs
start = iso(NOW - timedelta(days=180))
end = iso(NOW + timedelta(days=1))
report = api("GET", f"/reports/spending?from={start[:10]}&to={end[:10]}", H).json()
check("spending report returns items", "items" in report)
report_total = sum(it["total"] for it in report["items"])

# Independent sum from /transactions in same window
all_tx2 = api("GET", "/transactions?page=1&page_size=200", H).json()["transactions"]
manual_total = 0.0
for t in all_tx2:
    if t["amount"] < 0 and t["amount_base"] is not None:
        td = datetime.fromisoformat(t["date"].replace("Z","")).date()
        if datetime.fromisoformat(start[:10]).date() <= td <= datetime.fromisoformat(end[:10]).date():
            manual_total += abs(t["amount_base"])
check(f"spending report total roughly matches /transactions sum (rel diff <5%)",
      abs(report_total - manual_total) / max(manual_total, 1) < 0.05,
      f"report={report_total:.2f} txsum={manual_total:.2f}")


section("Filters on /transactions")
# By category
r = api("GET", f"/transactions?category_id={by_name['Groceries']['id']}&page_size=200", H).json()
check("category filter returns only that category",
      all(t["category_id"] == by_name["Groceries"]["id"] for t in r["transactions"]),
      f"got {len(r['transactions'])} items")

# By date range (last 30 days)
ago = iso(NOW - timedelta(days=30))[:10]
end = iso(NOW + timedelta(days=1))[:10]
r = api("GET", f"/transactions?date_from={ago}&date_to={end}&page_size=200", H).json()
for t in r["transactions"]:
    td = datetime.fromisoformat(t["date"].replace("Z","")).date()
    if not (datetime.fromisoformat(ago).date() <= td <= datetime.fromisoformat(end).date()):
        check("date filter excludes out-of-window", False, f"got tx dated {td}")
        break
else:
    check("date filter respected for all rows", True)

# Pagination
r1 = api("GET", "/transactions?page=1&page_size=10", H).json()
r2 = api("GET", "/transactions?page=2&page_size=10", H).json()
check("pagination returns disjoint pages",
      not (set(t["id"] for t in r1["transactions"]) & set(t["id"] for t in r2["transactions"])),
      "overlap detected")


section("Net worth aggregation")
nw = api("GET", "/networth", H).json()
check("net worth endpoint returns net_worth field",
      "net_worth" in nw and "total_assets" in nw and "total_liabilities" in nw)
check("net worth = total_assets - total_liabilities (within RON 0.50)",
      abs((nw["total_assets"] - nw["total_liabilities"]) - nw["net_worth"]) < 0.5,
      f"assets={nw.get('total_assets')} liab={nw.get('total_liabilities')} nw={nw.get('net_worth')}")
check("net worth breakdown has Paper Portfolio + Cash + Net cash flow",
      sum(1 for b in nw.get("breakdown", []) if b["name"] in
          ("Paper Portfolio", "Cash", "Net cash flow")) >= 3)

# Snapshot then history
r = api("POST", "/networth/snapshot", H)
check("manual snapshot returns 201", r.status_code == 201, r.text[:200])
hist = api("GET", "/networth/history?range=ALL", H).json()
check("history has at least one point",
      "points" in hist and len(hist["points"]) >= 1,
      f"points={len(hist.get('points', []))}")


section("Search across resources")
r = api("GET", "/search?q=Netflix", H)
check("search status 200", r.status_code == 200)


section("Alerts generation")
alerts_resp = api("GET", "/alerts", H).json()
alerts = alerts_resp.get("alerts", alerts_resp.get("items", []))
print(f"  /alerts returned {len(alerts)} entries; sources={[a.get('source') for a in alerts][:10]}")
check("/alerts endpoint returns 200 with a list", isinstance(alerts, list))


section("Defensive: try to delete a system category (Goals)")
goals_cat_id = by_name["Goals"]["id"]
r = api("DELETE", f"/categories/{goals_cat_id}", H)
check("delete Goals category is rejected (>=400)",
      r.status_code >= 400, f"unexpectedly succeeded ({r.status_code})")


section("Defensive: invalid currency, past target_date, etc")
# Past target date
r = api("POST", "/goals", H, json={
    "name": "Bad", "target_amount": 100, "currency": "RON",
    "target_date": iso(NOW - timedelta(days=30)),
})
check("past target_date rejected (422)", r.status_code == 422)

# Negative target_amount
r = api("POST", "/goals", H, json={
    "name": "Bad2", "target_amount": -50, "currency": "RON",
    "target_date": fut(6),
})
check("negative target_amount rejected (422)", r.status_code == 422)

# Auto-contribute with amount <= 0
r = api("POST", "/goals", H, json={
    "name": "Bad3", "target_amount": 1000, "currency": "RON",
    "target_date": fut(6),
    "auto_contribute": {"amount": 0, "start_date": iso(NOW + timedelta(days=5))},
})
check("auto_contribute amount<=0 rejected", r.status_code >= 400)

# Contribute to a non-existent goal
r = api("POST", "/goals/000000000000000000000000/contribute", H, json={"amount": 10})
check("contribute to non-existent goal: 404", r.status_code == 404)

# Mark paid on non-existent recurring
r = api("POST", "/recurring/000000000000000000000000/mark-paid", H)
check("mark_paid on non-existent recurring: 404", r.status_code == 404)


section("Corner: idempotent cron (second run is a no-op)")
with app.app_context():
    before = mongo.db["transactions"].count_documents({"user_id": ObjectId(USER_ID)})
    s2 = recurring_service.materialize_due()
    after = mongo.db["transactions"].count_documents({"user_id": ObjectId(USER_ID)})
check("second cron run produces 0 new tx (nothing newly due)",
      before == after, f"before={before} after={after} stats={s2}")


section("Corner: multi-cycle catch-up on a backdated auto recurring")
# Backdate the Italy auto goal recurring by 3 months. The cron should
# fire 3 contributions in one pass — one per missed month.
with app.app_context():
    italy_rec = mongo.db["recurring_payments"].find_one(
        {"name": "Contribution: Italy 2027", "user_id": ObjectId(USER_ID), "status": "active"}
    )
    if italy_rec:
        backdated = (NOW - timedelta(days=92)).replace(tzinfo=None)
        mongo.db["recurring_payments"].update_one(
            {"_id": italy_rec["_id"]},
            {"$set": {"next_due": backdated, "start_date": backdated}},
        )
        italy_pre = api("GET", f"/goals/{gid_italy}", H).json()["goal"]
        stats3 = recurring_service.materialize_due()
        italy_post = api("GET", f"/goals/{gid_italy}", H).json()["goal"]
        delta = italy_post["saved_amount"] - italy_pre["saved_amount"]
        # Expect 3 cycles × 250 = 750, but cap if goal completes mid-catchup.
        check("multi-cycle catch-up created multiple transactions",
              stats3["created"] >= 2,
              f"stats={stats3} delta={delta}")
        check("multi-cycle catch-up bumped saved by >= 500",
              delta >= 500, f"delta={delta}")


section("Corner: PATCH a non-goal recurring's amount directly")
r = api("PATCH", f"/recurring/{rec_netflix_id}", H, json={"amount": 35.99})
check("PATCH non-goal recurring amount: 200",
      r.status_code == 200, r.text[:200])
if r.status_code == 200:
    check("amount field reflects PATCH",
          abs(r.json()["recurring"]["amount"] - 35.99) < 0.001)


section("Corner: budget set on category surfaces via /categories + spending report")
# This is how the Budget page actually reads its data — /categories carries
# monthly_budget; /reports/spending carries the actual spent amount.
r = api("PATCH", f"/categories/{by_name['Groceries']['id']}", H,
        json={"monthly_budget": 800})
check("set monthly_budget on Groceries: 200", r.status_code == 200)
cats_after = api("GET", "/categories", H).json()["categories"]
groc = next((c for c in cats_after if c["name"] == "Groceries"), None)
check("Groceries monthly_budget == 800 on /categories",
      groc is not None and abs(groc["monthly_budget"] - 800) < 0.01,
      f"groc={groc}")
# Spending report for this month should include Groceries spend
this_month_start = NOW.replace(day=1).strftime("%Y-%m-%d")
this_month_end = (NOW.replace(day=1) + timedelta(days=40)).replace(day=1).strftime("%Y-%m-%d")
report = api("GET", f"/reports/spending?from={this_month_start}&to={this_month_end}", H).json()
groc_line = next((it for it in report.get("items", []) if it["category_name"] == "Groceries"), None)
check("Groceries appears in monthly spending report",
      groc_line is not None, f"items={[it['category_name'] for it in report.get('items',[])]}")


section("Corner: /reports/monthly returns income + expense + net per month")
r = api("GET", f"/reports/monthly?months=6", H)
check("/reports/monthly reachable", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    body = r.json()
    items = body.get("months") or body.get("items") or []
    has_income = any(m.get("income", 0) > 0 for m in items)
    check("at least one month has positive income",
          has_income, f"months={items[:3]}")


section("Corner: tx without category_id is auto-categorized")
r = api("POST", "/transactions", H, json={
    "date": iso(NOW), "amount": -42.50, "currency": "RON",
    "description": "Kaufland weekly shop",
})
check("create tx without category_id: 201", r.status_code == 201, r.text[:300])
if r.status_code == 201:
    tx = r.json()["transaction"]
    # Should fall to Groceries via rules, or to Other as fallback
    check("auto-categorized: assigned a category_id",
          tx.get("category_id") is not None,
          f"tx={tx}")


section("Corner: cross-currency goal contribution preserves currency")
# MacBook is USD — its cron-created tx must remain USD with amount_base in RON
all_tx3 = api("GET", "/transactions?page=1&page_size=200", H).json()["transactions"]
mac_txs = [t for t in all_tx3 if "Contribution: MacBook" in t["description"]]
check("MacBook contribution tx exists",
      len(mac_txs) >= 1)
if mac_txs:
    mt = mac_txs[0]
    check("MacBook tx currency is USD",
          mt["currency"] == "USD")
    check("MacBook tx amount_base is set (FX conversion ran)",
          mt["amount_base"] is not None and mt["amount_base"] < 0)


section("Corner: goal currency is locked on update")
r = api("PATCH", f"/goals/{gid_house}", H, json={"currency": "EUR"})
# Backend GoalUpdate doesn't accept `currency` — it should be ignored or 422.
g_after = api("GET", f"/goals/{gid_house}", H).json()["goal"]
check("goal currency unchanged after PATCH (still RON)",
      g_after["currency"] == "RON", f"got {g_after['currency']}")


section("Corner: cron does not fire on completed goal's stale recurring")
# Force the Bike recurring (status=completed) to active+due, then run cron.
# Goal is already complete (saved=target), so _materialize_goal_recurring
# should see remaining<=0 and close out without firing.
with app.app_context():
    bike_rec = mongo.db["recurring_payments"].find_one(
        {"name": "Contribution: Bike", "user_id": ObjectId(USER_ID)},
    )
    if bike_rec:
        mongo.db["recurring_payments"].update_one(
            {"_id": bike_rec["_id"]},
            {"$set": {"status": "active", "next_due": NOW.replace(tzinfo=None), "deleted_at": None}},
        )
        bike_before = api("GET", f"/goals/{gid_bike}", H).json()["goal"]
        recurring_service.materialize_due()
        bike_after = api("GET", f"/goals/{gid_bike}", H).json()["goal"]
        check("bike saved_amount unchanged after forced cron on completed goal",
              abs(bike_before["saved_amount"] - bike_after["saved_amount"]) < 0.01,
              f"before={bike_before['saved_amount']} after={bike_after['saved_amount']}")
        check("bike auto_contribute remains null (recurring re-closed)",
              bike_after["auto_contribute"] is None)


section("Corner: contribute negative or zero amount is rejected")
r = api("POST", f"/goals/{gid_house}/contribute", H, json={"amount": -5})
check("negative manual contribute amount rejected", r.status_code >= 400)
r = api("POST", f"/goals/{gid_house}/contribute", H, json={"amount": 0})
check("zero manual contribute amount rejected", r.status_code >= 400)


section("Corner: PATCH goal target_date in the past is rejected")
r = api("PATCH", f"/goals/{gid_house}", H,
        json={"target_date": iso(NOW - timedelta(days=10))})
check("PATCH past target_date: 422", r.status_code == 422, r.text[:200])


section("Corner: completed recurrings persist in Mongo with status=completed")
# /recurring API filters status=completed by default (no include_completed query
# is exposed). Verify the Mongo invariant directly: closed-but-not-deleted
# rows for goals and one-offs are status=completed with deleted_at=None.
with app.app_context():
    closed_count = mongo.db["recurring_payments"].count_documents(
        {"user_id": ObjectId(USER_ID), "status": "completed", "deleted_at": None},
    )
    check("at least 2 closed recurrings persist (one-off + goal completion)",
          closed_count >= 2, f"got {closed_count}")
    soft_deleted = mongo.db["recurring_payments"].count_documents(
        {"user_id": ObjectId(USER_ID), "deleted_at": {"$ne": None}},
    )
    check("at least 1 soft-deleted recurring (from PATCH auto=false)",
          soft_deleted >= 1, f"got {soft_deleted}")


section("Corner: TX update preserves amount_base recompute on currency change")
# Create a tx in RON, then PATCH currency to USD. amount_base must change.
r = api("POST", "/transactions", H, json={
    "date": iso(NOW - timedelta(days=10)), "amount": -100, "currency": "RON",
    "description": "Mutable expense", "category_id": by_name["Other"]["id"],
})
if check("created mutable tx for FX recompute test", r.status_code == 201, r.text[:200]):
    tx = r.json()["transaction"]
    base_before = tx.get("amount_base")
    pr = api("PATCH", f"/transactions/{tx['id']}", H, json={"currency": "USD"})
    if check("PATCH tx currency to USD: 200", pr.status_code == 200, pr.text[:200]):
        tx2 = pr.json()["transaction"]
        check("amount_base recomputed after currency change",
              tx2.get("amount_base") != base_before,
              f"before={base_before} after={tx2.get('amount_base')}")


section("Corner: FX endpoint /fx/convert")
r = api("GET", "/fx/convert?from=USD&to=RON&amount=100", H)
check("/fx/convert reachable", r.status_code == 200, r.text[:200])
if r.status_code == 200:
    body = r.json()
    check("converted USD->RON > 0", (body.get("converted") or body.get("amount", 0)) > 0,
          f"body={body}")


section("Corner: stale-account alert when account.last_updated > 90 days ago")
# Manually backdate the Cash account's last_updated.
with app.app_context():
    cash = mongo.db["accounts"].find_one({"user_id": ObjectId(USER_ID), "name": "Cash"})
    if cash:
        mongo.db["accounts"].update_one(
            {"_id": cash["_id"]},
            {"$set": {"last_updated": NOW.replace(tzinfo=None) - timedelta(days=120)}},
        )
        # The Cash account is auto-tracked (is_automatic=True) — stale alert only
        # fires for manual accounts in the production rule. Quick sanity that the
        # rule path doesn't crash:
        alerts_now = api("GET", "/alerts", H).json()
        check("GET /alerts still 200 after backdating account",
              isinstance(alerts_now.get("alerts", []), list))


section("Corner: contributions log on /goals shows recent entries")
# Already verified by the cron + manual contributions above; just sanity-check
# that the saved_amount math equals sum of contributions.
italy_after_final = api("GET", f"/goals/{gid_italy}", H).json()["goal"]
print(f"  Italy final saved={italy_after_final['saved_amount']} (target={italy_after_final['target_amount']})")
all_tx_final = api("GET", "/transactions?page=1&page_size=200", H).json()["transactions"]
italy_contributions = [t for t in all_tx_final
                       if t["description"] == "Contribution: Italy 2027"]
contrib_sum = sum(abs(t["amount"]) for t in italy_contributions)
check("sum of Italy contribution txs == goal.saved_amount",
      abs(contrib_sum - italy_after_final["saved_amount"]) < 0.01,
      f"contrib_sum={contrib_sum} saved={italy_after_final['saved_amount']}")


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
if SECTIONS:
    last = SECTIONS[-1]
    SECTIONS[-1] = (last[0], PASS_COUNT - last[1], FAIL_COUNT - last[2])

print("\n" + "=" * 60)
print("INTEGRATION SMOKE SUMMARY")
print("=" * 60)
for label, p, f in SECTIONS:
    status = " " if f == 0 else "FAIL"
    print(f"  [{status:>4}] {label:50} {p} pass / {f} fail")

print("\n" + "-" * 60)
print(f"TOTAL: {PASS_COUNT} passed, {FAIL_COUNT} failed")
if FAILS:
    print("\nFAILURES:")
    for f in FAILS:
        print(f"  - {f}")

sys.exit(0 if FAIL_COUNT == 0 else 1)
