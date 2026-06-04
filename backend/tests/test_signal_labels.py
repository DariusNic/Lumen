"""Label generation tests — guarantees:

1. Labels are forward-looking: row t's label depends on close[t+5], not the past.
2. The last 5 rows of every ticker have no label (future not observed).
3. Per-ticker grouping prevents cross-ticker forward-return computation
   (close[last day of ticker A] / close[first day of ticker B] - 1 must
   never produce a label).
4. The threshold mapping (±2%) is exactly as specified.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.signals.labels import (
    BUY_THRESHOLD,
    HORIZON_DAYS,
    LABEL_BUY,
    LABEL_HOLD,
    LABEL_SELL,
    LABEL_TO_INT,
    SELL_THRESHOLD,
    attach_labels,
    forward_returns,
    label_distribution,
    label_from_return,
    label_series,
)


# ---------------------------------------------------------------------------
# label_from_return — pure function, threshold edges
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ret,expected",
    [
        (0.05,  LABEL_BUY),    # +5% → BUY
        (0.021, LABEL_BUY),    # just above threshold
        (0.020, LABEL_HOLD),   # exactly at the threshold → HOLD (strict >)
        (0.019, LABEL_HOLD),
        (0.0,   LABEL_HOLD),
        (-0.019, LABEL_HOLD),
        (-0.020, LABEL_HOLD),  # exactly at the negative threshold → HOLD (strict <)
        (-0.021, LABEL_SELL),
        (-0.05, LABEL_SELL),
    ],
)
def test_label_from_return_thresholds(ret, expected):
    assert label_from_return(ret) == expected


def test_label_from_return_handles_nan():
    assert label_from_return(float("nan")) is None
    assert label_from_return(None) is None


def test_threshold_constants_are_locked():
    """If these flip, every existing model's class meanings change.
    Sign-off required before adjusting them."""
    assert BUY_THRESHOLD == 0.02
    assert SELL_THRESHOLD == -0.02
    assert HORIZON_DAYS == 5


def test_label_to_int_encoding_is_stable():
    """The numeric encoding feeds XGBoost directly — predict_proba columns
    line up with this order. Don't reshuffle."""
    assert LABEL_TO_INT == {LABEL_SELL: 0, LABEL_HOLD: 1, LABEL_BUY: 2}


# ---------------------------------------------------------------------------
# forward_returns / label_series — series-level
# ---------------------------------------------------------------------------

def test_forward_returns_aligned_to_t():
    """row t's value = close[t+5]/close[t] - 1."""
    close = pd.Series(
        [100, 101, 102, 103, 104, 110, 111],
        index=pd.date_range("2024-01-02", periods=7, freq="B"),
    )
    ret = forward_returns(close, horizon=5)
    # row 0: close[5]/close[0] - 1 = 110/100 - 1 = 0.10
    assert ret.iloc[0] == pytest.approx(0.10)
    # row 1: close[6]/close[1] - 1 = 111/101 - 1 ≈ 0.099
    assert ret.iloc[1] == pytest.approx(111 / 101 - 1)
    # last 5 rows: NaN (no future).
    assert ret.iloc[-5:].isna().all()


def test_forward_returns_rejects_unsorted():
    close = pd.Series(
        [100, 110, 105],
        index=pd.DatetimeIndex(["2024-01-04", "2024-01-02", "2024-01-03"]),
    )
    with pytest.raises(ValueError, match="ascending"):
        forward_returns(close, horizon=2)


def test_label_series_assigns_correct_labels():
    """Construct a series whose 5-day forward return is engineered: BUY,
    HOLD, SELL. Verify the correct labels come back."""
    close = pd.Series(
        [
            100, 100, 100, 100, 100,    # rows 0-4 — labels assigned from close[5..9]
            110,                         # row 5: forward = close[10]/close[5] - 1
            100, 100, 100, 100,          # rows 6-9
            100, 100, 100, 100, 100,     # rows 10-14 (provide future for rows 5-9)
        ],
        index=pd.date_range("2024-01-02", periods=15, freq="B"),
    )
    labels = label_series(close, horizon=5)
    # Row 0: 110/100 - 1 = +10% → BUY
    assert labels.iloc[0] == LABEL_BUY
    # Row 5: close[10]/close[5] - 1 = 100/110 - 1 ≈ -9% → SELL
    assert labels.iloc[5] == LABEL_SELL
    # Last 5 rows: no future, label is None.
    assert labels.iloc[-5:].isna().all() or all(labels.iloc[-5:].isnull())


# ---------------------------------------------------------------------------
# attach_labels — grouped DataFrame, the production entrypoint
# ---------------------------------------------------------------------------

def test_attach_labels_drops_last_five_per_ticker():
    """Every ticker should lose exactly 5 rows after labeling — no more, no less."""
    rows = []
    for ticker in ("AAPL", "MSFT"):
        for i in range(20):
            rows.append({"ticker": ticker, "close": 100 + i, "feat": i})
    df = pd.DataFrame(rows)

    labeled = attach_labels(df)
    # Each ticker had 20 rows → keeps 15 (last 5 dropped).
    assert (labeled["ticker"] == "AAPL").sum() == 15
    assert (labeled["ticker"] == "MSFT").sum() == 15


def test_attach_labels_does_not_mix_tickers():
    """If the function naïvely computed forward returns over the concatenated
    frame, the boundary row of ticker A would pick up ticker B's prices.
    This test rigs A and B to make that mistake produce a wrong label."""
    rows = []
    # Ticker A: stays flat at 100, then drops to 50. Forward return at the
    # last A row — if computed naïvely against B's first price (200) — would
    # fake a +300% return → BUY. The correct answer: NaN (last 5 of A
    # have no future), so they get dropped.
    a_close = [100, 100, 100, 100, 100, 100, 100, 100, 100, 50]
    b_close = [200, 200, 200, 200, 200, 200, 200, 200, 200, 200]
    for c in a_close:
        rows.append({"ticker": "A", "close": c})
    for c in b_close:
        rows.append({"ticker": "B", "close": c})
    df = pd.DataFrame(rows)

    labeled = attach_labels(df)
    # If labels respect ticker boundaries, A keeps 5 rows (10 - 5 = 5), all of
    # them with forward returns inside A only. None of them should be BUY
    # (the only direction inside A is flat → drop, nothing rises 2%).
    a_only = labeled[labeled["ticker"] == "A"]
    assert len(a_only) == 5
    assert (a_only["label"] == LABEL_BUY).sum() == 0


def test_attach_labels_empty_frame_returns_empty():
    df = pd.DataFrame(columns=["ticker", "close"])
    out = attach_labels(df)
    assert out.empty
    assert "label" in out.columns
    assert "forward_return" in out.columns


def test_label_distribution_counts_classes():
    labels = [LABEL_BUY] * 10 + [LABEL_HOLD] * 20 + [LABEL_SELL] * 5 + [None]
    dist = label_distribution(labels)
    assert dist == {LABEL_BUY: 10, LABEL_HOLD: 20, LABEL_SELL: 5}
