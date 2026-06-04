"""Rule-based explanation engine — deterministic by design.

Explanations must be reproducible: same feature snapshot + same label in,
same string out, every time. These tests pin the rule semantics so a later
edit to `explanations._RULES` can't silently change what the API serves.

The engine is **signal-aware**: rules only fire for the label(s) listed
in their `supports` set. So tests that exercise a directional rule must
pass the matching label; tests that exercise direction-agnostic rules
(volume, volatility) work with any label.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.ml.signals.explanations import explain, explain_row


def _features(**overrides) -> dict[str, float]:
    """Default feature snapshot — all neutral, override what each test cares about."""
    base = {
        "ret_1d": 0.0, "ret_5d": 0.0, "ret_21d": 0.0,
        "rsi_14": 50.0, "stoch_k_14": 50.0, "stoch_d_14": 50.0,
        "macd": 0.0, "macd_signal": 0.0, "macd_hist": 0.0,
        "ema_10_ratio": 0.0, "ema_21_ratio": 0.0, "ema_50_ratio": 0.0,
        "atr_14_pct": 0.02, "bb_pctb_20": 0.5, "bb_bandwidth_20": 0.05,
        "volume_z_21": 0.0, "obv_change_5": 0.0,
        "dow": 2, "month": 5,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fallback when nothing fires
# ---------------------------------------------------------------------------

def test_neutral_features_return_hold_fallback():
    """HOLD label + no rules firing → the mixed-indicators fallback."""
    text = explain(_features(), "HOLD")
    assert "mixed" in text.lower() or "no single" in text.lower()


def test_buy_fallback_when_no_buy_rule_fires():
    """BUY signal with bullish data missing → 'model leans bullish' fallback."""
    text = explain(_features(), "BUY")
    assert "bullish" in text.lower()
    assert "uptrend" not in text.lower()  # the v1 bug must not regress


def test_sell_fallback_when_no_sell_rule_fires():
    """SELL signal with bearish data missing → 'model leans bearish' fallback."""
    text = explain(_features(), "SELL")
    assert "bearish" in text.lower()


def test_explanation_is_deterministic():
    """Same features + same label → same output, every time."""
    feats = _features(rsi_14=20, macd_hist=0.5, ret_21d=0.20)
    a = explain(feats, "BUY")
    b = explain(feats, "BUY")
    c = explain(feats, "BUY")
    assert a == b == c


# ---------------------------------------------------------------------------
# Reversal patterns (highest priority)
# ---------------------------------------------------------------------------

def test_oversold_reversal_pattern_on_buy_signal():
    text = explain(_features(rsi_14=25, macd_hist=0.4), "BUY")
    assert "oversold" in text.lower()
    assert "macd" in text.lower()


def test_overbought_reversal_pattern_on_sell_signal():
    text = explain(_features(rsi_14=75, macd_hist=-0.4), "SELL")
    assert "overbought" in text.lower()


def test_reversal_beats_momentum_for_buy():
    """When both fire, the higher-priority reversal sentence comes first."""
    text = explain(
        _features(rsi_14=25, macd_hist=0.4, ret_21d=0.15),
        "BUY",
        max_sentences=2,
    )
    # "oversold" must appear before "momentum" since priority 100 > 80.
    assert text.lower().index("oversold") < text.lower().index("momentum")


# ---------------------------------------------------------------------------
# Bollinger band edges
# ---------------------------------------------------------------------------

def test_above_upper_bollinger_band_on_sell_signal():
    """Above upper band is a mean-reversion-SELL read."""
    text = explain(_features(bb_pctb_20=1.05), "SELL")
    assert "bollinger" in text.lower()
    assert "above" in text.lower()


def test_below_lower_bollinger_band_on_buy_signal():
    """Below lower band is a mean-reversion-BUY read."""
    text = explain(_features(bb_pctb_20=-0.10), "BUY")
    assert "bollinger" in text.lower()
    assert "below" in text.lower()


# ---------------------------------------------------------------------------
# Strong momentum
# ---------------------------------------------------------------------------

def test_strong_positive_momentum_on_buy():
    text = explain(_features(ret_21d=0.15), "BUY")
    assert "momentum" in text.lower() or "up over" in text.lower()


def test_strong_negative_momentum_on_sell():
    text = explain(_features(ret_21d=-0.15), "SELL")
    assert "weakness" in text.lower() or "down over" in text.lower()


# ---------------------------------------------------------------------------
# Trend regime — the regression-test cluster for the user-reported bug
# ---------------------------------------------------------------------------

def test_trading_above_50ema_on_buy():
    text = explain(_features(ema_50_ratio=0.08), "BUY")
    assert "uptrend" in text.lower() or "above" in text.lower()


def test_trading_below_50ema_on_sell():
    text = explain(_features(ema_50_ratio=-0.08), "SELL")
    assert "downtrend" in text.lower() or "below" in text.lower()


def test_sell_signal_with_uptrend_data_does_NOT_say_uptrend():
    """The user-reported bug: SELL + bullish data must not surface
    'established uptrend' reasoning. Either the SELL fallback fires
    or only direction-agnostic rules do — never the BUY-tagged uptrend."""
    text = explain(
        _features(ema_50_ratio=0.08, ret_21d=0.05),  # bullish indicators
        "SELL",
    )
    assert "uptrend" not in text.lower()
    assert "positive trend" not in text.lower()


def test_buy_signal_with_overbought_data_does_NOT_say_overbought():
    """Symmetric case: BUY + bearish indicators must not surface
    'overbought reversal' reasoning."""
    text = explain(
        _features(rsi_14=75, macd_hist=-0.4, ema_50_ratio=-0.08),
        "BUY",
    )
    assert "overbought" not in text.lower()
    assert "downtrend" not in text.lower()


# ---------------------------------------------------------------------------
# Volume / volatility — direction-agnostic, fire on any label
# ---------------------------------------------------------------------------

def test_volume_spike_fires_for_any_label():
    for label in ("BUY", "SELL", "HOLD"):
        text = explain(_features(volume_z_21=2.5), label)
        assert "volume" in text.lower(), f"volume rule missing for label={label}"


def test_high_volatility_fires_for_any_label():
    for label in ("BUY", "SELL", "HOLD"):
        text = explain(_features(atr_14_pct=0.05), label)
        assert "volatility" in text.lower(), f"volatility rule missing for label={label}"


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_handles_nan_features_gracefully():
    """A single NaN must not break the chain. _safe() coerces NaN → 0
    so any rule referencing only NaN values reads as neutral."""
    feats = _features()
    feats["rsi_14"] = float("nan")
    feats["macd_hist"] = float("nan")
    text = explain(feats, "HOLD")
    assert isinstance(text, str)
    assert len(text) > 0


def test_handles_missing_keys_gracefully():
    """An incomplete feature dict (e.g. an old serialization missing a column)
    must not raise — rules tolerate KeyError via _safe(r.get(key))."""
    text = explain({"ret_21d": 0.0}, "HOLD")
    assert isinstance(text, str)
    assert len(text) > 0


def test_max_sentences_caps_output_for_buy():
    """Even when many BUY rules fire, at most `max_sentences` are concatenated."""
    text = explain(
        _features(
            rsi_14=25, macd_hist=0.5,        # reversal (priority 100, BUY)
            bb_pctb_20=-0.10,                 # bollinger below (90, BUY)
            ret_21d=0.15,                     # momentum +10% (80, BUY)
            ema_50_ratio=0.08,                # trend above (70, BUY)
            volume_z_21=2.5,                  # volume (60, ANY)
        ),
        "BUY",
        max_sentences=2,
    )
    # Two sentences → exactly two periods (each rule sentence ends with '.').
    assert text.count(".") == 2


def test_explain_row_accepts_pandas_series():
    feats = _features(rsi_14=25, macd_hist=0.4)
    text = explain_row(pd.Series(feats), "BUY")
    assert "oversold" in text.lower()


def test_explain_row_default_label_is_hold():
    """Default label='HOLD' for backwards-compatible callers — no exception
    raised, returns the HOLD fallback when no direction-agnostic rule fires."""
    text = explain_row(pd.Series(_features()))
    assert isinstance(text, str)
    assert "mixed" in text.lower() or "no single" in text.lower()
