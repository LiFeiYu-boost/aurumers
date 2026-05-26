"""Post-processing probability calibrator.

Hermes's audit (2026-05) measured ECE 0.275 against a 0.45 average confidence —
the model is systematically over-confident and biased toward FLAT. We can't
retrain the LLM, but we can fit a lightweight per-class multiplicative scale
from recent verified predictions and apply it before the headline direction
call is taken.

Algorithm (cal-v1-global):
  predicted_rate[c] = mean(prob_c) over last N verified non-synthetic samples
  actual_rate[c]    = mean(1{actual == c}) over the same samples
  scale[c]          = clamp(actual_rate[c] / predicted_rate[c], 0.5, 2.0)

Applied as:
  cal_prob[c] = prob[c] * scale[c]  (floor 0.05, ceil 0.85, then renormalise)

Why multiplicative and not temperature/Platt: with ~60 verified rows we'd be
overfitting parameter models. A per-class scale is a 3-DOF nudge that directly
targets the diagnosed failure (class bias) and is trivially auditable. Once
the verified sample crosses ~200, swap in a richer family — the call site
only needs a new ``CalibrationResult``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from schemas import DailyPrediction, RegimeLabel, Trend


# Behaviour knobs.
DEFAULT_WINDOW = 60
MIN_SAMPLES = 20
MIN_REGIME_CLASS_SAMPLES = 10
SCALE_MIN, SCALE_MAX = 0.5, 2.0
PROB_FLOOR = 0.05
PROB_CEILING = 0.85
_DEGENERATE_PREDICTED_RATE = 0.05

CALIBRATOR_VERSION_GLOBAL = "cal-v1-global"
CALIBRATOR_VERSION_REGIME = "cal-v2-regime"
# Back-compat alias used by daily_runner before regime routing landed.
CALIBRATOR_VERSION = CALIBRATOR_VERSION_GLOBAL

# Excluded from calibration fitting: anything that wasn't a real production call.
_EXCLUDED_PROB_SOURCES = frozenset(
    {"synthetic_backtest", "synthetic_backtest_v1", "mock"}
)


@dataclass(frozen=True)
class CalibrationResult:
    scales: dict[str, float]
    status: str            # "ok" | "insufficient_data" | "disabled"
    version: str
    sample_size: int
    predicted_rate: dict[str, float]
    actual_rate: dict[str, float]
    regime: str | None = None
    per_class_source: dict[str, str] | None = None  # "regime" | "global" per class, only set for cal-v2-regime


def _eligible(predictions: Iterable[DailyPrediction]) -> list[DailyPrediction]:
    out: list[DailyPrediction] = []
    for p in predictions:
        if p.verified_correct is None:
            continue
        if p.verified_actual_direction not in (Trend.UP, Trend.DOWN, Trend.FLAT):
            continue
        if p.prob_source in _EXCLUDED_PROB_SOURCES:
            continue
        if p.prob_up_raw is not None and p.prob_down_raw is not None and p.prob_flat_raw is not None:
            # Prefer the raw triple — that's what we want to calibrate.
            out.append(p)
        elif p.prob_up is not None and p.prob_down is not None and p.prob_flat is not None:
            # Backfill for rows written before the _raw columns existed.
            out.append(p)
    return out


def _pick_triple(p: DailyPrediction) -> tuple[float, float, float]:
    if p.prob_up_raw is not None and p.prob_down_raw is not None and p.prob_flat_raw is not None:
        return p.prob_up_raw, p.prob_down_raw, p.prob_flat_raw
    return float(p.prob_up or 0.0), float(p.prob_down or 0.0), float(p.prob_flat or 0.0)


def _disabled_result(reason: str, sample_size: int = 0) -> CalibrationResult:
    return CalibrationResult(
        scales={"up": 1.0, "down": 1.0, "flat": 1.0},
        status=reason,
        version=CALIBRATOR_VERSION_GLOBAL,
        sample_size=sample_size,
        predicted_rate={"up": 0.0, "down": 0.0, "flat": 0.0},
        actual_rate={"up": 0.0, "down": 0.0, "flat": 0.0},
    )


def _fit_rates(sample: list[DailyPrediction]) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Compute predicted_rate, actual_rate, and per-class actual counts for a sample."""
    n = len(sample)
    pred_sum = {"up": 0.0, "down": 0.0, "flat": 0.0}
    act_count = {"up": 0, "down": 0, "flat": 0}
    for p in sample:
        up, down, flat = _pick_triple(p)
        pred_sum["up"] += up
        pred_sum["down"] += down
        pred_sum["flat"] += flat
        if p.verified_actual_direction == Trend.UP:
            act_count["up"] += 1
        elif p.verified_actual_direction == Trend.DOWN:
            act_count["down"] += 1
        elif p.verified_actual_direction == Trend.FLAT:
            act_count["flat"] += 1
    predicted_rate = {k: (v / n if n else 0.0) for k, v in pred_sum.items()}
    actual_rate = {k: (v / n if n else 0.0) for k, v in act_count.items()}
    return predicted_rate, actual_rate, act_count


