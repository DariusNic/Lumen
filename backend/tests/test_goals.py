from datetime import datetime, timedelta, timezone


def _register(client):
    return client.post(
        "/api/auth/register",
        json={
            "email": "ana@example.com",
            "password": "password123",
            "full_name": "Ana",
            "base_currency": "RON",
        },
    ).get_json()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _future(months: int) -> str:
    d = datetime.now(timezone.utc) + timedelta(days=30 * months)
    return d.replace(microsecond=0).isoformat()


def test_create_goal_returns_dual_pace_math(client):
    body = _register(client)
    res = client.post(
        "/api/goals",
        json={
            "name": "Italy vacation",
            "target_amount": 5000,
            "currency": "EUR",
            "target_date": _future(20),
            "type": "travel",
            "priority": 2,
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    g = res.get_json()["goal"]
    assert g["name"] == "Italy vacation"
    assert g["target_amount"] == 5000
    assert g["saved_amount"] == 0
    assert g["progress_pct"] == 0
    assert g["months_remaining"] >= 18  # ~20 months
    # simple = 5000 / months
    assert abs(g["monthly_simple"] - 5000 / g["months_remaining"]) < 0.5


def test_initial_deposit_counts_as_saved(client):
    body = _register(client)
    res = client.post(
        "/api/goals",
        json={
            "name": "Emergency fund",
            "target_amount": 12000,
            "currency": "RON",
            "target_date": _future(12),
            "initial_deposit": 4000,
            "type": "emergency",
        },
        headers=_auth(body["access_token"]),
    )
    g = res.get_json()["goal"]
    # Initial deposit is recorded as saved_amount and reduces the
    # required monthly contribution proportionally.
    assert g["saved_amount"] == 4000
    assert g["progress_pct"] == round(4000 / 12000 * 100, 1)
    # remaining 8000 spread over ~12 months
    assert abs(g["monthly_simple"] - 8000 / g["months_remaining"]) < 0.5


def test_create_rejects_past_target_date(client):
    body = _register(client)
    past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = client.post(
        "/api/goals",
        json={
            "name": "Old goal",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": past,
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_contribute_increments_saved_and_progress(client):
    body = _register(client)
    g = client.post(
        "/api/goals",
        json={
            "name": "Laptop",
            "target_amount": 8000,
            "currency": "RON",
            "target_date": _future(10),
        },
        headers=_auth(body["access_token"]),
    ).get_json()["goal"]

    res = client.post(
        f"/api/goals/{g['id']}/contribute",
        json={"amount": 1500},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    after = res.get_json()["goal"]
    assert after["saved_amount"] == 1500
    assert after["progress_pct"] == round(1500 / 8000 * 100, 1)


def test_contribute_to_completion_marks_status_completed(client):
    body = _register(client)
    g = client.post(
        "/api/goals",
        json={
            "name": "Phone",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
        },
        headers=_auth(body["access_token"]),
    ).get_json()["goal"]

    res = client.post(
        f"/api/goals/{g['id']}/contribute",
        json={"amount": 1000},
        headers=_auth(body["access_token"]),
    )
    after = res.get_json()["goal"]
    assert after["status"] == "completed"
    assert after["monthly_simple"] == 0


def test_update_goal(client):
    body = _register(client)
    g = client.post(
        "/api/goals",
        json={
            "name": "Test",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
        },
        headers=_auth(body["access_token"]),
    ).get_json()["goal"]

    res = client.patch(
        f"/api/goals/{g['id']}",
        json={"name": "Renamed", "target_amount": 2000},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    after = res.get_json()["goal"]
    assert after["name"] == "Renamed"
    assert after["target_amount"] == 2000


def test_delete_goal(client):
    body = _register(client)
    g = client.post(
        "/api/goals",
        json={
            "name": "Test",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
        },
        headers=_auth(body["access_token"]),
    ).get_json()["goal"]
    res = client.delete(f"/api/goals/{g['id']}", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    res2 = client.get(f"/api/goals/{g['id']}", headers=_auth(body["access_token"]))
    assert res2.status_code == 404


def test_list_requires_auth(client):
    res = client.get("/api/goals")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Auto-contribute flow (Goals category + recurring + clamp + completion)
# ---------------------------------------------------------------------------


def test_manual_contribute_creates_goal_transaction(client):
    """Every manual contribution is logged as a real transaction in the
    user's seeded "Goals" category — so it counts against budgets and
    shows in the transactions list / reports."""
    body = _register(client)
    h = _auth(body["access_token"])
    g = client.post(
        "/api/goals",
        json={"name": "Phone", "target_amount": 1000, "currency": "RON", "target_date": _future(6)},
        headers=h,
    ).get_json()["goal"]
    res = client.post(f"/api/goals/{g['id']}/contribute", json={"amount": 150}, headers=h)
    assert res.status_code == 200

    txs = client.get("/api/transactions?page=1&page_size=10", headers=h).get_json()["transactions"]
    contribution = next((t for t in txs if t["description"] == "Contribution: Phone"), None)
    assert contribution is not None, "expected contribution transaction"
    assert contribution["amount"] == -150
    assert contribution["currency"] == "RON"
    assert contribution["category_name"] == "Goals"
    assert contribution["source"] == "goal_contribution"


def test_auto_contribute_creates_linked_recurring(client):
    """Creating a goal with auto_contribute spins up a recurring_payments
    row whose name reads 'Contribution: <goal>' and whose goal_id points
    back at the goal. The recurring shows up on /api/recurring (the
    Planned page) like any other scheduled payment."""
    from datetime import datetime, timedelta, timezone

    body = _register(client)
    h = _auth(body["access_token"])
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Italy",
            "target_amount": 5000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 500, "start_date": start},
        },
        headers=h,
    ).get_json()["goal"]

    # The returned goal exposes the auto_contribute summary.
    assert g["auto_contribute"] is not None
    assert g["auto_contribute"]["amount"] == 500

    # And the recurring is on /api/recurring with the proper name.
    rec = client.get("/api/recurring", headers=h).get_json()["recurring"]
    matches = [r for r in rec if r["name"] == "Contribution: Italy"]
    assert len(matches) == 1
    assert matches[0]["goal_id"] == g["id"]
    assert matches[0]["amount"] == 500
    assert matches[0]["frequency"] == "monthly"
    assert matches[0]["is_income"] is False
    assert matches[0]["auto_create_transaction"] is True


def test_materialize_clamps_final_cycle_to_remaining(client):
    """Reproduces the user-described scenario: a manual contribution
    leaves less than one full monthly cycle remaining; the next auto
    contribution clamps to the remaining amount instead of overshooting
    the target. Verifies BOTH the transaction amount AND that the
    recurring is closed afterwards (no more cron firings)."""
    from datetime import datetime, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    today_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Laptop",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
            # Auto-contribute starts today (so it's due immediately) at
            # 800/mo. After a manual contribution of 500, the remaining
            # 500 < 800 — so this single cycle should clamp.
            "auto_contribute": {"amount": 800, "start_date": today_iso},
        },
        headers=h,
    ).get_json()["goal"]

    # Manual contribute 500 first.
    client.post(f"/api/goals/{g['id']}/contribute", json={"amount": 500}, headers=h)

    # Now fire the cron. The recurring's next_due is today (immediately due).
    stats = recurring_service.materialize_due()
    assert stats["created"] >= 1

    # After: saved is exactly target (no overshoot), recurring is closed.
    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after["saved_amount"] == 1000
    assert after["status"] == "completed"
    assert after["auto_contribute"] is None, "linked recurring should be completed"

    # Two Goals transactions: -500 (manual) + -500 (auto, clamped from 800).
    txs = client.get(
        "/api/transactions?page=1&page_size=20", headers=h,
    ).get_json()["transactions"]
    laptop_txs = [t for t in txs if t["description"] == "Contribution: Laptop"]
    amounts = sorted(t["amount"] for t in laptop_txs)
    assert amounts == [-500, -500], f"expected two -500s (manual + clamped auto), got {amounts}"


def test_completion_via_manual_contribute_closes_recurring(client):
    """Manual contribution that completes a goal also stops the linked
    recurring auto-contribute — the user shouldn't have to clean up
    a Planned-page entry that no longer makes sense."""
    from datetime import datetime, timedelta, timezone

    body = _register(client)
    h = _auth(body["access_token"])
    future_start = (datetime.now(timezone.utc) + timedelta(days=10)).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Bike",
            "target_amount": 600,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 100, "start_date": future_start},
        },
        headers=h,
    ).get_json()["goal"]
    assert g["auto_contribute"] is not None

    # Manual lump-sum contribute that completes the goal.
    after = client.post(
        f"/api/goals/{g['id']}/contribute", json={"amount": 600}, headers=h,
    ).get_json()["goal"]
    assert after["status"] == "completed"
    assert after["auto_contribute"] is None, "linked recurring should be auto-completed"

    # The recurring is now status=completed and won't appear in the
    # default Planned-page list (which filters to active).
    rec = client.get("/api/recurring", headers=h).get_json()["recurring"]
    assert all(r["name"] != "Contribution: Bike" for r in rec)


