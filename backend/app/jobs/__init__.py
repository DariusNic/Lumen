"""APScheduler-driven background jobs.

The scheduler is started inside `create_app` (skipped under TESTING). Jobs are
in-process — the entire stack stays single-process.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from flask import Flask
from pytz import UTC

from app.models.user import utcnow

# Empirical APScheduler footgun: `BackgroundScheduler(timezone="UTC")` is
# only the scheduler's *default* tz. A `CronTrigger(hour=H, minute=M)`
# constructed without an explicit `timezone=` kwarg snapshots the local
# machine tz via `tzlocal.get_localzone()` at construction time, BEFORE
# the scheduler attaches. Result: cron fires in the host's local tz, not
# UTC. Bug confirmed in dev — stock-data refresh fired at 21:00 Bucharest
# (= 18:00 UTC, during US trading hours, partial intraday bars persisted)
# instead of 21:00 UTC. Every trigger below passes `timezone=UTC`.
_UTC = UTC

log = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _materialize_planned_payments(app: Flask) -> None:
    """Daily job: turn due planned payments into real transactions."""
    from app.services.recurring_service import materialize_due
    with app.app_context():
        try:
            stats = materialize_due()
            if stats["created"] > 0:
                log.info(
                    "materialize_planned_payments: %s tx created (%s rolled, %s completed)",
                    stats["created"], stats["rolled"], stats["completed"],
                )
        except Exception:
            log.exception("materialize_planned_payments failed")


def _refresh_fx_rates(app: Flask) -> None:
    """Daily job: pull today's ECB rates from Frankfurter and cache them.

    ECB publishes around 16:00 CET on weekdays. We schedule for 17:00 UTC so
    we're definitely past the publish on a typical day, and we tolerate misses
    (next-day fetch via `_ensure_rates_for` still works, with the 7-day window
    keeping yesterday's row valid).
    """
    from app.services.fx_service import refresh_today
    with app.app_context():
        try:
            doc = refresh_today()
            log.info("refresh_fx_rates: cached %s for %s", list(doc["rates"].keys()), doc["date"].date())
        except Exception:
            log.exception("refresh_fx_rates failed")


def _snapshot_networth(app: Flask) -> None:
    """Daily job: walk every user, take today's net worth snapshot.

    Runs at 02:30 UTC — 30 minutes after `materialize_planned_payments`
    so today's auto-logged transactions are reflected in the snapshot.
    """
    from app.services.networth_service import snapshot_all_users
    with app.app_context():
        try:
            stats = snapshot_all_users()
            log.info(
                "snapshot_networth: %s/%s users (%s failed)",
                stats["ok"], stats["users_total"], stats["failed"],
            )
        except Exception:
            log.exception("snapshot_networth failed")


def _retrain_categorizer(app: Flask) -> None:
    """Daily job: re-train the TF-IDF + LogReg categorizer with the latest
    user corrections folded into the seed corpus, then invalidate the
    in-process model cache so the next `categorize()` call picks up the
    new joblib.

    Skip-condition: no `corrections` rows newer than the existing model's
    `trained_at` timestamp. Re-training the same data daily produces the
    same artifact (deterministic with `random_state`) and burns CPU for
    nothing.

    Runs at 03:00 UTC — quiet window between `snapshot_networth` (02:30)
    and the FX refresh (17:00).
    """
    from datetime import datetime as _dt
    from app.ml.categorization import predict as _predict
    from app.ml.categorization import train_tfidf_lr
    from app.extensions import mongo

    with app.app_context():
        # Cheap pre-check: is there anything new to learn from?
        cutoff = None
        if train_tfidf_lr.METRICS_PATH.exists():
            try:
                import json as _json
                with train_tfidf_lr.METRICS_PATH.open(encoding="utf-8") as f:
                    existing = _json.load(f)
                trained_at = existing.get("trained_at")
                if trained_at:
                    cutoff = _dt.fromisoformat(trained_at)
            except Exception:  # noqa: BLE001 — corrupt metrics shouldn't block retrain
                cutoff = None
        if cutoff is not None:
            fresh = mongo.db["corrections"].count_documents({"created_at": {"$gt": cutoff}})
            if fresh == 0:
                log.info("retrain_categorizer: no new corrections since %s — skip", cutoff)
                return

        try:
            metrics = train_tfidf_lr.train_and_evaluate(include_corrections=True)
        except Exception:
            log.exception("retrain_categorizer: train_and_evaluate failed")
            return

        # Force the next `categorize()` call to re-read the joblib instead
        # of serving from the cached pipeline that was in memory when we
        # entered this function.
        _predict.reset_model_cache()
        log.info(
            "retrain_categorizer: %s rows (%s seed + %s corrections), "
            "accuracy=%.4f macro_f1=%.4f",
            metrics["corpus"]["rows_total"],
            metrics["corpus"]["rows_seed"],
            metrics["corpus"]["rows_corrections"],
            metrics["metrics"]["accuracy"],
            metrics["metrics"]["macro_f1"],
        )


def _refresh_stock_data(app: Flask) -> None:
    """Daily job: pull yesterday's bars for every tracked ticker via yfinance
    and upsert into `stock_data`. Then write the day's predictions to
    `ml_predictions` so `GET /api/stocks/signals` can serve from cache
    instead of recomputing 100 tickers on every request (Q-PERF-1).

    Scheduled for 21:30 UTC — 30 minutes past the US close (20:00 UTC in
    EDT, 21:00 UTC in EST) so yfinance has a chance to publish settled
    bars. In summer (EDT) that's 00:30 EEST in Romania; in winter (EST)
    that's 23:30 EET. yfinance's `period='5d'` window covers any
    back-revised bars from earlier in the week.
    """
    from app.services.stock_data_service import refresh_latest
    with app.app_context():
        try:
            stats = refresh_latest()
            log.info(
                "refresh_stock_data: %s/%s tickers ok, %s rows written",
                stats["tickers_ok"], stats["tickers_total"], stats["rows_written"],
            )
        except Exception:
            log.exception("refresh_stock_data failed")

        # Write today's predictions to the cache. Independent of the bar
        # refresh: if yfinance failed we'd still want yesterday's cache to
        # be refreshed against the latest data we already have.
        try:
            from app.ml.signals import predict as signals_predict
            from app.services import predictions_cache
            from app.utils.constants import TICKERS

            sigs = signals_predict.predict_signals_batch(list(TICKERS))
            n = predictions_cache.upsert_batch(sigs)
            log.info("refresh_stock_data: cached %s predictions in ml_predictions", n)
        except Exception:
            log.exception("predictions_cache refresh failed")


def init_scheduler(app: Flask) -> Optional[BackgroundScheduler]:
    """Start a BackgroundScheduler bound to this Flask app.

    Skips entirely under TESTING (mongomock + ephemeral apps don't want a
    long-running thread). Skips also when `DISABLE_SCHEDULER=1` is set so the
    user can run `flask run` without background activity during dev iteration.
    """
    global _scheduler
    if app.config.get("TESTING"):
        return None
    if os.getenv("DISABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        log.info("Scheduler disabled via DISABLE_SCHEDULER=1")
        return None
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone="UTC", daemon=True)
    # `misfire_grace_time=24h` on every once-daily cron covers the case where
    # the scheduler is *running* but the worker thread is too busy/blocked to
    # execute at the scheduled instant — it gives APScheduler a window to
    # still fire the job. It does NOT recover firings the scheduler was
    # entirely offline for: `CronTrigger.next_run_time` is computed forward
    # from `add_job()` time, so a server that was off when yesterday's 21:30
    # UTC cron should have run wakes up with the next firing pointed at
    # tomorrow. We handle that case separately via `_kick_off_catchups`
    # below, which inspects on-disk state at boot and schedules one-shot
    # catch-up firings if anything looks stale.
    _DAILY_GRACE = 24 * 3600

    # Materialize planned payments daily at 02:00 UTC. Far enough past midnight
    # that any timezone-shifted "today" boundaries have settled, early enough
    # that morning users see today's auto-logged transactions.
    sched.add_job(
        _materialize_planned_payments,
        trigger=CronTrigger(hour=2, minute=0, timezone=_UTC),
        args=[app],
        id="materialize_planned_payments",
        max_instances=1,
        coalesce=True,        # if the server was offline during the window, run once on resume
        misfire_grace_time=_DAILY_GRACE,
    )
    # Refresh ECB rates from Frankfurter daily at 17:00 UTC. ECB publishes
    # around 16:00 CET (15:00 UTC winter / 14:00 UTC summer); 17:00 UTC is past
    # both. Misses are recoverable — `_ensure_rates_for` retries on demand and
    # the 7-day staleness window keeps yesterday's cache valid.
    sched.add_job(
        _refresh_fx_rates,
        trigger=CronTrigger(hour=17, minute=0, timezone=_UTC),
        args=[app],
        id="refresh_fx_rates",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_DAILY_GRACE,
    )
    # Net worth snapshot daily at 02:30 UTC — 30 min after materialize so
    # today's auto-logged transactions are reflected in the snapshot.
    sched.add_job(
        _snapshot_networth,
        trigger=CronTrigger(hour=2, minute=30, timezone=_UTC),
        args=[app],
        id="snapshot_networth",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_DAILY_GRACE,
    )
    # Retrain the categorization model daily at 03:00 UTC — quiet window
    # between snapshot_networth (02:30) and refresh_fx_rates (17:00). The
    # job itself short-circuits when no new corrections exist, so daily
    # firings on idle data are cheap.
    sched.add_job(
        _retrain_categorizer,
        trigger=CronTrigger(hour=3, minute=0, timezone=_UTC),
        args=[app],
        id="retrain_categorizer",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_DAILY_GRACE,
    )
    # Stock data refresh daily at 21:30 UTC — after US market close (20:00-21:00
    # UTC depending on DST) so Yahoo has the settled bar. The extra 30-min
    # margin (vs the original 21:00 UTC) covers EST winter weeks where the
    # close coincides with our cron, leaving yfinance no time to publish.
    # 21:30 UTC (not 21:00) leaves a 30-min margin past the US close so the
    # yfinance upstream has a chance to publish settled bars. During US winter
    # (EST), the close is at 21:00 UTC exactly — firing at the close lets a
    # partial last bar slip in. 21:30 covers EST + EDT without delay risk.
    sched.add_job(
        _refresh_stock_data,
        trigger=CronTrigger(hour=21, minute=30, timezone=_UTC),
        args=[app],
        id="refresh_stock_data",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=_DAILY_GRACE,
    )
    sched.start()
    _scheduler = sched
    log.info(
        "APScheduler started — materialize_planned_payments @ 02:00 UTC, "
        "snapshot_networth @ 02:30 UTC, retrain_categorizer @ 03:00 UTC, "
        "refresh_fx_rates @ 17:00 UTC, refresh_stock_data @ 21:30 UTC daily",
    )
    _kick_off_catchups(app, sched)
    return sched


def _kick_off_catchups(app: Flask, sched: BackgroundScheduler) -> None:
    """One-shot catch-ups for daily jobs the scheduler couldn't have run
    while the process was off.

    Why this exists: APScheduler computes `CronTrigger.next_run_time` forward
    from boot, so a server that's off overnight wakes with yesterday's cron
    already in the past — `misfire_grace_time` does nothing because the job
    was never scheduled to fire while we were running. Concrete symptom: the
    user starts dev server in the morning and yesterday's candle is missing
    from the chart even though yfinance has it.

    Each check inspects on-disk state to decide whether the corresponding
    cron has a missed firing to make up for. If so, we schedule a one-shot
    DateTrigger ~5 seconds out so the scheduler thread picks it up. The
    daily cron-based schedule continues unchanged after that.

    FX rates *do* have a 7-day on-demand fallback, but if the project sits
    unused longer than that, tx inserts start failing with the "FX older
    than 7 days" error. Catching up on boot keeps that from ever firing in
    practice — a stale cache repairs itself when the user opens the app.
    """
    from app.extensions import mongo

    now = utcnow()
    delay = timedelta(seconds=5)

    with app.app_context():
        # --- Stock data (user-visible: missing candles on the chart) -----
        latest_bar = mongo.db["stock_data"].find_one(sort=[("date", -1)])
        if latest_bar is not None:
            # `stock_data.date` is stored as a naive UTC datetime at
            # midnight, and `utcnow()` returns naive UTC, so we can
            # subtract directly.
            age = now - latest_bar["date"]
            if age > timedelta(hours=24):
                sched.add_job(
                    _refresh_stock_data,
                    trigger=DateTrigger(run_date=now + delay, timezone=_UTC),
                    args=[app],
                    id="refresh_stock_data_catchup",
                    max_instances=1,
                    replace_existing=True,
                )
                log.info(
                    "Catch-up: latest stock_data is %s (age %s), refresh queued",
                    latest_bar["date"].date(), age,
                )

        # --- Materialize planned payments (user-visible: auto-recurring
        # whose `next_due` has passed sits "due today" all day without
        # auto-logging a transaction) -------------------------------------
        overdue = mongo.db["recurring_payments"].find_one(
            {
                "deleted_at": None,
                "status": "active",
                "auto_create_transaction": True,
                "next_due": {"$lte": now},
            },
            projection={"_id": 1, "next_due": 1, "name": 1},
        )
        if overdue is not None:
            sched.add_job(
                _materialize_planned_payments,
                trigger=DateTrigger(run_date=now + delay, timezone=_UTC),
                args=[app],
                id="materialize_planned_payments_catchup",
                max_instances=1,
                replace_existing=True,
            )
            log.info(
                "Catch-up: auto recurring %s overdue since %s, materialize queued",
                overdue.get("name"), overdue["next_due"],
            )

        # --- FX rates (user-visible after >7 days idle: tx inserts fail
        # with the "FX older than 7 days" error from `_ensure_rates_for`) -
        latest_fx = mongo.db["fx_rates"].find_one(sort=[("date", -1)])
        if latest_fx is not None:
            age = now - latest_fx["date"]
            if age > timedelta(hours=24):
                sched.add_job(
                    _refresh_fx_rates,
                    trigger=DateTrigger(run_date=now + delay, timezone=_UTC),
                    args=[app],
                    id="refresh_fx_rates_catchup",
                    max_instances=1,
                    replace_existing=True,
                )
                log.info(
                    "Catch-up: latest fx_rates is %s (age %s), refresh queued",
                    latest_fx["date"].date(), age,
                )

        # --- Net worth snapshot (user-visible: gap in the Net worth
        # evolution chart on Reports for the missed day) ------------------
        latest_snap = mongo.db["net_worth_snapshots"].find_one(sort=[("date", -1)])
        if latest_snap is not None:
            age = now - latest_snap["date"]
            if age > timedelta(hours=24):
                sched.add_job(
                    _snapshot_networth,
                    trigger=DateTrigger(run_date=now + delay, timezone=_UTC),
                    args=[app],
                    id="snapshot_networth_catchup",
                    max_instances=1,
                    replace_existing=True,
                )
                log.info(
                    "Catch-up: latest net_worth_snapshots is %s (age %s), snapshot queued",
                    latest_snap["date"].date(), age,
                )

        # --- Categorizer retrain (user-visible: corrections the user made
        # while the server was off would only land in the model at the
        # next 03:00 UTC firing; we'd rather re-train on boot if the
        # artifact is more than ~25h old AND there are unprocessed
        # corrections waiting) ---------------------------------------------
        from app.ml.categorization import train_tfidf_lr as _trainer
        model_path = _trainer.MODEL_PATH
        if model_path.exists():
            model_mtime = datetime.fromtimestamp(model_path.stat().st_mtime)
            if (now - model_mtime) > timedelta(hours=25):
                # Trained more than a day ago — only worth re-running if
                # there's new feedback to fold in. Otherwise the artifact
                # is functionally fresh (training is deterministic).
                fresh = mongo.db["corrections"].count_documents(
                    {"created_at": {"$gt": model_mtime}}
                )
                if fresh > 0:
                    sched.add_job(
                        _retrain_categorizer,
                        trigger=DateTrigger(run_date=now + delay, timezone=_UTC),
                        args=[app],
                        id="retrain_categorizer_catchup",
                        max_instances=1,
                        replace_existing=True,
                    )
                    log.info(
                        "Catch-up: categorizer model trained %s (age %s), "
                        "%s new corrections — retrain queued",
                        model_mtime.date(), now - model_mtime, fresh,
                    )
