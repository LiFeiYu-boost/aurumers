"""Phase 1 metrics tests — Brier / log-loss / ECE / regime / compute_accuracy_v2."""
import gc
import math
import os
import sqlite3
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("SCHEDULER_DAILY_ENABLED", "0")

from schemas import (
    CloseSourceStatus,
    DailyPrediction,
    RegimeLabel,
    Trend,
)


class MetricsMathTests(unittest.TestCase):
    """Pure math — no DB."""

    def test_brier_perfect(self):
        from chains.metrics import brier_multiclass
        self.assertEqual(brier_multiclass(1.0, 0.0, 0.0, Trend.UP), 0.0)
        self.assertEqual(brier_multiclass(0.0, 1.0, 0.0, Trend.DOWN), 0.0)
        self.assertEqual(brier_multiclass(0.0, 0.0, 1.0, Trend.FLAT), 0.0)

    def test_brier_pure_wrong(self):
        from chains.metrics import brier_multiclass
        self.assertEqual(brier_multiclass(1.0, 0.0, 0.0, Trend.DOWN), 2.0)

    def test_brier_uniform(self):
        from chains.metrics import brier_multiclass
        result = brier_multiclass(1 / 3, 1 / 3, 1 / 3, Trend.UP)
        self.assertAlmostEqual(result, 2 / 3, places=4)

    def test_brier_nullable_inputs(self):
        from chains.metrics import brier_multiclass
        self.assertIsNone(brier_multiclass(None, 0.5, 0.5, Trend.UP))
        self.assertIsNone(brier_multiclass(0.5, 0.3, 0.2, None))
        self.assertIsNone(brier_multiclass(0.5, 0.3, 0.2, Trend.UNKNOWN))

    def test_log_loss_perfect(self):
        from chains.metrics import log_loss
        self.assertAlmostEqual(log_loss(1.0, 0.0, 0.0, Trend.UP), 0.0, places=4)

    def test_log_loss_clipped(self):
        from chains.metrics import log_loss
        result = log_loss(0.0, 0.5, 0.5, Trend.UP)
        # -log(1e-9) ≈ 20.72
        self.assertAlmostEqual(result, -math.log(1e-9), places=2)

    def test_log_loss_typical(self):
        from chains.metrics import log_loss
        result = log_loss(0.6, 0.3, 0.1, Trend.UP)
        self.assertAlmostEqual(result, -math.log(0.6), places=4)


def _mk_pred(date, direction, confidence, *, verified, hit, prob_source="model",
             prob_up=None, prob_down=None, prob_flat=None,
             actual_direction=None, regime: RegimeLabel | None = None) -> DailyPrediction:
    if prob_up is None:
        # Auto-fill triple from (direction, confidence) so tests can omit them
        floor = 0.05
        base = max(floor, min(1 - 2 * floor, confidence))
        other = max(floor, (1 - base) / 2)
        triple = {Trend.UP: (base, other, other),
                  Trend.DOWN: (other, base, other),
                  Trend.FLAT: (other, other, base)}[direction]
        total = sum(triple)
        prob_up, prob_down, prob_flat = (round(v / total, 4) for v in triple)
    return DailyPrediction(
        id=str(uuid4()),
        predicted_at=f"{date} 02:50:00",
        prediction_date=date,
        today_close_sge=1000.0,
        today_close_comex=2400.0,
        today_close_source=CloseSourceStatus.BOTH,
        today_direction=direction,
        tomorrow_direction=direction,
        tomorrow_confidence=confidence,
        prob_up=prob_up,
        prob_down=prob_down,
        prob_flat=prob_flat,
        prob_source=prob_source,
        regime_label=regime,
        verified_at=f"{date} 03:10:00" if verified else None,
        verified_actual_close=1005.0 if verified else None,
        verified_actual_direction=(actual_direction or direction) if verified else None,
        verified_correct=hit if verified else None,
    )