# ---------------------------------------------------------------------------
# Auto-contribute - exhaustive edge cases
# ---------------------------------------------------------------------------


def test_no_auto_contribute_no_recurring_created(client):
    """Sanity: creating a goal WITHOUT auto_contribute does NOT create a
    recurring_payments row."""
    body = _register(client)
    h = _auth(body["access_token"])
    g = client.post(
        "/api/goals",
        json={"name": "Sweet jar", "target_amount": 200, "currency": "RON", "target_date": _future(6)},
        headers=h,
    ).get_json()["goal"]
    assert g["auto_contribute"] is None

    rec = client.get("/api/recurring", headers=h).get_json()["recurring"]
    assert all(r["name"] != "Contribution: Sweet jar" for r in rec)


def test_auto_contribute_first_cycle_clamps_when_amount_overshoots(client):
    """Monthly auto-contribute amount > goal target on the very first cycle.
    The single firing should clamp to the target and close the recurring."""
    from datetime import datetime, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Tiny",
            "target_amount": 100,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 500, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]

    recurring_service.materialize_due()

    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after["saved_amount"] == 100, "auto contribute clamped to target"
    assert after["status"] == "completed"
    assert after["auto_contribute"] is None

    txs = client.get("/api/transactions?page=1&page_size=10", headers=h).get_json()["transactions"]
    tiny_txs = [t for t in txs if t["description"] == "Contribution: Tiny"]
    assert len(tiny_txs) == 1
    assert tiny_txs[0]["amount"] == -100  # clamped from -500


