"""Hard-gate for the "震荡" / FLAT prediction class.

Hermes's audit (2026-05) found the system over-predicts FLAT (290 / 349 ≈ 83%
of predictions vs. 37 / 349 ≈ 11% of actual outcomes). The prompt-level
guidance was insufficient: the LLM keeps drifting toward FLAT under
uncertainty. This module enforces a post-LLM hard gate — a high prob_flat
(> 0.4) is only allowed when the technical picture actually looks quiet.

Gate conditions (all currently derived from indicators we already compute
in the daily pipeline):

* ``atr_low_pct``  — ATR(14) sits in the lower 35% of its 60-day distribution
* ``rsi_neutral``  — RSI(14) ∈ [45, 55]
* ``low_ma_dist``  — |dist-from-MA20 z-score| < 0.5

Rule: ``allow_high_flat`` is True iff at least 2 of the 3 conditions fire.
Any None input is treated as a non-firing condition (degraded data should
not let FLAT through under "we can't tell").
"""
from __future__ import annotations

from dataclasses import dataclass


_ATR_PERCENTILE_CEILING = 0.35
_RSI_NEUTRAL_LOW = 45.0
_RSI_NEUTRAL_HIGH = 55.0
_MA_DIST_ABS_CEILING = 0.5
_MIN_CONDITIONS_TO_ALLOW = 2

# The cap on prob_flat when the gate blocks it. Mass above this is redistributed
# proportionally to prob_up / prob_down by the caller in daily_runner.
FLAT_BLOCKED_CEILING = 0.4


@dataclass(frozen=True)
class FlatGateResult:
    allow_high_flat: bool
    fired: list[str]


def evaluate_flat_gate(
    atr_percentile: float | None,
    rsi: float | None,
    dist_ma20_z: float | None,
) -> FlatGateResult:
    """Return (allow_high_flat, fired_conditions).

    A condition with a None input never fires — degraded technicals must not
    silently pass the gate.
    """
    fired: list[str] = []
    if atr_percentile is not None and atr_percentile < _ATR_PERCENTILE_CEILING:
        fired.append("atr_low_pct")
    if rsi is not None and _RSI_NEUTRAL_LOW <= rsi <= _RSI_NEUTRAL_HIGH:
        fired.append("rsi_neutral")
    if dist_ma20_z is not None and abs(dist_ma20_z) < _MA_DIST_ABS_CEILING:
        fired.append("low_ma_dist")
    return FlatGateResult(
        allow_high_flat=len(fired) >= _MIN_CONDITIONS_TO_ALLOW,
        fired=fired,
    )


def enforce_flat_ceiling(
    prob_up: float,
    prob_down: float,
    prob_flat: float,
    *,
    allow_high_flat: bool,
) -> tuple[float, float, float, bool]:
    """If the gate blocks high flat and prob_flat > FLAT_BLOCKED_CEILING,
    cap flat at the ceiling and redistribute the excess to up/down by their
    current ratio. Returns (up, down, flat, was_modified).

    When up + down is zero (pathological), splits the excess evenly.
    """
    if allow_high_flat or prob_flat <= FLAT_BLOCKED_CEILING:
        return prob_up, prob_down, prob_flat, False
    excess = prob_flat - FLAT_BLOCKED_CEILING
    base = prob_up + prob_down
    if base <= 0:
        prob_up += excess / 2
        prob_down += excess / 2
    else:
        prob_up += excess * (prob_up / base)
        prob_down += excess * (prob_down / base)
    return prob_up, prob_down, FLAT_BLOCKED_CEILING, True


__all__ = (
    "FlatGateResult",
    "FLAT_BLOCKED_CEILING",
    "evaluate_flat_gate",
    "enforce_flat_ceiling",
)