class ECEAndReliabilityTests(unittest.TestCase):
    def test_ece_calibrated(self):
        """Per-bucket avg_conf ≈ hit_rate → ECE small."""
        from chains.metrics import expected_calibration_error
        preds = []
        # bucket 0.6-0.8 confidence with 70% hit rate (10 preds, 7 hits)
        for i in range(10):
            preds.append(_mk_pred(f"2026-04-{i+1:02d}", Trend.UP, 0.7,
                                   verified=True, hit=(i < 7)))
        ece = expected_calibration_error(preds, n_bins=5)
        self.assertIsNotNone(ece)
        self.assertLess(ece, 0.05)

    def test_ece_miscalibrated(self):
        """Conf=0.9 but hit=0.5 → ECE ≈ 0.4."""
        from chains.metrics import expected_calibration_error
        preds = [
            _mk_pred(f"2026-04-{i+1:02d}", Trend.UP, 0.9,
                     verified=True, hit=(i % 2 == 0))
            for i in range(20)
        ]
        ece = expected_calibration_error(preds, n_bins=5)
        self.assertIsNotNone(ece)
        self.assertGreater(ece, 0.3)

    def test_reliability_diagram_structure(self):
        from chains.metrics import reliability_diagram
        preds = [_mk_pred(f"2026-04-{i+1:02d}", Trend.UP, 0.65, verified=True, hit=(i < 6))
                 for i in range(10)]
        bins = reliability_diagram(preds, n_bins=5)
        self.assertGreaterEqual(len(bins), 1)
        self.assertEqual(bins[0].sample_size, 10)
        self.assertAlmostEqual(bins[0].avg_confidence, 0.65, places=4)
        self.assertAlmostEqual(bins[0].hit_rate, 0.6, places=4)