def test_auto_contribute_exact_match_completes_in_one_cycle(client):
    """Auto-contribute amount exactly equals target."""
    from datetime import datetime, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Exact",
            "target_amount": 300,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 300, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]
    recurring_service.materialize_due()

    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after["saved_amount"] == 300
    assert after["status"] == "completed"
    assert after["auto_contribute"] is None


def test_delete_goal_closes_linked_recurring(client):
    """Deleting a goal with auto_contribute should immediately close the
    recurring row so it stops showing on /planned."""
    from datetime import datetime, timezone

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "About to be deleted",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 100, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]

    rec_before = client.get("/api/recurring", headers=h).get_json()["recurring"]
    assert any(r["name"] == "Contribution: About to be deleted" for r in rec_before)

    res = client.delete(f"/api/goals/{g['id']}", headers=h)
    assert res.status_code == 200

    rec_after = client.get("/api/recurring", headers=h).get_json()["recurring"]
    assert all(r["name"] != "Contribution: About to be deleted" for r in rec_after)


def test_cross_currency_contribution_has_amount_base(client):
    """Goal currency != base currency. Verify the resulting transaction
    has amount_base computed via FX so reports / budgets handle it."""
    body = _register(client)
    h = _auth(body["access_token"])
    g = client.post(
        "/api/goals",
        json={"name": "EUR trip", "target_amount": 1000, "currency": "EUR", "target_date": _future(8)},
        headers=h,
    ).get_json()["goal"]
    client.post(f"/api/goals/{g['id']}/contribute", json={"amount": 50}, headers=h)

    txs = client.get("/api/transactions?page=1&page_size=10", headers=h).get_json()["transactions"]
    tx = next((t for t in txs if t["description"] == "Contribution: EUR trip"), None)
    assert tx is not None
    assert tx["currency"] == "EUR"
    assert tx["amount"] == -50
    assert tx["amount_base"] is not None
    assert tx["amount_base"] < 0


