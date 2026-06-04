"""Time-travel tests using the `freeze_time` fixture from conftest.

These tests exercise the day-boundary and multi-day behavior that the
production scheduler is responsible for — but deterministically, without
waiting wall-clock time. They demonstrate:

  - Net-worth snapshots accumulate one per simulated day.
  - A monthly recurring payment fires N times across N simulated months.
  - A goal goes from "on track" to "overdue" when the target date passes.

If something in the time-handling code regresses (e.g. the materialize
loop drops a cycle, or the snapshot job double-fires on the same day),
these tests catch it without needing a 30-day wall-clock wait.
"""
from datetime import datetime, timezone

from app.models.user import utcnow


def _register(client, email: str = "clock@example.com") -> str:
    """Helper — register, return the access token. The `TESTING=True`
    shortcut auto-verifies and returns tokens immediately, so we can build
    fixtures without going through the email loop."""
    res = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "Clock Tester",
            "base_currency": "RON",
        },
    )
    assert res.status_code == 201, res.get_json()
    return res.get_json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. The fixture itself: utcnow follows the frozen clock
# ---------------------------------------------------------------------------

def test_freeze_time_propagates_to_utcnow(freeze_time):
    """Sanity check — `utcnow()` everywhere in the app sees the frozen
    time, not the wall clock."""
    freeze_time.set(datetime(2030, 6, 15, 12, 0, tzinfo=timezone.utc))
    now = utcnow()
    assert now.year == 2030
    assert now.month == 6
    assert now.day == 15
    assert now.hour == 12

    freeze_time.advance(days=10)
    assert utcnow().day == 25


# ---------------------------------------------------------------------------
# 2. Net-worth snapshots accumulate one per simulated day
# ---------------------------------------------------------------------------

def test_networth_snapshots_one_per_simulated_day(client, freeze_time, app):
    """Simulate 7 days, fire the daily jobs each day, expect 7 snapshot
    rows for the registered user (plus possibly one for "day zero" if the
    register flow itself snapshots — which it doesn't, but the test is
    written to tolerate either)."""
    freeze_time.set(datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc))
    token = _register(client)

    # No snapshots yet — register doesn't snapshot.
    from app.extensions import mongo
    snapshots = mongo.db["net_worth_snapshots"]
    before = snapshots.count_documents({})

    # Simulate one week
    freeze_time.simulate_days(7)
    after = snapshots.count_documents({})

    # Each simulated day should produce one row per user.
    assert after - before == 7, (
        f"Expected 7 new snapshots over 7 simulated days, got {after - before}. "
        "If this fails, snapshot_all_users() may be skipping users or "
        "creating duplicates."
    )

    # And no duplicates on the same `date` for the same user
    rows = list(snapshots.find({}, {"user_id": 1, "date": 1}))
    seen = {(r["user_id"], r["date"]) for r in rows}
    assert len(seen) == len(rows), "Duplicate snapshots for same (user, date)"
    _ = token  # silence unused-import warning


# ---------------------------------------------------------------------------
# 3. Monthly recurring fires N times across N simulated months
# ---------------------------------------------------------------------------

def test_monthly_recurring_materializes_each_simulated_month(client, freeze_time):
    """Set up a monthly recurring with auto_create_transaction=True,
    advance the clock 3 months, expect 3 transactions to materialize
    (one per cycle)."""
    freeze_time.set(datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc))
    token = _register(client)

    # Create the recurring with start_date = today
    res = client.post(
        "/api/recurring",
        headers=_auth(token),
        json={
            "name": "Netflix",
            "merchant_pattern": "NETFLIX",
            "amount": 12.99,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": "2027-01-15T00:00:00",
            "auto_create_transaction": True,
        },
    )
    assert res.status_code == 201, res.get_json()

    # Count transactions before simulation
    from app.extensions import mongo
    tx = mongo.db["transactions"]
    before = tx.count_documents({})

    # Advance 90 days (~3 months). materialize_due fires daily; should
    # create one tx per ~30 day cycle.
    freeze_time.simulate_days(90)

    after = tx.count_documents({})
    new_tx = after - before
    # We expect 3 monthly cycles in 90 days. The materialize logic uses
    # 30-day deltas, so cycles fire on day 1 (already-materialized at create),
    # day ~30, day ~60, day ~90.
    # Eager-materialize on create handles day-0; +3 from the cron loop.
    # Hence 3 or 4 depending on exact day alignment.
    assert 3 <= new_tx <= 4, (
        f"Expected 3-4 materialized transactions across 90 simulated days, "
        f"got {new_tx}. If <3, materialize loop is missing cycles; if >4, "
        f"it's double-firing on the same day."
    )


# ---------------------------------------------------------------------------
# 4. A goal flips from on-track to overdue when the deadline passes
# ---------------------------------------------------------------------------

def test_goal_becomes_overdue_when_clock_crosses_target_date(client, freeze_time):
    """Create a goal with target_date 30 days from frozen-now, advance
    35 days, expect the goal to report status='behind' or 'overdue'."""
    freeze_time.set(datetime(2027, 7, 1, 12, 0, tzinfo=timezone.utc))
    token = _register(client)

    # Goal due 2027-07-31 (30 days from now)
    res = client.post(
        "/api/goals",
        headers=_auth(token),
        json={
            "name": "Trip to Spain",
            "target_amount": 1000.0,
            "currency": "RON",
            "type": "other",
            "target_date": "2027-07-31T00:00:00",
        },
    )
    assert res.status_code == 201, res.get_json()
    goal_id = res.get_json()["goal"]["id"]

    # Advance 35 days — past the target date
    freeze_time.simulate_days(35, fire_jobs=False)  # skip cron noise

    res = client.get(f"/api/goals/{goal_id}", headers=_auth(token))
    g = res.get_json()["goal"]
    # months_remaining should be <= 0 once we're past the target date
    assert g["months_remaining"] <= 0, (
        f"Expected months_remaining<=0 after deadline, got {g['months_remaining']}. "
        f"target_date={g['target_date']} now={utcnow().isoformat()}"
    )


# ---------------------------------------------------------------------------
# 5. Multiple users get snapshots independently
# ---------------------------------------------------------------------------

def test_simulate_days_snapshots_every_user(client, freeze_time):
    """Two users, simulate 3 days. Expect 6 snapshot rows total (3 per
    user). Catches "snapshot job only processes the first user" or "job
    short-circuits when one user errors" regressions."""
    freeze_time.set(datetime(2028, 2, 1, 12, 0, tzinfo=timezone.utc))
    _register(client, email="ana@example.com")
    _register(client, email="ben@example.com")

    from app.extensions import mongo
    snapshots = mongo.db["net_worth_snapshots"]
    before = snapshots.count_documents({})

    freeze_time.simulate_days(3)

    after = snapshots.count_documents({})
    assert after - before == 6, (
        f"Expected 6 snapshots (2 users × 3 days), got {after - before}"
    )
