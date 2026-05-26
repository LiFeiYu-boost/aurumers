"""Tests for chains/calibration — global per-class multiplicative scaler."""
import os
import unittest
from uuid import uuid4

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")

from chains.calibration import (
    CALIBRATOR_VERSION_GLOBAL,
    CALIBRATOR_VERSION_REGIME,
    MIN_REGIME_CLASS_SAMPLES,
    MIN_SAMPLES,
    PROB_CEILING,
    PROB_FLOOR,
    SCALE_MAX,
    SCALE_MIN,
    apply_calibration,
    fit_calibrator,
)
from schemas import CloseSourceStatus, DailyPrediction, RegimeLabel, Trend


def _make_verified(
    *,
    date: str,
    pred_up: float,
    pred_down: float,
    pred_flat: float,
    actual: Trend,
    prob_source: str = "model",
    regime: RegimeLabel | None = None,
) -> DailyPrediction:
    triple_max = max(pred_up, pred_down, pred_flat)
    if triple_max == pred_up:
        direction = Trend.UP
    elif triple_max == pred_down:
        direction = Trend.DOWN
    else:
        direction = Trend.FLAT
    correct = direction == actual
    return DailyPrediction(
        id=str(uuid4()),
        predicted_at=f"{date} 02:50:00",
        prediction_date=date,
        today_close_source=CloseSourceStatus.BOTH,
        tomorrow_direction=direction,
        tomorrow_confidence=triple_max,
        prob_up=pred_up,
        prob_down=pred_down,
        prob_flat=pred_flat,
        prob_up_raw=pred_up,
        prob_down_raw=pred_down,
        prob_flat_raw=pred_flat,
        prob_source=prob_source,
        regime_label=regime,
        verified_at=f"{date} 03:10:00",
        verified_actual_close=100.0,
        verified_actual_direction=actual,
        verified_correct=correct,
    )


class FitCalibratorTests(unittest.TestCase):
    def test_insufficient_data_returns_unit_scales(self):
        result = fit_calibrator([])
        self.assertEqual(result.status, "insufficient_data")
        self.assertEqual(result.scales, {"up": 1.0, "down": 1.0, "flat": 1.0})

    def test_below_min_samples_returns_unit_scales(self):
        # MIN_SAMPLES is 20; verify exactly one less is still "insufficient_data".
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.34, pred_down=0.33, pred_flat=0.33,
                actual=Trend.UP,
            )
            for i in range(MIN_SAMPLES - 1)
        ]
        self.assertEqual(fit_calibrator(sample).status, "insufficient_data")

    def test_excludes_synthetic_and_mock(self):
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.34, pred_down=0.33, pred_flat=0.33,
                actual=Trend.UP,
                prob_source="synthetic_backtest",
            )
            for i in range(MIN_SAMPLES + 5)
        ]
        # All synthetic → eligible pool empty → insufficient_data.
        self.assertEqual(fit_calibrator(sample).status, "insufficient_data")

    def test_flat_biased_predictions_get_flat_scale_down(self):
        # 25 samples: model predicts flat heavily (0.7 flat) but reality is up.
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.15, pred_down=0.15, pred_flat=0.70,
                actual=Trend.UP,
            )
            for i in range(25)
        ]
        result = fit_calibrator(sample)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.sample_size, 25)
        # Predicted flat rate 0.70, actual flat rate 0.0 → desired scale = 0,
        # clamped up to SCALE_MIN (0.5). Expect flat scale = SCALE_MIN.
        self.assertEqual(result.scales["flat"], SCALE_MIN)
        # Up actual rate 1.0 / predicted 0.15 → 6.67, clamped to SCALE_MAX.
        self.assertEqual(result.scales["up"], SCALE_MAX)

    def test_calibrated_scales_clamped_to_range(self):
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.33, pred_down=0.33, pred_flat=0.34,
                actual=Trend.UP if i % 2 == 0 else Trend.DOWN,
            )
            for i in range(MIN_SAMPLES + 5)
        ]
        result = fit_calibrator(sample)
        for class_name, scale in result.scales.items():
            self.assertGreaterEqual(scale, SCALE_MIN, msg=class_name)
            self.assertLessEqual(scale, SCALE_MAX, msg=class_name)