def test_two_goals_each_with_auto_contribute_independent(client):
    """Two goals, two recurrings. Each fires independently."""
    from datetime import datetime, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    g1 = client.post(
        "/api/goals",
        json={
            "name": "Goal A",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 100, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]
    g2 = client.post(
        "/api/goals",
        json={
            "name": "Goal B",
            "target_amount": 2000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 200, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]

    recurring_service.materialize_due()

    after_a = client.get(f"/api/goals/{g1['id']}", headers=h).get_json()["goal"]
    after_b = client.get(f"/api/goals/{g2['id']}", headers=h).get_json()["goal"]
    assert after_a["saved_amount"] == 100
    assert after_b["saved_amount"] == 200
    assert after_a["status"] != "completed"
    assert after_b["status"] != "completed"


def test_materialize_due_is_idempotent_within_same_cycle(client):
    """Calling materialize_due twice without elapsed cycle time should
    contribute exactly once."""
    from datetime import datetime, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Idempotent",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 50, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]

    recurring_service.materialize_due()
    after_first = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]

    recurring_service.materialize_due()
    after_second = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]

    assert after_first["saved_amount"] == 50
    assert after_second["saved_amount"] == 50


def test_completed_goal_recurring_does_not_fire_on_cron(client):
    """If the recurring is somehow still active after the goal is
    complete (corrupted state), the goal-aware cron path defends
    against double-contributing."""
    from datetime import datetime, timezone
    from app.services import recurring_service
    from app.extensions import mongo
    from bson import ObjectId

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Filled",
            "target_amount": 500,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 100, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]

    client.post(f"/api/goals/{g['id']}/contribute", json={"amount": 500}, headers=h)

    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after["status"] == "completed"
    assert after["auto_contribute"] is None

    rec = mongo.db["recurring_payments"].find_one({"goal_id": ObjectId(g["id"])})
    if rec is not None:
        mongo.db["recurring_payments"].update_one(
            {"_id": rec["_id"]},
            {"$set": {"status": "active"}},
        )
        recurring_service.materialize_due()

    after_cron = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after_cron["saved_amount"] == 500


def test_goal_update_does_not_touch_auto_contribute(client):
    """PATCH /api/goals/:id must not accidentally close/modify the linked
    recurring."""
    from datetime import datetime, timezone

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Mutable",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 100, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]
    assert g["auto_contribute"] is not None
    rec_id_before = g["auto_contribute"]["recurring_id"]

    client.patch(
        f"/api/goals/{g['id']}",
        json={"name": "Renamed", "target_amount": 1500},
        headers=h,
    )

    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after["name"] == "Renamed"
    assert after["target_amount"] == 1500
    assert after["auto_contribute"] is not None
    assert after["auto_contribute"]["recurring_id"] == rec_id_before
    assert after["auto_contribute"]["amount"] == 100


def test_goal_with_initial_deposit_meeting_target_still_safe(client):
    """initial_deposit == target_amount + auto_contribute set. The
    recurring exists but the next cron firing finds remaining<=0 and
    closes it without contributing."""
    from datetime import datetime, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Pre-funded",
            "target_amount": 500,
            "currency": "RON",
            "target_date": _future(6),
            "initial_deposit": 500,
            "auto_contribute": {"amount": 100, "start_date": today},
        },
        headers=h,
    ).get_json()["goal"]
    assert g["saved_amount"] == 500
    assert g["status"] == "completed"

    recurring_service.materialize_due()
    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    assert after["saved_amount"] == 500
    assert after["auto_contribute"] is None


