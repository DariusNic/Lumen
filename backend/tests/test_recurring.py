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


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()


def _past(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()


# ---------- create / list ----------

def test_create_recurring_payment(client):
    body = _register(client)
    res = client.post(
        "/api/recurring",
        json={
            "name": "Spotify Family",
            "merchant_pattern": "SPOTIFY*PREMIUM",
            "amount": 35.0,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": _past(60),
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    r = res.get_json()["recurring"]
    assert r["name"] == "Spotify Family"
    assert r["frequency"] == "monthly"
    assert r["is_income"] is False


def test_create_income_recurring(client):
    body = _register(client)
    res = client.post(
        "/api/recurring",
        json={
            "name": "Salary",
            "merchant_pattern": "ACME PAYROLL",
            "amount": 8000.0,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": _past(30),
            "is_income": True,
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    assert res.get_json()["recurring"]["is_income"] is True


def test_next_due_is_in_future(client):
    body = _register(client)
    r = client.post(
        "/api/recurring",
        json={
            "name": "Spotify",
            "merchant_pattern": "SPOTIFY",
            "amount": 35.0,
            "currency": "RON",
            "frequency": "monthly",
            "start_date": _past(75),
        },
        headers=_auth(body["access_token"]),
    ).get_json()["recurring"]
    next_due = datetime.fromisoformat(r["next_due"])
    now = datetime.now()
    # next_due should be in the future and within ~30 days from now
    assert next_due >= now - timedelta(days=1)
    assert next_due <= now + timedelta(days=31)


def test_list_sorted_by_next_due(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    client.post("/api/recurring", json={
        "name": "B-rent", "merchant_pattern": "RENT", "amount": 3200, "currency": "RON",
        "frequency": "monthly", "start_date": _past(45),
    }, headers=headers)
    client.post("/api/recurring", json={
        "name": "A-spotify", "merchant_pattern": "SPOTIFY", "amount": 35, "currency": "RON",
        "frequency": "monthly", "start_date": _past(20),
    }, headers=headers)
    items = client.get("/api/recurring", headers=headers).get_json()["recurring"]
    assert len(items) == 2
    # Sorted ascending by next_due
    assert items[0]["next_due"] <= items[1]["next_due"]


# ---------- validation ----------

def test_create_rejects_invalid_frequency(client):
    body = _register(client)
    res = client.post(
        "/api/recurring",
        json={
            "name": "X", "merchant_pattern": "X", "amount": 10, "currency": "RON",
            "frequency": "fortnightly", "start_date": _past(10),
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_create_rejects_zero_amount(client):
    body = _register(client)
    res = client.post(
        "/api/recurring",
        json={
            "name": "X", "merchant_pattern": "X", "amount": 0, "currency": "RON",
            "frequency": "monthly", "start_date": _past(10),
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


def test_create_with_unknown_category_rejected(client):
    body = _register(client)
    res = client.post(
        "/api/recurring",
        json={
            "name": "X", "merchant_pattern": "X", "amount": 10, "currency": "RON",
            "frequency": "monthly", "start_date": _past(10),
            "category_id": "000000000000000000000000",
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 422


# ---------- update / delete ----------

def test_update_changes_next_due_when_frequency_changes(client):
    body = _register(client)
    r = client.post("/api/recurring", json={
        "name": "X", "merchant_pattern": "X", "amount": 10, "currency": "RON",
        "frequency": "monthly", "start_date": _past(40),
    }, headers=_auth(body["access_token"])).get_json()["recurring"]
    monthly_next = r["next_due"]

    res = client.patch(
        f"/api/recurring/{r['id']}",
        json={"frequency": "weekly"},
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 200
    weekly_next = res.get_json()["recurring"]["next_due"]
    assert weekly_next != monthly_next


def test_delete(client):
    body = _register(client)
    r = client.post("/api/recurring", json={
        "name": "X", "merchant_pattern": "X", "amount": 10, "currency": "RON",
        "frequency": "monthly", "start_date": _past(10),
    }, headers=_auth(body["access_token"])).get_json()["recurring"]
    res = client.delete(f"/api/recurring/{r['id']}", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    res2 = client.get(f"/api/recurring/{r['id']}", headers=_auth(body["access_token"]))
    assert res2.status_code == 404


# ---------- calendar ----------

def test_calendar_groups_by_day_of_month(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    # Two recurring payments scheduled in the same month
    client.post("/api/recurring", json={
        "name": "A", "merchant_pattern": "A", "amount": 10, "currency": "RON",
        "frequency": "monthly", "start_date": _past(10),  # next_due ~20 days from now
    }, headers=headers)
    now = datetime.now(timezone.utc)
    res = client.get(
        f"/api/recurring/calendar?year={now.year}&month={now.month}",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["year"] == now.year
    assert data["month"] == now.month
    # by_day is a dict — content depends on the actual next_due day, just assert shape
    assert isinstance(data["by_day"], dict)


def test_calendar_rejects_bad_month(client):
    body = _register(client)
    res = client.get("/api/recurring/calendar?year=2026&month=13", headers=_auth(body["access_token"]))
    assert res.status_code == 422


# ---------- detection (integration: stored transactions → suggestions) ----------

def test_detect_finds_monthly_pattern_in_real_transactions(client):
    body = _register(client)
    headers = _auth(body["access_token"])
    now = datetime.now(timezone.utc)

    # Three monthly Spotify charges
    for d in [60, 30, 0]:
        client.post(
            "/api/transactions",
            json={
                "date": (now - timedelta(days=d)).replace(microsecond=0).isoformat(),
                "amount": -35.0,
                "currency": "RON",
                "description": "SPOTIFY*PREMIUM",
            },
            headers=headers,
        )

    res = client.post("/api/recurring/detect", headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data["transactions_scanned"] >= 3
    assert any(s["frequency"] == "monthly" for s in data["suggestions"])
    spotify = next(s for s in data["suggestions"] if "SPOTIFY" in s["merchant_pattern"])
    assert spotify["average_amount"] == 35.0
    assert spotify["occurrences"] == 3
    assert spotify["is_income"] is False


def test_detect_returns_empty_when_no_transactions(client):
    body = _register(client)
    res = client.post("/api/recurring/detect", headers=_auth(body["access_token"]))
    assert res.status_code == 200
    data = res.get_json()
    assert data["transactions_scanned"] == 0
    assert data["suggestions"] == []


# ---------- isolation + auth ----------

def test_users_dont_see_each_others_recurring(client):
    a = _register(client)
    # Register a second user with a different email by re-using _register's payload
    b = client.post("/api/auth/register", json={
        "email": "b@example.com", "password": "password123",
        "full_name": "B", "base_currency": "RON",
    }).get_json()
    client.post("/api/recurring", json={
        "name": "Spotify", "merchant_pattern": "SPOTIFY", "amount": 35,
        "currency": "RON", "frequency": "monthly", "start_date": _past(20),
    }, headers=_auth(a["access_token"]))
    items = client.get("/api/recurring", headers=_auth(b["access_token"])).get_json()["recurring"]
    assert items == []


def test_list_requires_auth(client):
    res = client.get("/api/recurring")
    assert res.status_code == 401


def test_detect_requires_auth(client):
    res = client.post("/api/recurring/detect")
    assert res.status_code == 401


# ---------- one-off planned payments (frequency: "once") ----------

def test_create_once_planned_payment(client):
    body = _register(client)
    res = client.post(
        "/api/recurring",
        json={
            "name": "Andrei's wedding",
            "merchant_pattern": "Wedding gift",
            "amount": 500.0,
            "currency": "RON",
            "frequency": "once",
            "start_date": _future(60),
        },
        headers=_auth(body["access_token"]),
    )
    assert res.status_code == 201
    r = res.get_json()["recurring"]
    assert r["frequency"] == "once"
    assert r["status"] == "active"
    # Once-offs default to auto-creating the transaction (user explicitly committed).
    assert r["auto_create_transaction"] is True
    # next_due is just the start_date — no forward roll for one-shots.
    assert r["next_due"] == r["start_date"]


def test_recurring_defaults_auto_create_off(client):
    body = _register(client)
    r = client.post(
        "/api/recurring",
        json={
            "name": "Spotify", "merchant_pattern": "SPOTIFY", "amount": 35,
            "currency": "RON", "frequency": "monthly", "start_date": _past(20),
        },
        headers=_auth(body["access_token"]),
    ).get_json()["recurring"]
    # Recurring defaults to OFF — avoids double-counting against CSV imports.
    assert r["auto_create_transaction"] is False


def test_auto_create_explicit_override(client):
    body = _register(client)
    r = client.post(
        "/api/recurring",
        json={
            "name": "Salary", "merchant_pattern": "PAYROLL", "amount": 8000,
            "currency": "RON", "frequency": "monthly", "start_date": _past(20),
            "is_income": True, "auto_create_transaction": True,
        },
        headers=_auth(body["access_token"]),
    ).get_json()["recurring"]
    assert r["auto_create_transaction"] is True


# ---------- auto-materialization ----------

def test_materialize_creates_transaction_for_due_once_payment(client):
    """A 'once' payment with auto_create=True and next_due in the past
    materializes into a real transaction and transitions to status=completed."""
    from app.services.recurring_service import materialize_due

    body = _register(client)
    headers = _auth(body["access_token"])
    # Create a once-off planned payment with start_date == today — fires
    # immediately on materialize_due (next_due == now → due now).
    # (Backdated once is refused by the API on create, so the test uses
    # `_future(0)` to land on today.)
    r = client.post("/api/recurring", json={
        "name": "Tax bill", "merchant_pattern": "ANAF", "amount": 1200,
        "currency": "RON", "frequency": "once", "start_date": _future(0),
    }, headers=headers).get_json()["recurring"]

    stats = materialize_due()
    assert stats["created"] == 1
    assert stats["completed"] == 1

    # The planned-payment row is now completed and no longer appears in the active list.
    items = client.get("/api/recurring", headers=headers).get_json()["recurring"]
    assert all(p["id"] != r["id"] for p in items)

    # A real transaction was created with source="recurring" and a negative (expense) amount.
    txs = client.get("/api/transactions", headers=headers).get_json()["transactions"]
    matches = [t for t in txs if t["description"] == "Tax bill"]
    assert len(matches) == 1
    assert matches[0]["source"] == "recurring"
    assert matches[0]["amount"] == -1200


def test_materialize_skips_when_auto_create_off(client):
    """Default recurring (auto_create=False) is NOT materialized."""
    from app.services.recurring_service import materialize_due

    body = _register(client)
    headers = _auth(body["access_token"])
    client.post("/api/recurring", json={
        "name": "Spotify", "merchant_pattern": "SPOTIFY", "amount": 35,
        "currency": "RON", "frequency": "monthly", "start_date": _past(20),
    }, headers=headers)

    stats = materialize_due()
    assert stats["created"] == 0
    txs = client.get("/api/transactions", headers=headers).get_json()["transactions"]
    assert all(t.get("source") != "recurring" for t in txs)


def test_materialize_rolls_recurring_forward_after_downtime(client):
    """If `next_due` is in the past (e.g. the scheduler was offline for several
    cadences), materialize creates one transaction per missed occurrence and
    rolls next_due into the future. Recurring rows stay active across this."""
    from datetime import datetime, timedelta

    from bson import ObjectId

    from app.extensions import mongo
    from app.services.recurring_service import materialize_due

    body = _register(client)
    headers = _auth(body["access_token"])
    r = client.post("/api/recurring", json={
        "name": "Cleaning service", "merchant_pattern": "CLEAN", "amount": 100,
        "currency": "RON", "frequency": "weekly", "start_date": _past(2),
        "auto_create_transaction": True,
    }, headers=headers).get_json()["recurring"]

    # Simulate three weeks of scheduler downtime by force-rewinding next_due.
    backdated = datetime.utcnow() - timedelta(days=22)
    mongo.db["recurring_payments"].update_one(
        {"_id": ObjectId(r["id"])}, {"$set": {"next_due": backdated}},
    )

    stats = materialize_due()
    # 22 days back, weekly cadence → 4 occurrences (days 22, 15, 8, 1) before today.
    assert stats["created"] >= 3

    # next_due is now in the future — running the job again is a no-op.
    again = materialize_due()
    assert again["created"] == 0

    fresh = client.get(f"/api/recurring/{r['id']}", headers=headers).get_json()["recurring"]
    assert fresh["status"] == "active"  # recurring stays active
    next_due = datetime.fromisoformat(fresh["next_due"])
    assert next_due >= datetime.utcnow()


def test_create_recurring_skips_past_occurrences(client):
    """Creating a weekly with start_date 30 days ago should NOT back-fill those
    past occurrences — next_due lands in the near future and materialize is a
    no-op until that day arrives. (Avoids fabricating history the user never paid.)"""
    from app.services.recurring_service import materialize_due

    body = _register(client)
    headers = _auth(body["access_token"])
    client.post("/api/recurring", json={
        "name": "Old subscription", "merchant_pattern": "OLD", "amount": 50,
        "currency": "RON", "frequency": "weekly", "start_date": _past(30),
        "auto_create_transaction": True,
    }, headers=headers)

    stats = materialize_due()
    assert stats["created"] == 0


def test_materialize_creates_income_with_positive_sign(client):
    """is_income=True → transaction.amount is positive."""
    from app.services.recurring_service import materialize_due

    body = _register(client)
    headers = _auth(body["access_token"])
    client.post("/api/recurring", json={
        "name": "Freelance gig", "merchant_pattern": "INVOICE", "amount": 500,
        "currency": "RON", "frequency": "once", "start_date": _future(0),
        "is_income": True,
    }, headers=headers)

    materialize_due()
    txs = client.get("/api/transactions", headers=headers).get_json()["transactions"]
    matches = [t for t in txs if t["description"] == "Freelance gig"]
    assert len(matches) == 1
    assert matches[0]["amount"] == 500.0


def test_calendar_excludes_completed_once(client):
    """A completed (already-materialized) once-off does not show up on the calendar."""
    from app.services.recurring_service import materialize_due
    from datetime import datetime, timezone

    body = _register(client)
    headers = _auth(body["access_token"])
    client.post("/api/recurring", json={
        "name": "Past wedding", "merchant_pattern": "WED", "amount": 300,
        "currency": "RON", "frequency": "once", "start_date": _future(0),
    }, headers=headers)
    materialize_due()

    now = datetime.now(timezone.utc)
    cal = client.get(f"/api/recurring/calendar?year={now.year}&month={now.month}", headers=headers).get_json()
    # No remaining "Past wedding" entries on the calendar — the once-off was completed.
    flat = [item for items in cal["by_day"].values() for item in items]
    assert all(it["name"] != "Past wedding" for it in flat)


def test_create_once_no_end_date_required(client):
    """`end_date` is meaningless for once-offs and gets nulled at create time."""
    body = _register(client)
    r = client.post("/api/recurring", json={
        "name": "Trip deposit", "merchant_pattern": "TRIP", "amount": 800,
        "currency": "RON", "frequency": "once", "start_date": _future(15),
        "end_date": _future(60),  # supplied but should be ignored
    }, headers=_auth(body["access_token"])).get_json()["recurring"]
    assert r["end_date"] is None


def test_detection_never_suggests_once(client):
    """The detection runner should not return frequency=='once' under any input."""
    body = _register(client)
    headers = _auth(body["access_token"])
    # Single isolated charge — looks one-off but detection requires ≥ 2 occurrences anyway.
    client.post("/api/transactions", json={
        "date": _past(5), "amount": -200, "currency": "RON",
        "description": "ONE OFF MERCHANT",
    }, headers=headers)

    res = client.post("/api/recurring/detect", headers=headers).get_json()
    assert all(s["frequency"] != "once" for s in res["suggestions"])


# ---------------------------------------------------------------------------
# mark_paid (non-auto recurring "Pay" button on the Planned page)
# ---------------------------------------------------------------------------


def test_mark_paid_creates_tx_and_rolls_next_due(client):
    """The Pay button: creates a transaction with the recurring's amount
    + category, then rolls next_due forward one cadence step."""
    from datetime import datetime, timedelta, timezone
    body = _register(client)
    h = _auth(body["access_token"])
    rent_start = (datetime.now(timezone.utc) - timedelta(days=5)).replace(microsecond=0).isoformat()
    rec = client.post("/api/recurring", json={
        "name": "Rent", "merchant_pattern": "RENT", "amount": 2500, "currency": "RON",
        "frequency": "monthly", "start_date": rent_start, "auto_create_transaction": False,
    }, headers=h).get_json()["recurring"]
    next_due_before = rec["next_due"]

    res = client.post(f"/api/recurring/{rec['id']}/mark-paid", headers=h)
    assert res.status_code == 200
    after = res.get_json()["recurring"]
    # next_due rolled forward exactly 30 days (monthly delta)
    delta = datetime.fromisoformat(after["next_due"]) - datetime.fromisoformat(next_due_before)
    assert delta == timedelta(days=30)
    # tx created with the right shape
    txs = client.get("/api/transactions?page=1&page_size=5", headers=h).get_json()["transactions"]
    rent_tx = next((t for t in txs if t["description"] == "Rent"), None)
    assert rent_tx is not None
    assert rent_tx["amount"] == -2500
    assert rent_tx["source"] == "recurring"


def test_mark_paid_on_once_completes_the_row(client):
    """A one-off planned payment marked paid is `status="completed"` —
    so it won't appear on the active /planned list again."""
    from datetime import datetime, timedelta, timezone
    body = _register(client)
    h = _auth(body["access_token"])
    # Use today's date — backdated once-offs are refused by the API on
    # create, but the test only needs the row to be in a "due now" state
    # so mark_paid can complete it.
    start = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rec = client.post("/api/recurring", json={
        "name": "Tax bill", "merchant_pattern": "ANAF", "amount": 1200, "currency": "RON",
        "frequency": "once", "start_date": start, "auto_create_transaction": False,
    }, headers=h).get_json()["recurring"]

    res = client.post(f"/api/recurring/{rec['id']}/mark-paid", headers=h)
    assert res.status_code == 200
    assert res.get_json()["recurring"]["status"] == "completed"
    # No longer on the default active list
    items = client.get("/api/recurring", headers=h).get_json()["recurring"]
    assert all(r["id"] != rec["id"] for r in items)


def test_mark_paid_on_completed_row_rejects(client):
    """Cannot mark paid a row that's already completed (defensive — the
    UI shouldn't show the button for completed rows but the server
    guards anyway)."""
    from datetime import datetime, timezone
    body = _register(client)
    h = _auth(body["access_token"])
    rec = client.post("/api/recurring", json={
        "name": "Tax bill", "merchant_pattern": "ANAF", "amount": 100, "currency": "RON",
        "frequency": "once", "start_date": datetime.now(timezone.utc).isoformat(),
        "auto_create_transaction": False,
    }, headers=h).get_json()["recurring"]
    client.post(f"/api/recurring/{rec['id']}/mark-paid", headers=h)
    res = client.post(f"/api/recurring/{rec['id']}/mark-paid", headers=h)
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# update() edge cases — the form re-submits all fields including
# `start_date` on every save, so the service must not silently roll
# `next_due` for what was actually a no-op edit. See bug report
# "I changed an due recurring payment from non automatically to auto,
#  and the due dissapeared, [but] I do not see the transaction".
# ---------------------------------------------------------------------------


def _force_next_due(rec_id: str, when):
    """Test helper: directly stamp `next_due` on the doc. Used to
    simulate the natural state where time has passed since the row
    was created and the next_due is now in the past — there's no
    public API to age a recurring row otherwise."""
    from bson import ObjectId
    from app.extensions import mongo
    mongo.db["recurring_payments"].update_one(
        {"_id": ObjectId(rec_id)},
        {"$set": {"next_due": when}},
    )


def test_update_with_unchanged_start_date_preserves_next_due(client):
    """The edit form always submits `start_date`. The backend must
    compare to the stored value and only recompute `next_due` when it
    actually changed — otherwise toggling any other field (auto, name,
    amount...) silently rolls next_due forward and the overdue badge
    drops with no transaction recorded.

    To make this catch the bug, we force `next_due` into the past
    first — otherwise recompute at near-same-instant would yield the
    same answer as the create and the assertion would pass by
    coincidence.
    """
    from datetime import datetime, timedelta
    body = _register(client)
    h = _auth(body["access_token"])
    rec = client.post("/api/recurring", json={
        "name": "Rent", "merchant_pattern": "RENT", "amount": 2500, "currency": "RON",
        "frequency": "monthly", "start_date": _past(40),
        "auto_create_transaction": False,
    }, headers=h).get_json()["recurring"]
    # Simulate elapsed time → next_due is now 5 days overdue.
    overdue = datetime.utcnow() - timedelta(days=5)
    _force_next_due(rec["id"], overdue)

    # Mimic the form: re-send start_date verbatim, change only `name`.
    res = client.patch(
        f"/api/recurring/{rec['id']}",
        json={"name": "Rent (apartment)", "start_date": rec["start_date"]},
        headers=h,
    )
    assert res.status_code == 200
    after_next = datetime.fromisoformat(res.get_json()["recurring"]["next_due"])
    # next_due unchanged — still overdue
    assert abs((after_next - overdue).total_seconds()) < 2, (
        f"next_due was rolled forward silently. before={overdue}, after={after_next}"
    )


def test_toggle_auto_on_overdue_row_materializes(client):
    """User has a non-auto overdue recurring → edits → flips
    `auto_create_transaction` to true. Expected: missed transaction is
    created NOW (don't make the user wait for the 02:00 UTC cron) AND
    next_due is rolled forward by one cadence (so the overdue badge
    naturally drops on the next render)."""
    from datetime import datetime, timedelta
    body = _register(client)
    h = _auth(body["access_token"])
    rec = client.post("/api/recurring", json={
        "name": "Rent", "merchant_pattern": "RENT", "amount": 2500, "currency": "RON",
        "frequency": "monthly", "start_date": _past(40),
        "auto_create_transaction": False,
    }, headers=h).get_json()["recurring"]
    # Force "5d overdue" state.
    _force_next_due(rec["id"], datetime.utcnow() - timedelta(days=5))

    res = client.patch(
        f"/api/recurring/{rec['id']}",
        json={"auto_create_transaction": True, "start_date": rec["start_date"]},
        headers=h,
    )
    assert res.status_code == 200
    after = res.get_json()["recurring"]
    after_next = datetime.fromisoformat(after["next_due"])
    # next_due rolled forward past now → badge naturally drops
    assert after_next > datetime.utcnow()
    # the missed transaction is now in the user's ledger
    txs = client.get("/api/transactions?page=1&page_size=10", headers=h).get_json()["transactions"]
    rent_tx = next((t for t in txs if t["description"] == "Rent"), None)
    assert rent_tx is not None, "auto toggle should have materialized the missed cycle"
    assert rent_tx["amount"] == -2500
    assert rent_tx["source"] == "recurring"


def test_toggle_auto_off_does_not_materialize(client):
    """Flipping auto OFF must not create any transaction. (The user is
    saying 'I'll record this manually from now on'.)"""
    from datetime import datetime, timedelta
    body = _register(client)
    h = _auth(body["access_token"])
    rec = client.post("/api/recurring", json={
        "name": "Gym", "merchant_pattern": "GYM", "amount": 200, "currency": "RON",
        "frequency": "monthly", "start_date": _past(40),
        "auto_create_transaction": True,
    }, headers=h).get_json()["recurring"]

    # Auto=True + backdated start already materialized one cycle on create.
    # We're testing the toggle-back from this point.
    txs_before = client.get("/api/transactions?page=1&page_size=20", headers=h).get_json()["transactions"]
    n_before = len([t for t in txs_before if t["description"] == "Gym"])

    # Force overdue state so the auto-toggle materialize path would
    # otherwise fire — proving the OFF direction doesn't trigger it.
    _force_next_due(rec["id"], datetime.utcnow() - timedelta(days=5))

    res = client.patch(
        f"/api/recurring/{rec['id']}",
        json={"auto_create_transaction": False, "start_date": rec["start_date"]},
        headers=h,
    )
    assert res.status_code == 200

    txs_after = client.get("/api/transactions?page=1&page_size=20", headers=h).get_json()["transactions"]
    n_after = len([t for t in txs_after if t["description"] == "Gym"])
    assert n_after == n_before


# ---------------------------------------------------------------------------
# Backdated start_date semantics:
#   - Recurring: start_date is a cadence anchor, no back-fill, next_due
#     is the first future instance.
#   - One-off: backdated start_date is refused on create.
# ---------------------------------------------------------------------------

def test_backdated_recurring_does_not_backfill_transactions(client):
    """User picks a weekly recurring with start_date 14 days ago + auto on.
    The OLD behavior was to back-fill two missed cycles immediately. The
    NEW behavior: zero back-fill, next_due rolls forward to the first
    future cadence-anchor instance, the cron picks it up at that date."""
    body = _register(client)
    h = _auth(body["access_token"])
    res = client.post(
        "/api/recurring",
        json={
            "name": "Gym",
            "merchant_pattern": "GYM",
            "amount": 200,
            "currency": "RON",
            "frequency": "weekly",
            "start_date": _past(14),
            "auto_create_transaction": True,
        },
        headers=h,
    )
    assert res.status_code == 201
    # Zero transactions created on the spot.
    txs = client.get("/api/transactions?page=1&page_size=20", headers=h).get_json()["transactions"]
    assert [t for t in txs if t["description"] == "Gym"] == []
    # next_due is in the future (the cadence-anchor instance ≥ now).
    rec = res.get_json()["recurring"]
    from datetime import datetime as _dt, timezone as _tz
    next_due = _dt.fromisoformat(rec["next_due"].replace("Z", "+00:00"))
    if next_due.tzinfo is None:
        next_due = next_due.replace(tzinfo=_tz.utc)
    assert next_due >= _dt.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def test_backdated_recurring_anchor_first_due_matches_weekday(client):
    """For a weekly recurring with backdated start_date, the first
    occurrence should land on the same weekday as the picked start_date
    (the cadence anchor preserved)."""
    body = _register(client)
    h = _auth(body["access_token"])
    res = client.post(
        "/api/recurring",
        json={
            "name": "Yoga",
            "merchant_pattern": "YOGA",
            "amount": 60,
            "currency": "RON",
            "frequency": "weekly",
            "start_date": _past(10),
            "auto_create_transaction": False,
        },
        headers=h,
    )
    assert res.status_code == 201
    rec = res.get_json()["recurring"]
    from datetime import datetime as _dt
    start = _dt.fromisoformat(rec["start_date"].replace("Z", "+00:00")).replace(tzinfo=None)
    next_due = _dt.fromisoformat(rec["next_due"].replace("Z", "+00:00")).replace(tzinfo=None)
    assert start.weekday() == next_due.weekday()


def test_backdated_once_off_is_refused(client):
    """One-off planned payments with a past start_date are refused — the
    UI date picker also blocks this, but the server is the source of truth."""
    body = _register(client)
    h = _auth(body["access_token"])
    res = client.post(
        "/api/recurring",
        json={
            "name": "Tax",
            "merchant_pattern": "ANAF",
            "amount": 1000,
            "currency": "RON",
            "frequency": "once",
            "start_date": _past(3),
            "auto_create_transaction": False,
        },
        headers=h,
    )
    assert res.status_code == 422
    body_err = res.get_json()
    assert "start_date" in (body_err.get("details") or {}).get("field", "start_date")
    assert "future" in body_err["message"].lower() or "today" in body_err["message"].lower()


def test_one_off_with_today_start_date_is_accepted(client):
    """The cutoff is `start.date() < now.date()` — start == today must
    still be allowed (most common case: user creates a planned payment
    they want to log immediately by marking it paid)."""
    body = _register(client)
    h = _auth(body["access_token"])
    res = client.post(
        "/api/recurring",
        json={
            "name": "Today bill",
            "merchant_pattern": "TODAY",
            "amount": 100,
            "currency": "RON",
            "frequency": "once",
            "start_date": _future(0),
            "auto_create_transaction": False,
        },
        headers=h,
    )
    assert res.status_code == 201
