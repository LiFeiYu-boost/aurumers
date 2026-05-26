"""In-memory backtest harness: replays the post-processing pipeline against
the existing DailyPrediction history and reports paired Brier / log-loss / ECE
for "raw" vs "post-processed" probability triples.

Usage::

    .venv/bin/python -m tools.backtest_post_processing --window 90

Designed to be safe to run on the VPS:
- Read-only against the DB (never writes a new row).
- Uses the row's existing ATR / RSI / dist_ma20_z fields as the gate inputs
  (so it works even for older rows that pre-date the prob_*_raw columns).

When a row has no prob_*_raw stored (legacy rows), the script treats the
existing prob_* triple as the "raw" baseline and replays calibration + gates
on top — this gives an apples-to-apples view of "what would the headline
metric look like if we had applied the new pipeline at the time?"
"""
from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass

from chains.calibration import apply_calibration, fit_calibrator
from chains.flat_gate import enforce_flat_ceiling, evaluate_flat_gate
from chains.metrics import brier_multiclass, log_loss as compute_log_loss
from schemas import DailyPrediction, Trend
from storage.record_manager import get_daily_predictions


logger = logging.getLogger(__name__)


TREND_GATE_TAU = 0.55


@dataclass
class PairedMetric:
    label: str
    n_eligible: int
    brier: float | None
    log_loss: float | None
    ece: float | None
    pred_share_up: float
    pred_share_down: float
    pred_share_flat: float
    accuracy: float


def _pick_baseline(p: DailyPrediction) -> tuple[float | None, float | None, float | None]:
    """Use prob_*_raw when available, else fall back to prob_*."""
    if p.prob_up_raw is not None and p.prob_down_raw is not None and p.prob_flat_raw is not None:
        return p.prob_up_raw, p.prob_down_raw, p.prob_flat_raw
    return p.prob_up, p.prob_down, p.prob_flat


def _atr_percentile_proxy(p: DailyPrediction, atr_distribution: list[float]) -> float | None:
    """Approximate ATR percentile from the in-memory historical ATR values.

    Real percentile needs the per-date 60-day rolling window — to stay
    self-contained without re-running tools.technicals, we fall back to the
    rank of this row's ATR within the full distribution. Good enough for an
    A/B sanity check; the prod path uses the exact percentile.
    """
    if p.atr14 is None or not atr_distribution:
        return None
    n = len(atr_distribution)
    less = sum(1 for v in atr_distribution if v < p.atr14)
    less_eq = sum(1 for v in atr_distribution if v <= p.atr14)
    return (less + less_eq) / (2 * n)


def _apply_pipeline(
    raw_up: float,
    raw_down: float,
    raw_flat: float,
    *,
    atr_pct: float | None,
    rsi: float | None,
    dist_ma20_z: float | None,
    scales: dict[str, float],
) -> tuple[float, float, float]:
    cal_up, cal_down, cal_flat = apply_calibration(raw_up, raw_down, raw_flat, scales)
    gate = evaluate_flat_gate(atr_pct, rsi, dist_ma20_z)
    cal_up, cal_down, cal_flat, _ = enforce_flat_ceiling(
        cal_up, cal_down, cal_flat, allow_high_flat=gate.allow_high_flat,
    )
    trend_mass = cal_up + cal_down
    if trend_mass >= TREND_GATE_TAU and cal_flat >= max(cal_up, cal_down):
        freed = cal_flat - 0.05
        if trend_mass > 0:
            cal_up += freed * (cal_up / trend_mass)
            cal_down += freed * (cal_down / trend_mass)
        else:
            cal_up += freed / 2
            cal_down += freed / 2
        cal_flat = 0.05
    total = cal_up + cal_down + cal_flat
    if total > 0:
        cal_up /= total
        cal_down /= total
        cal_flat /= total
    return cal_up, cal_down, cal_flat


def _direction(up: float, down: float, flat: float) -> Trend:
    triple = {Trend.UP: up, Trend.DOWN: down, Trend.FLAT: flat}
    return max(triple, key=triple.get)