def test_recurring_list_includes_goal_id_field(client):
    """/api/recurring must include goal_id (nullable) on every row."""
    from datetime import datetime, timezone

    body = _register(client)
    h = _auth(body["access_token"])
    today = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    client.post(
        "/api/recurring",
        json={
            "name": "Netflix",
            "merchant_pattern": "NETFLIX",
            "amount": 30,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": today,
            "auto_create_transaction": False,
        },
        headers=h,
    )
    client.post(
        "/api/goals",
        json={
            "name": "Linked",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(6),
            "auto_contribute": {"amount": 100, "start_date": today},
        },
        headers=h,
    )

    rec = client.get("/api/recurring", headers=h).get_json()["recurring"]
    netflix = next(r for r in rec if r["name"] == "Netflix")
    linked = next(r for r in rec if r["name"] == "Contribution: Linked")
    assert "goal_id" in netflix and netflix["goal_id"] is None
    assert "goal_id" in linked and linked["goal_id"] is not None


def test_goals_category_is_in_default_list(client):
    """The "Goals" system category is seeded with the right color and is_default=True."""
    body = _register(client)
    h = _auth(body["access_token"])
    cats = client.get("/api/categories", headers=h).get_json()["categories"]
    goals = next((c for c in cats if c["name"] == "Goals"), None)
    assert goals is not None
    assert goals["is_default"] is True
    assert goals["color"] == "#a855f7"
    assert goals["monthly_budget"] == 0.0


def test_set_budget_on_goals_category_and_see_spending(client):
    """A contribution to a goal shows up as spending against the Goals
    category in the spending report — verifies the Goals category
    behaves like every other expense category for budgeting + reports.
    The date range goes a year out so any contribute today lands inside
    the window regardless of clock skew."""
    from datetime import datetime, timezone

    body = _register(client)
    h = _auth(body["access_token"])

    cats = client.get("/api/categories", headers=h).get_json()["categories"]
    goals_cat = next(c for c in cats if c["name"] == "Goals")

    res = client.patch(
        f"/api/categories/{goals_cat['id']}",
        json={"monthly_budget": 200},
        headers=h,
    )
    assert res.status_code == 200
    assert res.get_json()["category"]["monthly_budget"] == 200

    g = client.post(
        "/api/goals",
        json={"name": "Budgeted", "target_amount": 500, "currency": "RON", "target_date": _future(6)},
        headers=h,
    ).get_json()["goal"]
    client.post(f"/api/goals/{g['id']}/contribute", json={"amount": 50}, headers=h)

    year = datetime.now(timezone.utc).year
    report = client.get(
        f"/api/reports/spending?from={year}-01-01&to={year + 1}-12-31", headers=h,
    ).get_json()
    goals_line = next((it for it in report["items"] if it["category_name"] == "Goals"), None)
    assert goals_line is not None
    assert goals_line["total"] == 50


def test_lazy_reseed_when_goals_category_is_missing(client):
    """If the Goals category somehow goes missing (corrupted state,
    migration gone wrong — the public API rightly refuses to delete
    system categories), the next contribution lazily re-seeds it via
    `_get_or_seed_goals_category`. Test simulates the missing state
    by directly soft-deleting the row in Mongo."""
    from app.extensions import mongo

    body = _register(client)
    h = _auth(body["access_token"])

    cats = client.get("/api/categories", headers=h).get_json()["categories"]
    goals_cat = next(c for c in cats if c["name"] == "Goals")

    # Simulate a corrupted state — Goals category soft-deleted in Mongo
    # bypassing the API's "system categories can't be deleted" guard.
    from bson import ObjectId
    from datetime import datetime, timezone
    mongo.db["categories"].update_one(
        {"_id": ObjectId(goals_cat["id"])},
        {"$set": {"deleted_at": datetime.now(timezone.utc)}},
    )

    # Contributions still succeed — lazy seed re-creates the row.
    g = client.post(
        "/api/goals",
        json={"name": "Resilient", "target_amount": 500, "currency": "RON", "target_date": _future(6)},
        headers=h,
    ).get_json()["goal"]
    res2 = client.post(f"/api/goals/{g['id']}/contribute", json={"amount": 50}, headers=h)
    assert res2.status_code == 200

    cats2 = client.get("/api/categories", headers=h).get_json()["categories"]
    assert any(c["name"] == "Goals" for c in cats2)


