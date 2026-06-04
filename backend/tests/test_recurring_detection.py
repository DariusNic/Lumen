"""Pure-algorithm tests for the Levenshtein recurring-payment detector.

These test the detection function directly with handcrafted `TxRow` lists —
no Flask, no Mongo. Easy to extend when we tune thresholds.
"""
from datetime import datetime, timedelta

from app.services.recurring_detection import (
    AMOUNT_TOLERANCE,
    INTERVAL_REGULARITY,
    MERCHANT_SIMILARITY,
    MIN_OCCURRENCES,
    TxRow,
    detect,
)


def _row(desc: str, amount: float, days_ago: int, currency: str = "RON") -> TxRow:
    return TxRow(
        description=desc,
        amount=amount,
        currency=currency,
        date=datetime(2026, 5, 1) - timedelta(days=days_ago),
    )


# ---------- happy-path detections ----------

def test_three_monthly_charges_detected_as_monthly():
    rows = [
        _row("SPOTIFY*PREMIUM", -35.00, days_ago=0),
        _row("SPOTIFY*PREMIUM", -35.00, days_ago=30),
        _row("SPOTIFY*PREMIUM", -35.00, days_ago=60),
    ]
    result = detect(rows)
    assert len(result.suggestions) == 1
    s = result.suggestions[0]
    assert s.frequency == "monthly"
    assert s.average_amount == 35.00
    assert s.occurrences == 3
    assert s.is_income is False


def test_weekly_charges():
    rows = [_row("BOLT.EU/O", -22.5, days_ago=i * 7) for i in range(4)]
    result = detect(rows)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].frequency == "weekly"


def test_biweekly_charges():
    rows = [_row("PAYROLL ACME", 4000, days_ago=i * 14) for i in range(3)]
    result = detect(rows)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].frequency == "biweekly"
    assert result.suggestions[0].is_income is True


def test_yearly_subscription():
    rows = [
        _row("ANNUAL SUB", -120.0, days_ago=0),
        _row("ANNUAL SUB", -120.0, days_ago=365),
    ]
    result = detect(rows)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].frequency == "yearly"


# ---------- merchant clustering ----------

def test_levenshtein_clusters_similar_merchant_strings():
    """Whitespace + per-charge ID suffixes shouldn't break clustering —
    that's what the Levenshtein-similarity layer is for."""
    rows = [
        _row("SPOTIFY*PREMIUM P00321", -35.00, days_ago=0),
        _row("SPOTIFY*PREMIUM P00322", -35.00, days_ago=30),
        _row("SPOTIFY*PREMIUM P00323", -35.00, days_ago=60),
    ]
    result = detect(rows)
    assert len(result.suggestions) == 1
    assert result.suggestions[0].occurrences == 3


def test_levenshtein_does_not_overcluster_short_strings():
    """`SPOTIFY*PREMIUM` (15 chars) and `SPOTIFY AB` (10 chars) are too
    different (ratio ≈ 0.6) to be merged — false positives are worse than
    missed ones, so we lean strict."""
    rows = [
        _row("SPOTIFY*PREMIUM", -35.00, days_ago=0),
        _row("SPOTIFY*PREMIUM", -35.00, days_ago=30),
        _row("SPOTIFY AB",      -35.00, days_ago=60),
    ]
    result = detect(rows)
    # The "SPOTIFY*PREMIUM" cluster has 2 hits → still detected as monthly.
    # "SPOTIFY AB" lands in its own 1-element cluster → filtered out.
    assert all(s.occurrences != 3 for s in result.suggestions)


def test_distinct_merchants_dont_merge():
    rows = [
        _row("SPOTIFY*PREMIUM", -35, days_ago=0),
        _row("SPOTIFY*PREMIUM", -35, days_ago=30),
        _row("NETFLIX.COM",     -55, days_ago=2),
        _row("NETFLIX.COM",     -55, days_ago=32),
    ]
    result = detect(rows)
    names = {s.merchant_pattern.split()[0].rstrip("*") for s in result.suggestions}
    # Two distinct clusters, both detected as monthly.
    assert len(result.suggestions) == 2
    assert "SPOTIFY" in {n.rstrip("*") for n in names} or any("SPOTIFY" in s.merchant_pattern for s in result.suggestions)
    assert any("NETFLIX" in s.merchant_pattern for s in result.suggestions)


# ---------- rejection paths ----------

def test_amounts_outside_tolerance_are_rejected():
    """One-off variable spend at the same merchant should NOT be flagged."""
    rows = [
        _row("CARREFOUR BANEASA", -342.50, days_ago=0),
        _row("CARREFOUR BANEASA", -127.40, days_ago=30),
        _row("CARREFOUR BANEASA", -98.10,  days_ago=60),
    ]
    result = detect(rows)
    assert result.suggestions == []