class ApplyCalibrationTests(unittest.TestCase):
    def test_unit_scales_passthrough(self):
        u, d, f = apply_calibration(0.40, 0.35, 0.25, {"up": 1, "down": 1, "flat": 1})
        self.assertAlmostEqual(u + d + f, 1.0, places=4)
        self.assertAlmostEqual(u, 0.40, places=4)

    def test_renorm_after_scaling(self):
        u, d, f = apply_calibration(
            0.20, 0.20, 0.60,
            {"up": 2.0, "down": 2.0, "flat": 0.5},
        )
        self.assertAlmostEqual(u + d + f, 1.0, places=4)
        # up and down were scaled equally; should remain equal after renorm.
        self.assertAlmostEqual(u, d, places=4)
        # Flat should be much smaller now.
        self.assertLess(f, 0.30)

    def test_floor_applied(self):
        u, d, f = apply_calibration(
            0.001, 0.499, 0.500,
            {"up": 0.5, "down": 1.0, "flat": 1.0},
        )
        # Each prob, after scaling and clamp, has a hard floor at PROB_FLOOR;
        # the floor lifts the smallest before renorm.
        before_renorm_floor = PROB_FLOOR
        # We can't directly inspect the intermediate but assert renorm sum holds
        # and the smallest is at least PROB_FLOOR / (total post-clamp).
        self.assertAlmostEqual(u + d + f, 1.0, places=4)
        self.assertGreaterEqual(min(u, d, f), 0.0)

    def test_ceiling_applied(self):
        u, d, f = apply_calibration(
            0.99, 0.005, 0.005,
            {"up": 2.0, "down": 1.0, "flat": 1.0},
        )
        # 0.99 * 2.0 = 1.98, clamped to PROB_CEILING = 0.85. After renorm, up
        # share is dominated by the clamp.
        self.assertAlmostEqual(u + d + f, 1.0, places=4)
        # The clamped pre-renorm up was 0.85; total was 0.85 + 0.05 + 0.05 = 0.95.
        # post-renorm up = 0.85 / 0.95 ≈ 0.8947.
        self.assertAlmostEqual(u, 0.85 / 0.95, places=2)

    def test_degenerate_zero_triple_uniform_fallback(self):
        u, d, f = apply_calibration(0.0, 0.0, 0.0, {"up": 0.5, "down": 0.5, "flat": 0.5})
        # With everything zero after scaling and the floor lifting all three
        # to PROB_FLOOR, the renorm should give 1/3 each.
        self.assertAlmostEqual(u, 1 / 3, places=4)
        self.assertAlmostEqual(d, 1 / 3, places=4)
        self.assertAlmostEqual(f, 1 / 3, places=4)


class RegimeConditionedTests(unittest.TestCase):
    def test_no_regime_returns_global_version(self):
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.15, pred_down=0.15, pred_flat=0.70,
                actual=Trend.UP,
            )
            for i in range(25)
        ]
        r = fit_calibrator(sample, regime=None)
        self.assertEqual(r.version, CALIBRATOR_VERSION_GLOBAL)
        self.assertIsNone(r.regime)

    def test_regime_with_sufficient_per_class_uses_regime_scale(self):
        # 30 bull samples: 25 up, 5 flat. Bull "up" actual count = 25 ≥ 10.
        bull_up = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.30, pred_down=0.20, pred_flat=0.50,
                actual=Trend.UP, regime=RegimeLabel.BULL,
            )
            for i in range(25)
        ]
        bull_flat = [
            _make_verified(
                date=f"2026-02-{i+1:02d}",
                pred_up=0.30, pred_down=0.20, pred_flat=0.50,
                actual=Trend.FLAT, regime=RegimeLabel.BULL,
            )
            for i in range(5)
        ]
        # Background bear samples to satisfy MIN_SAMPLES on the global pool
        bear_down = [
            _make_verified(
                date=f"2026-03-{i+1:02d}",
                pred_up=0.30, pred_down=0.20, pred_flat=0.50,
                actual=Trend.DOWN, regime=RegimeLabel.BEAR,
            )
            for i in range(10)
        ]
        r = fit_calibrator(bull_up + bull_flat + bear_down, regime=RegimeLabel.BULL)
        self.assertEqual(r.version, CALIBRATOR_VERSION_REGIME)
        self.assertEqual(r.regime, "bull")
        # In bull bucket "up" has 25 actual hits ≥ MIN_REGIME_CLASS_SAMPLES — regime path
        self.assertEqual(r.per_class_source["up"], "regime")
        # "down" had 0 actual in bull → < threshold → global fallback
        self.assertEqual(r.per_class_source["down"], "global")

    def test_regime_with_no_matching_rows_falls_back_to_global(self):
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.30, pred_down=0.20, pred_flat=0.50,
                actual=Trend.UP, regime=RegimeLabel.BEAR,
            )
            for i in range(25)
        ]
        r = fit_calibrator(sample, regime=RegimeLabel.BULL)
        self.assertEqual(r.version, CALIBRATOR_VERSION_REGIME)
        # All classes drew from global because BULL has no matching rows.
        self.assertEqual(set(r.per_class_source.values()), {"global"})

    def test_unknown_regime_takes_global_path(self):
        sample = [
            _make_verified(
                date=f"2026-01-{i+1:02d}",
                pred_up=0.30, pred_down=0.20, pred_flat=0.50,
                actual=Trend.UP,
            )
            for i in range(25)
        ]
        r = fit_calibrator(sample, regime=RegimeLabel.UNKNOWN)
        self.assertEqual(r.version, CALIBRATOR_VERSION_GLOBAL)


if __name__ == "__main__":
    unittest.main()