class _DBBackedTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "phase1.db"
        import storage.record_manager as rm
        self.rm = rm
        self.original = rm.DB_PATH
        rm.DB_PATH = self.db_path
        rm.init_storage()
        # also patch the regime module to use the same db path
        import chains.regime as regime_mod
        self.regime_mod = regime_mod
        self.original_regime_db = regime_mod.DB_PATH
        regime_mod.DB_PATH = self.db_path

    def tearDown(self):
        self.rm.DB_PATH = self.original
        self.regime_mod.DB_PATH = self.original_regime_db
        gc.collect()
        time.sleep(0.05)
        if self.db_path.exists():
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def _insert_ohlc(self, date: str, source: str, close: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_ohlc (date, source, open, high, low, close, locked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (date, source, close, close, close, close, "test"),
            )
            conn.commit()


class RegimeTests(_DBBackedTest):
    def test_regime_unknown_when_insufficient(self):
        from chains.regime import classify_regime
        # Only 5 rows on each source — below 20-day threshold
        for i in range(5):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", 1000 + i)
            self._insert_ohlc(day, "comex", 2400 + i)
        result = classify_regime("2026-04-30")
        self.assertEqual(result, RegimeLabel.UNKNOWN)

    def test_regime_bull_dual_agreement(self):
        from chains.regime import classify_regime
        # 30 days uptrend with last-5-day acceleration: +8% over 30d, +3% over last 5d
        # Days 0..24 (oldest..mid): linearly +5% (1.0 → 1.05)
        # Days 25..29 (mid..newest): +3% (1.05 → ~1.083)
        base_sge, base_comex = 1000.0, 2400.0
        for i in range(30):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            if i <= 24:
                multiplier = 1 + 0.05 * (i / 24)
            else:
                multiplier = 1.05 * (1 + 0.03 * ((i - 24) / 5))
            self._insert_ohlc(day, "sge", base_sge * multiplier)
            self._insert_ohlc(day, "comex", base_comex * multiplier)
        end = (datetime(2026, 4, 1) + timedelta(days=29)).strftime("%Y-%m-%d")
        self.assertEqual(classify_regime(end), RegimeLabel.BULL)

    def test_regime_transition_disagreement(self):
        from chains.regime import classify_regime
        # SGE strong bull, COMEX strong bear → transition
        base_sge, base_comex = 1000.0, 2400.0
        for i in range(30):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", base_sge * (1 + 0.08 * i / 29))
            self._insert_ohlc(day, "comex", base_comex * (1 - 0.08 * i / 29))
        end = (datetime(2026, 4, 1) + timedelta(days=29)).strftime("%Y-%m-%d")
        self.assertEqual(classify_regime(end), RegimeLabel.TRANSITION)

    def test_regime_choppy_low_vol(self):
        from chains.regime import classify_regime
        # 30 flat days with tiny noise → choppy on both sources
        for i in range(30):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            noise = ((i % 3) - 1) * 0.5  # -0.5 / 0 / +0.5
            self._insert_ohlc(day, "sge", 1000 + noise)
            self._insert_ohlc(day, "comex", 2400 + noise)
        end = (datetime(2026, 4, 1) + timedelta(days=29)).strftime("%Y-%m-%d")
        self.assertEqual(classify_regime(end), RegimeLabel.CHOPPY)


class ComputeAccuracyV2Tests(_DBBackedTest):
    def _save_pred(self, **kwargs) -> DailyPrediction:
        pred = _mk_pred(**kwargs)
        self.rm.save_daily_prediction(pred)
        return pred

    def test_v2_default_excludes_reconstructed(self):
        # 1 model + 1 reconstructed, both verified
        self._save_pred(date="2026-05-01", direction=Trend.UP, confidence=0.6,
                        verified=True, hit=True, prob_source="model")
        self._save_pred(date="2026-05-02", direction=Trend.DOWN, confidence=0.55,
                        verified=True, hit=False, prob_source="reconstructed")
        snap = self.rm.compute_accuracy_v2("30d")
        self.assertEqual(snap.verified_predictions, 1)
        self.assertEqual(snap.sample_count_by_source, {"model": 1, "reconstructed": 1})
        self.assertTrue(snap.excluded_reconstructed)

    def test_v2_include_reconstructed_flag(self):
        self._save_pred(date="2026-05-01", direction=Trend.UP, confidence=0.6,
                        verified=True, hit=True, prob_source="model")
        self._save_pred(date="2026-05-02", direction=Trend.DOWN, confidence=0.55,
                        verified=True, hit=False, prob_source="reconstructed")
        snap = self.rm.compute_accuracy_v2("30d", include_reconstructed=True)
        self.assertEqual(snap.verified_predictions, 2)
        self.assertFalse(snap.excluded_reconstructed)

    def test_v2_brier_average(self):
        # Two perfect predictions → Brier = 0
        self._save_pred(date="2026-05-01", direction=Trend.UP, confidence=0.99,
                        verified=True, hit=True, prob_source="model",
                        prob_up=0.98, prob_down=0.01, prob_flat=0.01,
                        actual_direction=Trend.UP)
        self._save_pred(date="2026-05-02", direction=Trend.DOWN, confidence=0.97,
                        verified=True, hit=True, prob_source="model",
                        prob_up=0.01, prob_down=0.98, prob_flat=0.01,
                        actual_direction=Trend.DOWN)
        snap = self.rm.compute_accuracy_v2("30d")
        self.assertIsNotNone(snap.brier_multiclass)
        self.assertLess(snap.brier_multiclass, 0.005)

    def test_v2_no_verified_returns_zero_metrics(self):
        self._save_pred(date="2026-05-01", direction=Trend.UP, confidence=0.6,
                        verified=False, hit=False, prob_source="model")
        snap = self.rm.compute_accuracy_v2("30d")
        self.assertEqual(snap.verified_predictions, 0)
        self.assertEqual(snap.overall_accuracy, 0.0)
        self.assertIsNone(snap.brier_multiclass)


class MetricsApiTests(_DBBackedTest):
    def test_metrics_detailed_endpoint(self):
        from fastapi.testclient import TestClient
        # Save one verified model prediction to make snapshot non-empty
        pred = _mk_pred(date="2026-05-01", direction=Trend.UP, confidence=0.6,
                        verified=True, hit=True, prob_source="model")
        self.rm.save_daily_prediction(pred)
        from app import app
        with TestClient(app) as client:
            r = client.get("/api/predictions/metrics/detailed?window=30d")
            self.assertEqual(r.status_code, 200)
            payload = r.json()["data"]
            for key in (
                "brier_multiclass", "log_loss", "ece",
                "accuracy_by_regime", "brier_by_regime",
                "reliability_diagram", "sample_count_by_source",
                "excluded_reconstructed",
                "overall_accuracy", "verified_predictions",
            ):
                self.assertIn(key, payload, f"missing key {key}")
            self.assertTrue(payload["excluded_reconstructed"])


if __name__ == "__main__":
    unittest.main()
