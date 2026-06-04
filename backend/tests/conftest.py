from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from app import create_app
from app.config import Config
from app.extensions import mongo
from app.models import user as user_models
from app.utils.db import ensure_indexes


class TestConfig(Config):
    TESTING = True
    MONGO_URI = "mongodb://localhost/test_finance_thesis"


@pytest.fixture
def app():
    flask_app = create_app(TestConfig)
    mongo.client = mongomock.MongoClient()
    mongo.db = mongo.client["test_finance_thesis"]
    # Mirror production: enforce the same unique compound indexes (e.g.
    # `stock_data {ticker, date}`) so insert-many idempotency tests match
    # real Atlas behavior. Mongomock supports `create_index(unique=True)`.
    ensure_indexes(mongo.db)
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


class FrozenClock:
    """Deterministic wall-clock for time-travel tests.

    Used by the `freeze_time` fixture below — every place in the app that
    calls `utcnow()` will see this clock's `.now()` instead of `datetime.now`.
    Advance with `.advance(days=N)` to simulate calendar progress; use
    `.fire_daily_jobs()` to run the materialize-recurring and snapshot-
    networth jobs in the same order the production scheduler would. Each
    call to `fire_daily_jobs` represents one simulated day's worth of
    in-process background work.

    The point: a test that needs "what happens after 30 days" doesn't have
    to wait 30 days. It calls `clock.advance(days=1); clock.fire_daily_jobs()`
    in a loop. Recurring payments materialize, net-worth snapshots
    accumulate, alerts reflect the new state — all deterministically.

    `refresh_fx_rates` and `refresh_stock_data` are intentionally NOT
    fired here — they hit external APIs (Frankfurter, yfinance) and
    tests that need them should mock the respective service functions.
    """

    def __init__(self, start: datetime):
        # Normalize to tz-aware UTC so the math is unambiguous; `utcnow`
        # will strip tzinfo before returning to callers.
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self._now = start

    def now(self) -> datetime:
        """Returns the current frozen time (tz-aware UTC)."""
        return self._now

    def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0) -> None:
        """Move the clock forward."""
        self._now = self._now + timedelta(days=days, hours=hours, minutes=minutes)

    def set(self, when: datetime) -> None:
        """Jump to a specific moment."""
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self._now = when

    def fire_daily_jobs(self) -> dict:
        """Run the in-process daily scheduled jobs in production order.
        Catches per-job exceptions so a single failure doesn't stop the
        simulation — the production scheduler has the same posture.

        Returns a summary dict keyed by job name.
        """
        from app.services.networth_service import snapshot_all_users
        from app.services.recurring_service import materialize_due

        summary: dict = {}
        try:
            summary["materialize_due"] = materialize_due()
        except Exception as exc:  # noqa: BLE001 — simulation continues
            summary["materialize_due"] = {"error": repr(exc)}
        try:
            summary["snapshot_all_users"] = snapshot_all_users()
        except Exception as exc:  # noqa: BLE001
            summary["snapshot_all_users"] = {"error": repr(exc)}
        return summary

    def simulate_days(self, n: int, *, fire_jobs: bool = True) -> list[dict]:
        """Advance `n` simulated days and (by default) fire the daily jobs
        on each day. Returns the list of per-day summaries.

        Caveat: `now()` is incremented by exactly 24h between days. If the
        test needs the jobs to fire at a specific hour-of-day, set the
        starting time before calling.
        """
        out: list[dict] = []
        for _ in range(n):
            self.advance(days=1)
            out.append(self.fire_daily_jobs() if fire_jobs else {})
        return out


@pytest.fixture(autouse=True)
def _stub_live_quote(monkeypatch):
    """Force `stock_data_service.live_quote()` to return None for the entire
    test session.

    Why: production calls `live_quote()` first inside `_last_price()` so the
    portfolio P&L can move during US trading hours before the daily cron
    writes the new close. In tests, that intraday call reaches the real
    yfinance API — which (a) makes the suite slow + flaky and (b) makes
    every test that seeds prices via `_seed_bars` get the real-world price
    instead of the seeded one. Returning None forces the fallback to
    `latest_bar()`, which reads the mongomock-seeded rows the tests expect.

    Autouse so individual tests don't have to opt in.
    """
    from app.services import stock_data_service
    monkeypatch.setattr(stock_data_service, "live_quote", lambda ticker: None)


@pytest.fixture
def freeze_time(monkeypatch):
    """Yield a `FrozenClock` that drives `app.models.user.utcnow()` for
    the duration of the test. Use it to write deterministic time-based
    tests — e.g. "after 30 simulated days, the goal is overdue".

    Default start: 2026-01-01 00:00:00 UTC. Override with `clock.set(...)`
    inside the test if a specific calendar moment matters.
    """
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))

    def _source() -> datetime:
        return clock.now()

    monkeypatch.setattr(user_models, "_now_source", _source)
    yield clock
    # monkeypatch auto-restores `_now_source` on teardown.
