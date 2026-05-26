"""Tests for chains/flat_gate — the hard FLAT-class gate.

Covers:
- truth table of (atr_pct, rsi, dist_ma20_z) combinations
- None inputs never fire a condition (degraded data must not pass)
- enforce_flat_ceiling redistributes excess proportional to up/down
"""
import os
import unittest

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")

from chains.flat_gate import (
    FLAT_BLOCKED_CEILING,
    enforce_flat_ceiling,
    evaluate_flat_gate,
)


class EvaluateFlatGateTests(unittest.TestCase):
    def test_all_three_conditions_allow(self):
        r = evaluate_flat_gate(atr_percentile=0.20, rsi=50, dist_ma20_z=0.1)
        self.assertTrue(r.allow_high_flat)
        self.assertEqual(set(r.fired), {"atr_low_pct", "rsi_neutral", "low_ma_dist"})

    def test_two_conditions_allow(self):
        # ATR low + RSI neutral, but MA distance too far.
        r = evaluate_flat_gate(atr_percentile=0.20, rsi=50, dist_ma20_z=1.0)
        self.assertTrue(r.allow_high_flat)
        self.assertEqual(set(r.fired), {"atr_low_pct", "rsi_neutral"})

    def test_one_condition_blocks(self):
        r = evaluate_flat_gate(atr_percentile=0.20, rsi=70, dist_ma20_z=1.0)
        self.assertFalse(r.allow_high_flat)
        self.assertEqual(r.fired, ["atr_low_pct"])

    def test_none_inputs_block(self):
        r = evaluate_flat_gate(atr_percentile=None, rsi=None, dist_ma20_z=None)
        self.assertFalse(r.allow_high_flat)
        self.assertEqual(r.fired, [])

    def test_boundary_atr_percentile_exclusive(self):
        # < 0.35 fires; ≥ 0.35 does not.
        self.assertIn("atr_low_pct", evaluate_flat_gate(0.349, None, None).fired)
        self.assertNotIn("atr_low_pct", evaluate_flat_gate(0.35, None, None).fired)
        self.assertNotIn("atr_low_pct", evaluate_flat_gate(0.40, None, None).fired)

    def test_boundary_rsi_inclusive(self):
        # 45 and 55 both fire; 44.9 and 55.1 do not.
        self.assertIn("rsi_neutral", evaluate_flat_gate(None, 45.0, None).fired)
        self.assertIn("rsi_neutral", evaluate_flat_gate(None, 55.0, None).fired)
        self.assertNotIn("rsi_neutral", evaluate_flat_gate(None, 44.9, None).fired)
        self.assertNotIn("rsi_neutral", evaluate_flat_gate(None, 55.1, None).fired)

    def test_boundary_ma_dist_uses_abs(self):
        self.assertIn("low_ma_dist", evaluate_flat_gate(None, None, 0.49).fired)
        self.assertIn("low_ma_dist", evaluate_flat_gate(None, None, -0.49).fired)
        self.assertNotIn("low_ma_dist", evaluate_flat_gate(None, None, 0.5).fired)
        self.assertNotIn("low_ma_dist", evaluate_flat_gate(None, None, -0.5).fired)


class EnforceFlatCeilingTests(unittest.TestCase):
    def test_allow_high_flat_no_change(self):
        u, d, f, modified = enforce_flat_ceiling(0.10, 0.10, 0.80, allow_high_flat=True)
        self.assertEqual((u, d, f), (0.10, 0.10, 0.80))
        self.assertFalse(modified)

    def test_below_ceiling_no_change(self):
        u, d, f, modified = enforce_flat_ceiling(0.30, 0.30, 0.40, allow_high_flat=False)
        self.assertEqual((u, d, f), (0.30, 0.30, 0.40))
        self.assertFalse(modified)

    def test_caps_flat_and_redistributes_proportionally(self):
        u, d, f, modified = enforce_flat_ceiling(0.10, 0.20, 0.70, allow_high_flat=False)
        self.assertTrue(modified)
        self.assertAlmostEqual(f, FLAT_BLOCKED_CEILING, places=4)
        # excess = 0.30, base = 0.30, up gets 0.30 * (0.10/0.30) = 0.10
        self.assertAlmostEqual(u, 0.20, places=4)
        self.assertAlmostEqual(d, 0.40, places=4)

    def test_caps_flat_even_split_when_base_zero(self):
        u, d, f, modified = enforce_flat_ceiling(0.0, 0.0, 1.0, allow_high_flat=False)
        self.assertTrue(modified)
        self.assertAlmostEqual(f, FLAT_BLOCKED_CEILING, places=4)
        self.assertAlmostEqual(u, 0.30, places=4)
        self.assertAlmostEqual(d, 0.30, places=4)


if __name__ == "__main__":
    unittest.main()