def test_irregular_cadence_is_rejected():
    """3 charges on day 0, day 5, day 50 — too irregular to be recurring."""
    rows = [
        _row("RAND MERCHANT", -50, days_ago=0),
        _row("RAND MERCHANT", -50, days_ago=5),
        _row("RAND MERCHANT", -50, days_ago=50),
    ]
    result = detect(rows)
    assert result.suggestions == []


def test_single_transaction_not_flagged():
    rows = [_row("ONE TIME PAYMENT", -200, days_ago=10)]
    result = detect(rows)
    assert result.suggestions == []


def test_two_transactions_just_outside_cadence_window_rejected():
    """Mean interval ~22 days falls between biweekly (max 18) and monthly (min 25)."""
    rows = [
        _row("WEIRD CADENCE", -50, days_ago=0),
        _row("WEIRD CADENCE", -50, days_ago=22),
        _row("WEIRD CADENCE", -50, days_ago=44),
    ]
    result = detect(rows)
    assert result.suggestions == []


def test_signs_must_match_within_cluster():
    """Refund + charge at the same merchant shouldn't combine into a 'recurring'."""
    rows = [
        _row("MERCHANT X", -50, days_ago=0),
        _row("MERCHANT X",  50, days_ago=30),  # refund
        _row("MERCHANT X", -50, days_ago=60),
    ]
    result = detect(rows)
    assert result.suggestions == []


def test_currency_mixing_rejected():
    rows = [
        _row("INTL SERVICE", -10, days_ago=0,  currency="USD"),
        _row("INTL SERVICE", -10, days_ago=30, currency="EUR"),
        _row("INTL SERVICE", -10, days_ago=60, currency="USD"),
    ]
    result = detect(rows)
    assert result.suggestions == []


# ---------- meta ----------

def test_thresholds_documented_at_sane_values():
    """Sanity-pin the thresholds. If we tune them, we tune them deliberately."""
    assert 0.7 <= MERCHANT_SIMILARITY <= 0.95
    # 0.20 lets variable-but-recurring spend (groceries, restaurant trips,
    # rideshare) cluster as recurring. Tightening below this re-introduces
    # the bug where 3 weekly Burger King meals at RON 50/60/50 were missed.
    assert 0.0 < AMOUNT_TOLERANCE <= 0.25
    assert 0.0 < INTERVAL_REGULARITY <= 0.50
    assert MIN_OCCURRENCES >= 2


def test_empty_input_returns_empty():
    result = detect([])
    assert result.suggestions == []
    assert result.transactions_scanned == 0


def test_result_reports_scan_counts():
    rows = [_row("X", -10, days_ago=i * 30) for i in range(3)]
    result = detect(rows)
    assert result.transactions_scanned == 3
    assert result.clusters_found == 1


# ---------- relaxed-tolerance & same-day-dedup regression tests ----------

def test_weekly_meals_with_minor_amount_drift_detected():
    """Real-world repeating spend (Burger King, RON 50/60/50 across 3 weeks)
    used to be rejected under the old 5 % tolerance. The user explicitly
    reported this on the testtest account — they expected the detector to
    flag a weekly pattern even though the receipt amounts wobbled."""
    rows = [
        _row("Burger King meal", -50, days_ago=14),
        _row("Burger King meal", -60, days_ago=7),
        _row("Burger King meal", -50, days_ago=0),
    ]
    result = detect(rows)
    assert len(result.suggestions) == 1
    s = result.suggestions[0]
    assert s.frequency == "weekly"
    assert s.occurrences == 3


def test_same_day_duplicates_dont_break_weekly_cadence():
    """Four receipts on the same day shouldn't produce 0-day intervals that
    poison the regularity check for an otherwise-clean weekly cadence."""
    rows = [
        _row("Burger King meal", -50, days_ago=21),
        _row("Burger King meal", -50, days_ago=14),
        _row("Burger King meal", -50, days_ago=7),
        # Four hits on the same day — same merchant + amount.
        _row("Burger King meal", -50, days_ago=0),
        _row("Burger King meal", -50, days_ago=0),
        _row("Burger King meal", -50, days_ago=0),
        _row("Burger King meal", -50, days_ago=0),
    ]
    result = detect(rows)
    assert len(result.suggestions) == 1
    s = result.suggestions[0]
    assert s.frequency == "weekly"
    # `occurrences` counts the raw cluster size — same-day dedup only
    # affects cadence math, not the count we report back.
    assert s.occurrences == 7


def test_wildly_variable_amounts_still_rejected_under_20pct():
    """20 % is a ceiling, not a free pass — a RON 0.08 outlier alongside
    three RON 50s should still kill the cluster, otherwise we'd over-cluster
    typos and refunds."""
    rows = [
        _row("Burger King meal", -50,   days_ago=21),
        _row("Burger King meal", -50,   days_ago=14),
        _row("Burger King meal", -50,   days_ago=7),
        _row("Burger King meal", -0.08, days_ago=0),
    ]
    result = detect(rows)
    assert result.suggestions == []