def _summarise(
    label: str,
    triples: list[tuple[float, float, float]],
    outcomes: list[Trend],
) -> PairedMetric:
    n = len(triples)
    if n == 0:
        return PairedMetric(label, 0, None, None, None, 0, 0, 0, 0.0)

    briers: list[float] = []
    losses: list[float] = []
    correct = 0
    up_share = down_share = flat_share = 0
    confidences: list[tuple[float, bool]] = []

    for (up, down, flat), actual in zip(triples, outcomes):
        b = brier_multiclass(up, down, flat, actual)
        if b is not None:
            briers.append(b)
        ll = compute_log_loss(up, down, flat, actual)
        if ll is not None:
            losses.append(ll)
        direction = _direction(up, down, flat)
        if direction == actual:
            correct += 1
        if direction is Trend.UP:
            up_share += 1
        elif direction is Trend.DOWN:
            down_share += 1
        else:
            flat_share += 1
        confidences.append((max(up, down, flat), direction == actual))

    # Expected calibration error (5 equal-width bins on the max-prob).
    bins = 5
    edges = [i / bins for i in range(bins + 1)]
    ece_weighted = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        bucket = [
            (c, hit) for c, hit in confidences
            if (lo <= c < hi or (i == bins - 1 and c == hi))
        ]
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        hit_rate = sum(1 for _, hit in bucket if hit) / len(bucket)
        ece_weighted += (len(bucket) / n) * abs(avg_conf - hit_rate)

    return PairedMetric(
        label=label,
        n_eligible=n,
        brier=round(sum(briers) / len(briers), 4) if briers else None,
        log_loss=round(sum(losses) / len(losses), 4) if losses else None,
        ece=round(ece_weighted, 4),
        pred_share_up=round(up_share / n, 4),
        pred_share_down=round(down_share / n, 4),
        pred_share_flat=round(flat_share / n, 4),
        accuracy=round(correct / n, 4),
    )


def run(window_days: int = 90, calibration_window: int = 60) -> tuple[PairedMetric, PairedMetric]:
    history = get_daily_predictions(window_days=window_days)
    calibration = fit_calibrator(history, window=calibration_window)

    atr_values = [p.atr14 for p in history if p.atr14 is not None]

    raw_triples: list[tuple[float, float, float]] = []
    pp_triples: list[tuple[float, float, float]] = []
    outcomes: list[Trend] = []

    for p in history:
        if p.verified_correct is None:
            continue
        if p.verified_actual_direction not in (Trend.UP, Trend.DOWN, Trend.FLAT):
            continue
        raw_up, raw_down, raw_flat = _pick_baseline(p)
        if raw_up is None or raw_down is None or raw_flat is None:
            continue
        atr_pct = _atr_percentile_proxy(p, atr_values)
        pp_up, pp_down, pp_flat = _apply_pipeline(
            raw_up, raw_down, raw_flat,
            atr_pct=atr_pct,
            rsi=p.rsi14,
            dist_ma20_z=p.dist_ma20_z,
            scales=calibration.scales,
        )
        raw_triples.append((raw_up, raw_down, raw_flat))
        pp_triples.append((pp_up, pp_down, pp_flat))
        outcomes.append(p.verified_actual_direction)

    raw = _summarise("raw", raw_triples, outcomes)
    pp = _summarise("post-processed", pp_triples, outcomes)
    return raw, pp


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=90, help="History window in days")
    parser.add_argument("--cal-window", type=int, default=60, help="Calibration fit window")
    args = parser.parse_args()

    raw, pp = run(args.window, args.cal_window)
    width = 24
    print(f"{'metric':<{width}}{'raw':>14}{'post-processed':>20}")
    for attr in ("n_eligible", "brier", "log_loss", "ece", "accuracy",
                 "pred_share_up", "pred_share_down", "pred_share_flat"):
        lhs = getattr(raw, attr)
        rhs = getattr(pp, attr)
        print(f"{attr:<{width}}{str(lhs):>14}{str(rhs):>20}")


if __name__ == "__main__":
    main()