def test_system_categories_cannot_be_deleted_via_api(client):
    """Sanity: the public API refuses to delete the seeded Goals
    category. (This is what protects the contribution path from
    requiring the lazy reseed in normal operation.)"""
    body = _register(client)
    h = _auth(body["access_token"])
    cats = client.get("/api/categories", headers=h).get_json()["categories"]
    goals_cat = next(c for c in cats if c["name"] == "Goals")
    res = client.delete(f"/api/categories/{goals_cat['id']}", headers=h)
    assert res.status_code == 422
    assert "system" in res.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Auto-contribute - edit-after-create flow (add / edit / disable on existing)
# ---------------------------------------------------------------------------


def _next_month(year: int, month: int) -> tuple[int, int]:
    """Roll (year, month) forward by one calendar month."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def test_add_auto_contribute_to_existing_goal(client):
    """A goal created without auto can have auto added later via PATCH.
    The new recurring's next_due is the first occurrence of the picked
    day-of-month in the NEXT calendar month — never this month, even if
    the chosen day is still in the future this month."""
    from datetime import datetime, timezone
    from app.extensions import mongo
    from bson import ObjectId

    body = _register(client)
    h = _auth(body["access_token"])
    g = client.post(
        "/api/goals",
        json={
            "name": "Late starter",
            "target_amount": 1200,
            "currency": "RON",
            "target_date": _future(12),
        },
        headers=h,
    ).get_json()["goal"]
    assert g["auto_contribute"] is None

    # Pick day 15 of "today's month" — next_due should land on day 15 of
    # the earliest month whose 15th is still on/after today (this month if
    # 15th is ahead, next month if it has passed). Defer to the helper so
    # the test stays stable regardless of when it runs.
    from app.services.goal_service import _next_monthly_anchor
    now = datetime.now(timezone.utc)
    picked_iso = now.replace(day=15, hour=12, minute=0, second=0, microsecond=0).isoformat()
    res = client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": {"amount": 200, "start_date": picked_iso}},
        headers=h,
    )
    assert res.status_code == 200
    updated = res.get_json()["goal"]
    assert updated["auto_contribute"] is not None
    assert updated["auto_contribute"]["amount"] == 200

    rec = mongo.db["recurring_payments"].find_one(
        {"goal_id": ObjectId(g["id"]), "status": "active"},
    )
    assert rec is not None
    expected = _next_monthly_anchor(now, 15)
    assert (rec["next_due"].year, rec["next_due"].month, rec["next_due"].day) == (
        expected.year, expected.month, expected.day,
    )
    # start_date is preserved verbatim — day-of-month survives future edits.
    assert rec["start_date"].day == 15


def test_edit_auto_contribute_amount_keeps_day_resnaps_next_due(client):
    """Editing only the amount on an existing auto-goal updates the
    recurring's amount and re-snaps next_due via `_next_monthly_anchor`.
    start_date is preserved (day-of-month carries forward)."""
    from datetime import datetime, timezone
    from app.extensions import mongo
    from app.services.goal_service import _next_monthly_anchor
    from bson import ObjectId

    body = _register(client)
    h = _auth(body["access_token"])
    now = datetime.now(timezone.utc)
    initial_iso = now.replace(day=10, hour=12, minute=0, second=0, microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Edit me",
            "target_amount": 2000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 150, "start_date": initial_iso},
        },
        headers=h,
    ).get_json()["goal"]

    # Edit amount only — re-use the original day.
    new_iso = now.replace(day=10, hour=12, minute=0, second=0, microsecond=0).isoformat()
    client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": {"amount": 250, "start_date": new_iso}},
        headers=h,
    )

    rec = mongo.db["recurring_payments"].find_one(
        {"goal_id": ObjectId(g["id"]), "status": "active"},
    )
    assert rec is not None
    assert rec["amount"] == 250
    assert rec["start_date"].day == 10
    expected = _next_monthly_anchor(now, 10)
    assert (rec["next_due"].year, rec["next_due"].month, rec["next_due"].day) == (
        expected.year, expected.month, expected.day,
    )


def test_edit_auto_contribute_changes_day_of_month(client):
    """Changing the day on an existing auto-goal updates both start_date
    and next_due (next-month on the new picked day)."""
    from datetime import datetime, timezone
    from app.extensions import mongo
    from bson import ObjectId

    body = _register(client)
    h = _auth(body["access_token"])
    now = datetime.now(timezone.utc)
    initial_iso = now.replace(day=5, hour=12, minute=0, second=0, microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Day shifter",
            "target_amount": 2000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 100, "start_date": initial_iso},
        },
        headers=h,
    ).get_json()["goal"]

    # User picks day 20 instead — start_date updates, next_due re-snaps
    # via `_next_monthly_anchor` (this month if day 20 is still ahead,
    # next month otherwise). Defer to the helper to stay date-stable.
    from app.services.goal_service import _next_monthly_anchor
    new_iso = now.replace(day=20, hour=12, minute=0, second=0, microsecond=0).isoformat()
    client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": {"amount": 100, "start_date": new_iso}},
        headers=h,
    )

    rec = mongo.db["recurring_payments"].find_one(
        {"goal_id": ObjectId(g["id"]), "status": "active"},
    )
    assert rec["start_date"].day == 20
    expected = _next_monthly_anchor(now, 20)
    assert (rec["next_due"].year, rec["next_due"].month, rec["next_due"].day) == (
        expected.year, expected.month, expected.day,
    )


def test_disable_auto_contribute_soft_deletes_recurring(client):
    """Setting auto_contribute=false on PATCH soft-deletes the linked
    recurring. The goal no longer surfaces auto_contribute, and the row
    disappears from the Planned list (filtered by status=active)."""
    from datetime import datetime, timezone

    body = _register(client)
    h = _auth(body["access_token"])
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    g = client.post(
        "/api/goals",
        json={
            "name": "Disable me",
            "target_amount": 1000,
            "currency": "RON",
            "target_date": _future(12),
            "auto_contribute": {"amount": 100, "start_date": now_iso},
        },
        headers=h,
    ).get_json()["goal"]
    assert g["auto_contribute"] is not None

    res = client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": False},
        headers=h,
    )
    assert res.status_code == 200
    after = res.get_json()["goal"]
    assert after["auto_contribute"] is None

    rec_list = client.get("/api/recurring", headers=h).get_json()["recurring"]
    assert all(r["name"] != "Contribution: Disable me" for r in rec_list)


def test_disable_auto_contribute_idempotent_when_no_auto(client):
    """Disabling auto on a goal that doesn't have one is a no-op (not
    an error)."""
    body = _register(client)
    h = _auth(body["access_token"])
    g = client.post(
        "/api/goals",
        json={
            "name": "Never auto",
            "target_amount": 500,
            "currency": "RON",
            "target_date": _future(6),
        },
        headers=h,
    ).get_json()["goal"]

    res = client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": False},
        headers=h,
    )
    assert res.status_code == 200
    assert res.get_json()["goal"]["auto_contribute"] is None


def test_next_monthly_anchor_semantics(client):
    """`_next_monthly_anchor` returns the earliest valid anchor on/after now.

    Bug fix 2026-06-03: it used to always roll to next month. Now: this
    month if the anchor day is still ahead, next month if it has passed,
    with day-clamp when the destination month is shorter.
    """
    from app.services.goal_service import _next_monthly_anchor
    from datetime import datetime

    # This month's anchor still ahead → use this month (the bug fix case).
    assert _next_monthly_anchor(datetime(2026, 6, 3), 7) == datetime(2026, 6, 7)
    # This month's anchor passed → roll to next month.
    assert _next_monthly_anchor(datetime(2026, 6, 10), 7) == datetime(2026, 7, 7)
    # Anchor exactly today → returns today (>= comparison).
    assert _next_monthly_anchor(datetime(2026, 6, 3), 3) == datetime(2026, 6, 3)
    # Clamp: pick day 31 in April (30 days) → Apr 30, still this month.
    assert _next_monthly_anchor(datetime(2026, 4, 1), 31) == datetime(2026, 4, 30)
    # Year-roll: Dec 15, anchor day 10 → next month is Jan of next year.
    assert _next_monthly_anchor(datetime(2026, 12, 15), 10) == datetime(2027, 1, 10)


def test_edit_auto_with_future_start_does_not_fire_cron(client):
    """Sanity: after editing auto on an existing goal with a future
    start_date, the cron does NOT contribute today — next_due is the
    chosen day in a future month."""
    from datetime import datetime, timedelta, timezone
    from app.services import recurring_service

    body = _register(client)
    h = _auth(body["access_token"])
    now = datetime.now(timezone.utc)
    g = client.post(
        "/api/goals",
        json={
            "name": "Slow burn",
            "target_amount": 2000,
            "currency": "RON",
            "target_date": _future(12),
        },
        headers=h,
    ).get_json()["goal"]
    # Pick a day-of-month that's already passed → next anchor is next
    # calendar month, well in the future, so no firing today.
    yesterday = (now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    picked_iso = yesterday.isoformat()
    client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": {"amount": 150, "start_date": picked_iso}},
        headers=h,
    )

    recurring_service.materialize_due()
    after = client.get(f"/api/goals/{g['id']}", headers=h).get_json()["goal"]
    # Nothing should have fired — next_due is yesterday's day-of-month
    # in next calendar month, still in the future.
    assert after["saved_amount"] == 0


# ---------------------------------------------------------------------------
# Completed goals are read-only
# ---------------------------------------------------------------------------

def _completed_goal(client, h):
    g = client.post(
        "/api/goals",
        json={
            "name": "Already done",
            "target_amount": 500,
            "currency": "RON",
            "target_date": _future(6),
        },
        headers=h,
    ).get_json()["goal"]
    client.post(
        f"/api/goals/{g['id']}/contribute",
        json={"amount": 500},
        headers=h,
    )
    return g


def test_completed_goal_rejects_update(client):
    body = _register(client)
    h = _auth(body["access_token"])
    g = _completed_goal(client, h)

    res = client.patch(
        f"/api/goals/{g['id']}",
        json={"name": "Try to rename"},
        headers=h,
    )
    assert res.status_code == 422
    assert "completed" in res.get_json()["message"].lower()


def test_completed_goal_rejects_auto_contribute_setup(client):
    body = _register(client)
    h = _auth(body["access_token"])
    g = _completed_goal(client, h)

    res = client.patch(
        f"/api/goals/{g['id']}",
        json={"auto_contribute": {"amount": 100, "start_date": _future(1)}},
        headers=h,
    )
    assert res.status_code == 422
    # And no recurring_payments row was created for the completed goal.
    from app.extensions import mongo
    from bson import ObjectId
    assert mongo.db["recurring_payments"].count_documents(
        {"goal_id": ObjectId(g["id"]), "deleted_at": None, "status": "active"}
    ) == 0


def test_completed_goal_rejects_manual_contribute(client):
    body = _register(client)
    h = _auth(body["access_token"])
    g = _completed_goal(client, h)

    res = client.post(
        f"/api/goals/{g['id']}/contribute",
        json={"amount": 50},
        headers=h,
    )
    assert res.status_code == 422
    assert "completed" in res.get_json()["message"].lower()


def test_completed_goal_can_still_be_deleted(client):
    body = _register(client)
    h = _auth(body["access_token"])
    g = _completed_goal(client, h)

    res = client.delete(f"/api/goals/{g['id']}", headers=h)
    assert res.status_code == 200
    # Goal is gone from the list.
    after = client.get("/api/goals", headers=h).get_json()["goals"]
    assert all(item["id"] != g["id"] for item in after)
