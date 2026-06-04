"""Rule-based natural-language explanation for a signal prediction.

Explanations are **deterministic and rule-based**, not LLM-generated. Same
feature snapshot + same label always produces the same explanation, every
time.

The engine evaluates a prioritized list of rules against the latest feature
row, but **only fires the rules whose `supports` set contains the model's
predicted label**. This prevents the contradictory "SELL — established
short-term uptrend" output the v1 engine could produce: now a SELL signal
only surfaces reasons that point downward (overbought, downtrend, weakness),
and a BUY signal only surfaces reasons that point upward. HOLD only sees
direction-agnostic observations (volume, volatility).

When no rule matches both the data AND the predicted direction, a
per-label fallback fires so the UI always has *something* readable.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Mapping

import pandas as pd

# A "rule" is (priority, condition, sentence, supports). Higher priority
# fires first within the subset matching the label. `supports` is the set
# of signal labels the sentence is relevant for — gating filter applied
# *before* the condition is evaluated.
_Rule = tuple[int, Callable[[Mapping[str, float]], bool], str, frozenset[str]]

# Signal-direction shorthands so the rule table reads cleanly.
_BUY  = frozenset({"BUY"})
_SELL = frozenset({"SELL"})
# Direction-agnostic observations (volume, volatility) — appropriate
# for any predicted direction, including HOLD.
_ANY  = frozenset({"BUY", "SELL", "HOLD"})


def _safe(value: float | None) -> float:
    """Treat NaN as 0 for rule predicates so a single missing value can't
    break the chain."""
    if value is None:
        return 0.0
    try:
        return 0.0 if value != value else float(value)  # NaN check: x != x
    except (TypeError, ValueError):
        return 0.0


_RULES: list[_Rule] = [
    # Technical terms in sentences are marked with [[TERM]] so the frontend
    # can wrap them in a glossary tooltip. The marker is plain ASCII so it
    # survives JSON transport without escaping.
    #
    # Each rule is tagged with the signal label(s) it can justify. A SELL
    # rule never fires for a BUY signal, so the user never sees the v1
    # contradiction "SELL — established uptrend".

    # --- Strong reversal patterns (highest priority) ----------------------
    (100,
     lambda r: _safe(r.get("rsi_14")) < 30 and _safe(r.get("macd_hist")) > 0,
     "[[RSI]] is [[oversold]] (under 30) and [[MACD]] histogram has turned positive — a possible upside reversal.",
     _BUY),
    (100,
     lambda r: _safe(r.get("rsi_14")) > 70 and _safe(r.get("macd_hist")) < 0,
     "[[RSI]] is [[overbought]] (over 70) and [[MACD]] histogram has turned negative — a possible downside reversal.",
     _SELL),

    # --- Bollinger band extremes ------------------------------------------
    # Above upper band → mean-reversion read favors SELL.
    # Below lower band → mean-reversion read favors BUY.
    (90,
     lambda r: _safe(r.get("bb_pctb_20")) > 1.0,
     "Price is above the upper [[Bollinger band]] — extended above its recent range.",
     _SELL),
    (90,
     lambda r: _safe(r.get("bb_pctb_20")) < 0.0,
     "Price is below the lower [[Bollinger band]] — extended below its recent range.",
     _BUY),

    # --- Strong recent momentum -------------------------------------------
    # Large 21-day moves: the dominant read is continuation, so tagged with
    # the same-direction signal. If the model picks the *opposite* of the
    # move, the per-label fallback surfaces "model leans … despite recent
    # move" rather than a misleading continuation phrase.
    (80,
     lambda r: _safe(r.get("ret_21d")) > 0.10,
     "Strong recent [[momentum]] — price is up over 10% in the last 21 trading days.",
     _BUY),
    (80,
     lambda r: _safe(r.get("ret_21d")) < -0.10,
     "Pronounced recent weakness — price is down over 10% in the last 21 trading days.",
     _SELL),

    # --- Trend regime via long EMA ----------------------------------------
    # Above/below EMA50 by 5%+ is the classic trend marker — clearly
    # directional, so tagged with the matching signal only.
    (70,
     lambda r: _safe(r.get("ema_50_ratio")) > 0.05,
     "Trading above the 50-day [[EMA]] by 5%+ — established short-term uptrend.",
     _BUY),
    (70,
     lambda r: _safe(r.get("ema_50_ratio")) < -0.05,
     "Trading below the 50-day [[EMA]] by 5%+ — established short-term downtrend.",
     _SELL),

    # --- Volume signals ---------------------------------------------------
    # Direction-agnostic. A volume spike is "unusual interest" regardless
    # of which way the model is leaning — useful context for any signal.
    (60,
     lambda r: _safe(r.get("volume_z_21")) > 2.0,
     "Recent volume spike (over 2 standard deviations above the 21-day mean) — unusual interest.",
     _ANY),

    # --- Volatility regime ------------------------------------------------
    # Direction-agnostic. High ATR tells the user the move (whichever way)
    # may be wider than usual, relevant for sizing on any signal.
    (50,
     lambda r: _safe(r.get("atr_14_pct")) > 0.04,
     "Above-average recent volatility ([[ATR]] over 4% of price).",
     _ANY),

    # --- Mild momentum (lowest priority — fallback when nothing else fires) -
    (10,
     lambda r: _safe(r.get("ret_21d")) > 0.02,
     "Mild positive trend over the last 21 days.",
     _BUY),
    (10,
     lambda r: _safe(r.get("ret_21d")) < -0.02,
     "Mild negative trend over the last 21 days.",
     _SELL),
]

# Sort once at import so `explain` doesn't re-sort on every call.
_RULES.sort(key=lambda r: -r[0])


# Per-label fallback when no rule fires for that signal direction.
# Kept neutral: doesn't claim more than "the model leans this way" since
# by definition we have no specific rule to point at.
_FALLBACK: dict[str, str] = {
    "BUY":  "The model leans bullish based on the latest features, though no single indicator dominates.",
    "SELL": "The model leans bearish based on the latest features, though no single indicator dominates.",
    "HOLD": "Indicators are mixed; no single factor stands out in the latest bar.",
}


def explain(
    features: Mapping[str, float],
    label: str = "HOLD",
    *,
    max_sentences: int = 2,
) -> str:
    """Return a 1-2 sentence explanation for the latest feature snapshot,
    aligned with the model's predicted `label` (BUY / HOLD / SELL).

    Only rules whose `supports` set contains the label can fire — this is
    what prevents the v1 bug where a SELL signal could surface "established
    uptrend" reasoning. If no rule both fires and matches, falls back to
    the per-label neutral message in `_FALLBACK`.
    """
    fired: list[str] = []
    for _priority, cond, sentence, supports in _RULES:
        if label not in supports:
            continue
        try:
            if cond(features):
                fired.append(sentence)
                if len(fired) >= max_sentences:
                    break
        except Exception:  # noqa: BLE001 — a malformed feature row mustn't break the API
            continue

    if fired:
        return " ".join(fired)
    return _FALLBACK.get(label, _FALLBACK["HOLD"])


def explain_row(
    row: pd.Series,
    label: str = "HOLD",
    *,
    max_sentences: int = 2,
) -> str:
    """Convenience wrapper for the common case where the caller has a
    pandas Series (one row of the feature frame)."""
    return explain(row.to_dict(), label, max_sentences=max_sentences)
