"""Recurring-payment auto-detection (plan §C.3).

Pure algorithm — no Mongo, no Flask. Takes a list of transactions, returns a
list of `DetectionSuggestion`s. The caller (`recurring_service.detect`) is
responsible for fetching the user's transactions and persisting confirmed
suggestions.

Algorithm:
  1. Cluster transactions by approximate merchant name using `Levenshtein.ratio`
     (≥ `MERCHANT_SIMILARITY` → same cluster).
  2. For each cluster with at least `MIN_OCCURRENCES` items:
     a. Reject if amount variation > `AMOUNT_TOLERANCE` of the mean.
     b. Compute consecutive-date intervals; reject if irregular
        (std-dev > `INTERVAL_REGULARITY` of the mean).
     c. Map the mean interval to one of the known cadences
        (weekly / biweekly / monthly / yearly); reject if it doesn't match.
  3. Return a `DetectionSuggestion` per surviving cluster.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, pstdev
from typing import Iterable, Optional

import Levenshtein

from app.models.recurring import DetectionResult, DetectionSuggestion, Frequency

# Tunable thresholds. Documented + unit-tested so tweaking them is conscious.
MERCHANT_SIMILARITY = 0.82      # Levenshtein.ratio() above this → same merchant
# `AMOUNT_TOLERANCE = 0.20` (20 %) is calibrated to accept *both* fixed
# subscriptions (Netflix RON 49.99 every month — variance ≈ 0 %) and
# variable-but-repeating real-life patterns (Burger King ≈ RON 50, ± a few
# lei per visit). The previous 5 % rejected anything that wasn't a credit-
# card-billed subscription, which is what the user (correctly) complained
# about. We still cap at 20 % so a one-off RON 500 doesn't get clustered
# with three RON 50 hits.
AMOUNT_TOLERANCE = 0.20
INTERVAL_REGULARITY = 0.30      # std-dev / mean of intervals must be ≤ 30 %
MIN_OCCURRENCES = 2             # need at least 2 hits to call a pattern recurring

# Cadence map: mean interval (days) → frequency label, with tolerance windows.
# (mean_days, label, lower_bound_days, upper_bound_days)
_CADENCES: list[tuple[int, Frequency, int, int]] = [
    (7,   "weekly",   5,   10),
    (14,  "biweekly", 11,  18),
    (30,  "monthly",  25,  35),
    (365, "yearly",   330, 400),
]


@dataclass
class TxRow:
    """Minimal shape the detection function needs from a transaction."""
    description: str
    amount: float           # signed: negative = expense, positive = income
    currency: str
    date: datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NORMALIZE_RE = re.compile(r"[^a-z0-9 ]+")


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Used for comparison only."""
    return _NORMALIZE_RE.sub(" ", s.lower()).strip()


def _classify_interval(days: float) -> Optional[Frequency]:
    for _mean, label, lo, hi in _CADENCES:
        if lo <= days <= hi:
            return label
    return None


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _cluster(rows: list[TxRow]) -> list[list[TxRow]]:
    """Greedy clustering by merchant similarity.

    Each row is compared to the canonical (first) row of each existing cluster;
    if `Levenshtein.ratio` ≥ MERCHANT_SIMILARITY, it joins; otherwise a new
    cluster starts. Sorted by descending size for deterministic output.
    """
    clusters: list[list[TxRow]] = []
    for row in rows:
        norm = _normalize(row.description)
        if not norm:
            continue
        joined = False
        for cluster in clusters:
            anchor_norm = _normalize(cluster[0].description)
            if Levenshtein.ratio(norm, anchor_norm) >= MERCHANT_SIMILARITY:
                cluster.append(row)
                joined = True
                break
        if not joined:
            clusters.append([row])
    clusters.sort(key=len, reverse=True)
    return clusters


# ---------------------------------------------------------------------------
# Cluster validation
# ---------------------------------------------------------------------------

def _validate_amounts(cluster: list[TxRow]) -> bool:
    """All transactions should share the same sign AND be within tolerance."""
    abs_amounts = [abs(r.amount) for r in cluster]
    if min(abs_amounts) == 0:
        return False
    m = mean(abs_amounts)
    if m == 0:
        return False
    sd = pstdev(abs_amounts)
    return (sd / m) <= AMOUNT_TOLERANCE


def _validate_signs_match(cluster: list[TxRow]) -> bool:
    signs = {1 if r.amount >= 0 else -1 for r in cluster}
    return len(signs) == 1


def _validate_currency(cluster: list[TxRow]) -> bool:
    return len({r.currency for r in cluster}) == 1


def _validate_cadence(cluster: list[TxRow]) -> Optional[Frequency]:
    """Returns the matched frequency, or None if irregular / unmatched.

    Same-day duplicates collapse to one point before interval math. A user
    who logs four Burger King receipts on the same day shouldn't have those
    four 0-day intervals destroy the regularity check for the surrounding
    weekly cadence.
    """
    if len(cluster) < 2:
        return None
    days = sorted({r.date.date() for r in cluster})
    if len(days) < 2:
        return None
    intervals = [(days[i + 1] - days[i]).days for i in range(len(days) - 1)]
    if not intervals:
        return None
    m = mean(intervals)
    if m <= 0:
        return None
    if len(intervals) >= 2:
        sd = pstdev(intervals)
        if (sd / m) > INTERVAL_REGULARITY:
            return None
    return _classify_interval(m)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect(rows: Iterable[TxRow]) -> DetectionResult:
    rows = list(rows)
    clusters = _cluster(rows)

    suggestions: list[DetectionSuggestion] = []
    for cluster in clusters:
        if len(cluster) < MIN_OCCURRENCES:
            continue
        if not _validate_signs_match(cluster):
            continue
        if not _validate_currency(cluster):
            continue
        if not _validate_amounts(cluster):
            continue
        freq = _validate_cadence(cluster)
        if freq is None:
            continue

        avg_amount = round(mean(abs(r.amount) for r in cluster), 2)
        last_seen = max(r.date for r in cluster)
        is_income = cluster[0].amount > 0

        # Pick the most-common short token from the cluster as the pattern.
        anchor = cluster[0].description.strip()
        sample = list({r.description for r in cluster})[:5]

        suggestions.append(
            DetectionSuggestion(
                merchant_pattern=anchor,
                average_amount=avg_amount,
                currency=cluster[0].currency,  # type: ignore[arg-type]
                frequency=freq,
                occurrences=len(cluster),
                last_seen=last_seen,
                is_income=is_income,
                sample_descriptions=sample,
            )
        )

    return DetectionResult(
        suggestions=suggestions,
        transactions_scanned=len(rows),
        clusters_found=len(clusters),
    )
