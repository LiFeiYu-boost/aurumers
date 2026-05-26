"""End-to-end tests for the post-processing pipeline in chains/daily_runner.

Covers _apply_post_processing across the four decision branches:
- gate allows flat (all three conditions fire)
- gate blocks high flat (cap to 0.4, redistribute to up/down)
- trend gate forces trend pick when argmax would have been flat
- env-flag disable bypasses everything
- raw triple None → no_raw_triple short-circuit
"""
import os
import unittest

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")

from chains.calibration import CalibrationResult
from chains.daily_runner import _apply_post_processing


def _unit_cal(status: str = "disabled_env_flag") -> CalibrationResult:
    return CalibrationResult(
        scales={"up": 1.0, "down": 1.0, "flat": 1.0},
        status=status,
        version="cal-v1-global",
        sample_size=0,
        predicted_rate={"up": 0.0, "down": 0.0, "flat": 0.0},
        actual_rate={"up": 0.0, "down": 0.0, "flat": 0.0},
    )


class PostProcessingTests(unittest.TestCase):

    def test_no_raw_triple_short_circuits(self):
        post = _apply_post_processing(
            raw_up=None, raw_down=0.5, raw_flat=0.5,
            calibration=_unit_cal(),
            atr_pct=0.2, rsi=50, dist_ma20_z=0.0,
            calibration_disabled=True, flat_gate_disabled=False, trend_gate_disabled=False,
        )
        self.assertEqual(post["trend_gate_decision"], "no_raw_triple")
        self.assertEqual(post["prob_up"], None)
        self.assertEqual(post["calibrator_status"], "no_raw_triple")

    def test_flat_allowed_when_three_conditions_fire(self):
        post = _apply_post_processing(
            raw_up=0.15, raw_down=0.15, raw_flat=0.70,
            calibration=_unit_cal(),
            atr_pct=0.20, rsi=50, dist_ma20_z=0.10,
            calibration_disabled=True, flat_gate_disabled=False, trend_gate_disabled=False,
        )
        self.assertEqual(post["trend_gate_decision"], "flat_allowed")
        self.assertAlmostEqual(post["prob_flat"], 0.70, places=4)
        self.assertEqual(set(post["flat_gate_fired"]), {"atr_low_pct", "rsi_neutral", "low_ma_dist"})

    def test_flat_blocked_when_no_conditions_fire(self):
        post = _apply_post_processing(
            raw_up=0.15, raw_down=0.15, raw_flat=0.70,
            calibration=_unit_cal(),
            atr_pct=0.80, rsi=70, dist_ma20_z=2.0,
            calibration_disabled=True, flat_gate_disabled=False, trend_gate_disabled=False,
        )
        # After cap to 0.4 then trend-forced (trend mass 0.6 ≥ 0.55, argmax was flat),
        # flat goes to 0.05; decision becomes composite.
        self.assertIn("flat_blocked_by_gate", post["trend_gate_decision"])
        self.assertIn("trend_forced", post["trend_gate_decision"])
        self.assertAlmostEqual(post["prob_flat"], 0.05, places=2)
        self.assertAlmostEqual(post["prob_up"] + post["prob_down"] + post["prob_flat"], 1.0, places=3)

    def test_trend_forced_when_gate_allows_but_trend_mass_high(self):
        post = _apply_post_processing(
            raw_up=0.32, raw_down=0.28, raw_flat=0.40,
            calibration=_unit_cal(),
            atr_pct=0.20, rsi=50, dist_ma20_z=0.10,  # all gate conditions fire
            calibration_disabled=True, flat_gate_disabled=False, trend_gate_disabled=False,
        )
        # Trend mass 0.6 ≥ 0.55 AND argmax was flat → trend_forced
        self.assertEqual(post["trend_gate_decision"], "trend_forced")
        # Flat squeezed to floor 0.05
        self.assertAlmostEqual(post["prob_flat"], 0.05, places=2)

    def test_all_disabled_passthrough(self):
        post = _apply_post_processing(
            raw_up=0.10, raw_down=0.10, raw_flat=0.80,
            calibration=_unit_cal(),
            atr_pct=0.80, rsi=70, dist_ma20_z=2.0,
            calibration_disabled=True, flat_gate_disabled=True, trend_gate_disabled=True,
        )
        self.assertEqual(post["trend_gate_decision"], "disabled_env_flag")
        self.assertAlmostEqual(post["prob_flat"], 0.80, places=4)
        self.assertAlmostEqual(post["prob_up"], 0.10, places=4)
        self.assertEqual(post["flat_gate_fired"], [])

    def test_calibration_applied_changes_triple(self):
        cal = CalibrationResult(
            scales={"up": 2.0, "down": 2.0, "flat": 0.5},
            status="ok", version="cal-v1-global", sample_size=30,
            predicted_rate={"up": 0.2, "down": 0.2, "flat": 0.6},
            actual_rate={"up": 0.4, "down": 0.4, "flat": 0.2},
        )
        post = _apply_post_processing(
            raw_up=0.20, raw_down=0.20, raw_flat=0.60,
            calibration=cal,
            atr_pct=0.20, rsi=50, dist_ma20_z=0.10,  # gate allows flat passthrough
            calibration_disabled=False, flat_gate_disabled=False, trend_gate_disabled=True,
        )
        # 0.2*2=0.4, 0.2*2=0.4, 0.6*0.5=0.3 → renorm sum 1.1 → up=down ≈ 0.364, flat ≈ 0.273
        self.assertAlmostEqual(post["prob_up"], 0.4 / 1.1, places=3)
        self.assertAlmostEqual(post["prob_flat"], 0.3 / 1.1, places=3)
        self.assertEqual(post["calibrator_status"], "ok")
        self.assertEqual(post["calibrator_scales"], {"up": 2.0, "down": 2.0, "flat": 0.5})

    def test_renormalised_triple_sums_to_one(self):
        post = _apply_post_processing(
            raw_up=0.10, raw_down=0.20, raw_flat=0.70,
            calibration=_unit_cal(),
            atr_pct=0.50, rsi=60, dist_ma20_z=0.20,  # only low_ma_dist fires
            calibration_disabled=True, flat_gate_disabled=False, trend_gate_disabled=False,
        )
        self.assertAlmostEqual(
            post["prob_up"] + post["prob_down"] + post["prob_flat"], 1.0, places=3,
        )


if __name__ == "__main__":
    unittest.main()