def _scale_for(predicted_rate: float, actual_rate: float) -> float | None:
    """Return clamped scale or None if predicted_rate is degenerate."""
    if predicted_rate < _DEGENERATE_PREDICTED_RATE:
        return None
    raw_scale = actual_rate / predicted_rate
    return round(max(SCALE_MIN, min(SCALE_MAX, raw_scale)), 4)


def fit_calibrator(
    predictions: Iterable[DailyPrediction],
    *,
    window: int = DEFAULT_WINDOW,
    regime: RegimeLabel | None = None,
) -> CalibrationResult:
    """Fit per-class scales from the most recent ``window`` eligible predictions.

    ``predictions`` is taken in any order; this routine selects up to ``window``
    most recent eligible rows by ``prediction_date`` descending.

    When ``regime`` is provided and ≥ ``MIN_REGIME_CLASS_SAMPLES`` rows in that
    regime have a verified outcome of class c, use the regime-conditioned scale
    for c. Otherwise fall back to that class's global scale. The mix is recorded
    in ``per_class_source``.
    """
    pool = sorted(_eligible(predictions), key=lambda p: p.prediction_date, reverse=True)
    sample = pool[:window]
    n = len(sample)
    if n < MIN_SAMPLES:
        return _disabled_result("insufficient_data", n)

    global_predicted_rate, global_actual_rate, _ = _fit_rates(sample)
    global_scales: dict[str, float] = {}
    for cls in ("up", "down", "flat"):
        s = _scale_for(global_predicted_rate[cls], global_actual_rate[cls])
        global_scales[cls] = 1.0 if s is None else s

    if regime is None or regime is RegimeLabel.UNKNOWN:
        return CalibrationResult(
            scales=global_scales,
            status="ok",
            version=CALIBRATOR_VERSION_GLOBAL,
            sample_size=n,
            predicted_rate={k: round(v, 4) for k, v in global_predicted_rate.items()},
            actual_rate={k: round(v, 4) for k, v in global_actual_rate.items()},
        )

    regime_sample = [p for p in sample if p.regime_label == regime]
    if not regime_sample:
        # No regime-tagged rows yet — return global with regime annotated.
        return CalibrationResult(
            scales=global_scales,
            status="ok",
            version=CALIBRATOR_VERSION_REGIME,
            sample_size=n,
            predicted_rate={k: round(v, 4) for k, v in global_predicted_rate.items()},
            actual_rate={k: round(v, 4) for k, v in global_actual_rate.items()},
            regime=regime.value,
            per_class_source={cls: "global" for cls in ("up", "down", "flat")},
        )

    regime_predicted_rate, regime_actual_rate, regime_actual_count = _fit_rates(regime_sample)

    mixed_scales: dict[str, float] = {}
    per_class_source: dict[str, str] = {}
    for cls in ("up", "down", "flat"):
        if regime_actual_count[cls] >= MIN_REGIME_CLASS_SAMPLES:
            s = _scale_for(regime_predicted_rate[cls], regime_actual_rate[cls])
            if s is not None:
                mixed_scales[cls] = s
                per_class_source[cls] = "regime"
                continue
        mixed_scales[cls] = global_scales[cls]
        per_class_source[cls] = "global"

    return CalibrationResult(
        scales=mixed_scales,
        status="ok",
        version=CALIBRATOR_VERSION_REGIME,
        sample_size=len(regime_sample),
        predicted_rate={k: round(v, 4) for k, v in regime_predicted_rate.items()},
        actual_rate={k: round(v, 4) for k, v in regime_actual_rate.items()},
        regime=regime.value,
        per_class_source=per_class_source,
    )


def apply_calibration(
    prob_up: float,
    prob_down: float,
    prob_flat: float,
    scales: dict[str, float],
) -> tuple[float, float, float]:
    """Multiply each prob by its scale, clamp to [floor, ceiling], renormalise.

    Returns the calibrated triple summing to 1.0 (modulo float rounding).
    """
    raw = {
        "up": prob_up * scales.get("up", 1.0),
        "down": prob_down * scales.get("down", 1.0),
        "flat": prob_flat * scales.get("flat", 1.0),
    }
    clamped = {k: max(PROB_FLOOR, min(PROB_CEILING, v)) for k, v in raw.items()}
    total = sum(clamped.values())
    if total <= 0:
        # Degenerate; fall back to uniform.
        return 1 / 3, 1 / 3, 1 / 3
    return (
        clamped["up"] / total,
        clamped["down"] / total,
        clamped["flat"] / total,
    )


__all__ = (
    "CalibrationResult",
    "CALIBRATOR_VERSION",
    "CALIBRATOR_VERSION_GLOBAL",
    "CALIBRATOR_VERSION_REGIME",
    "DEFAULT_WINDOW",
    "MIN_SAMPLES",
    "MIN_REGIME_CLASS_SAMPLES",
    "SCALE_MIN",
    "SCALE_MAX",
    "PROB_FLOOR",
    "PROB_CEILING",
    "fit_calibrator",
    "apply_calibration",
)
