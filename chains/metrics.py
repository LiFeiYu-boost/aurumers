"""Phase 1 metrics — multiclass Brier, log-loss, ECE, reliability diagram.

All public functions return None on missing inputs rather than raising. The
verifier hook calls these best-effort and must not crash on malformed rows
(e.g., placeholder predictions where probs are NULL).
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Iterable

from schemas import ReliabilityBin, Trend

if TYPE_CHECKING:
    from schemas import DailyPrediction


_TREND_TO_VEC: dict[Trend, tuple[int, int, int]] = {
    Trend.UP: (1, 0, 0),
    Trend.DOWN: (0, 1, 0),
    Trend.FLAT: (0, 0, 1),
}


def _coerce_prob(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def brier_multiclass(
    prob_up: float | None,
    prob_down: float | None,
    prob_flat: float | None,
    actual: Trend | None,
) -> float | None:
    """Sum of squared errors over the (up, down, flat) one-hot space.

    Returns None if any probability is missing or actual is not in {UP, DOWN, FLAT}.
    Range: [0, 2]. Lower is better. A uniform (1/3, 1/3, 1/3) gives 2/3 ≈ 0.667.
    """
    if actual is None or actual not in _TREND_TO_VEC:
        return None
    p_up = _coerce_prob(prob_up)
    p_down = _coerce_prob(prob_down)
    p_flat = _coerce_prob(prob_flat)
    if p_up is None or p_down is None or p_flat is None:
        return None
    y = _TREND_TO_VEC[actual]
    p = (p_up, p_down, p_flat)
    return round(sum((pi - yi) ** 2 for pi, yi in zip(p, y)), 6)


def log_loss(
    prob_up: float | None,
    prob_down: float | None,
    prob_flat: float | None,
    actual: Trend | None,
    eps: float = 1e-9,
) -> float | None:
    """Negative log probability of the actual class, clipped to avoid log(0)."""
    if actual is None or actual not in _TREND_TO_VEC:
        return None
    p_map = {
        Trend.UP: _coerce_prob(prob_up),
        Trend.DOWN: _coerce_prob(prob_down),
        Trend.FLAT: _coerce_prob(prob_flat),
    }
    p = p_map.get(actual)
    if p is None:
        return None
    p = max(eps, min(1 - eps, p))
    return round(-math.log(p), 6)


def expected_calibration_error(
    predictions: "Iterable[DailyPrediction]",
    n_bins: int = 5,
) -> float | None:
    """ECE = Σ_b (n_b / N) · |avg_confidence_b − hit_rate_b| over n_bins equal-width bins.

    Only verified predictions with non-null tomorrow_confidence enter the calc.
    """
    eligible = [
        p for p in predictions
        if p.verified_correct is not None and p.tomorrow_confidence is not None
    ]
    if not eligible:
        return None
    n_total = len(eligible)
    edges = [i / n_bins for i in range(n_bins + 1)]
    weighted_gap = 0.0
    for i in range(n_bins):
        low, high = edges[i], edges[i + 1]
        in_bucket = [
            p for p in eligible
            if (low <= p.tomorrow_confidence < high
                or (i == n_bins - 1 and p.tomorrow_confidence == high))
        ]
        if not in_bucket:
            continue
        avg_conf = sum(p.tomorrow_confidence for p in in_bucket) / len(in_bucket)
        hit_rate = sum(1 for p in in_bucket if p.verified_correct) / len(in_bucket)
        weighted_gap += (len(in_bucket) / n_total) * abs(avg_conf - hit_rate)
    return round(weighted_gap, 6)


def reliability_diagram(
    predictions: "Iterable[DailyPrediction]",
    n_bins: int = 5,
) -> list[ReliabilityBin]:
    """Return per-bin (low, high, sample_size, avg_confidence, hit_rate) for plotting."""
    eligible = [
        p for p in predictions
        if p.verified_correct is not None and p.tomorrow_confidence is not None
    ]
    edges = [i / n_bins for i in range(n_bins + 1)]
    bins: list[ReliabilityBin] = []
    for i in range(n_bins):
        low, high = edges[i], edges[i + 1]
        in_bucket = [
            p for p in eligible
            if (low <= p.tomorrow_confidence < high
                or (i == n_bins - 1 and p.tomorrow_confidence == high))
        ]
        if not in_bucket:
            continue
        avg_conf = sum(p.tomorrow_confidence for p in in_bucket) / len(in_bucket)
        hit_rate = sum(1 for p in in_bucket if p.verified_correct) / len(in_bucket)
        bins.append(
            ReliabilityBin(
                bucket_low=round(low, 2),
                bucket_high=round(high, 2),
                sample_size=len(in_bucket),
                avg_confidence=round(avg_conf, 4),
                hit_rate=round(hit_rate, 4),
            )
        )
    return bins
