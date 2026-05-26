"""Phase 1.5 backtest tests — historical fetcher, daily_runner historical mode, exclusion."""
import gc
import os
import sqlite3
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("SCHEDULER_DAILY_ENABLED", "0")

from schemas import CloseSourceStatus, DailyPrediction, Trend


class _DBBackedTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "phase15.db"
        import storage.record_manager as rm
        self.rm = rm
        self.original = rm.DB_PATH
        rm.DB_PATH = self.db_path
        rm.init_storage()
        # regime module imports DB_PATH at import time — patch its module-level too
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


class FetchDualCloseFromOhlcTests(_DBBackedTest):
    def test_returns_locked_data_both(self):
        from tools.gold_close import fetch_dual_close_from_ohlc
        # Patch DB_PATH for the gold_close module too via its lazy import
        with patch("storage.record_manager.DB_PATH", self.db_path):
            self._insert_ohlc("2026-01-15", "sge", 1234.56)
            self._insert_ohlc("2026-01-15", "comex", 2345.67)
            sge, comex, status = fetch_dual_close_from_ohlc("2026-01-15")
            self.assertAlmostEqual(sge, 1234.56)
            self.assertAlmostEqual(comex, 2345.67)
            self.assertEqual(status, CloseSourceStatus.BOTH)

    def test_returns_neither_for_missing_date(self):
        from tools.gold_close import fetch_dual_close_from_ohlc
        with patch("storage.record_manager.DB_PATH", self.db_path):
            sge, comex, status = fetch_dual_close_from_ohlc("2099-12-31")
            self.assertIsNone(sge)
            self.assertIsNone(comex)
            self.assertEqual(status, CloseSourceStatus.NEITHER)

    def test_sge_only_status(self):
        from tools.gold_close import fetch_dual_close_from_ohlc
        with patch("storage.record_manager.DB_PATH", self.db_path):
            self._insert_ohlc("2026-02-10", "sge", 1000.0)
            sge, comex, status = fetch_dual_close_from_ohlc("2026-02-10")
            self.assertAlmostEqual(sge, 1000.0)
            self.assertIsNone(comex)
            self.assertEqual(status, CloseSourceStatus.SGE_ONLY)


class HistoricalDailyRunnerTests(_DBBackedTest):
    def _seed_ohlc(self):
        # Plant some OHLC across 14 days so daily_runner can pick anchor
        base = datetime(2026, 1, 1)
        for i in range(14):
            d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(d, "sge", 1000 + i * 2)
            self._insert_ohlc(d, "comex", 2400 + i * 5)

    def test_historical_mode_persists_synthetic_backtest_source(self):
        from chains import daily_runner
        with patch("storage.record_manager.DB_PATH", self.db_path):
            self._seed_ohlc()
            pred = daily_runner.run_daily_prediction("2026-01-10", historical_mode=True)
            self.assertEqual(pred.prob_source, "synthetic_backtest")
            self.assertIsNotNone(pred.prob_up)
            self.assertIsNotNone(pred.prob_down)
            self.assertIsNotNone(pred.prob_flat)

    def test_historical_mode_skips_news_and_distribution(self):
        """Capture the payload to confirm news_text + distribution_text are placeholders."""
        from chains import daily_runner
        captured = {}

        original_run_chain = daily_runner._run_chain

        def spy_run_chain(payload):
            captured.update(payload)
            return original_run_chain(payload)

        with patch("storage.record_manager.DB_PATH", self.db_path), \
             patch("chains.daily_runner._run_chain", side_effect=spy_run_chain):
            self._seed_ohlc()
            daily_runner.run_daily_prediction("2026-01-10", historical_mode=True)
            self.assertIn("历史回测", captured.get("news_text", ""))
            self.assertIn("历史回测", captured.get("recent_distribution", ""))


class HistoricalVerifierTests(_DBBackedTest):
    def _make_prediction(self, date: str, direction: Trend, sge: float, comex: float) -> DailyPrediction:
        from schemas import CloseSourceStatus
        pred = DailyPrediction(
            id=str(uuid4()),
            predicted_at=f"{date} 02:50:00",
            prediction_date=date,
            today_close_sge=sge,
            today_close_comex=comex,
            today_close_source=CloseSourceStatus.BOTH,
            today_direction=direction,
            tomorrow_direction=direction,
            tomorrow_confidence=0.6,
            prob_up=0.6 if direction == Trend.UP else 0.2,
            prob_down=0.6 if direction == Trend.DOWN else 0.2,
            prob_flat=0.6 if direction == Trend.FLAT else 0.2,
            prob_source="synthetic_backtest",
        )
        self.rm.save_daily_prediction(pred)
        return pred

    def test_historical_verifier_uses_ohlc_not_live(self):
        from chains import verifier
        with patch("storage.record_manager.DB_PATH", self.db_path):
            # Set up: anchor day SGE 1000, next-day SGE 1010 (UP move)
            anchor_date = "2026-03-03"  # Tuesday
            next_date = "2026-03-04"
            self._insert_ohlc(anchor_date, "sge", 1000.0)
            self._insert_ohlc(anchor_date, "comex", 2400.0)
            self._insert_ohlc(next_date, "sge", 1010.0)
            self._insert_ohlc(next_date, "comex", 2410.0)
            self._make_prediction(anchor_date, Trend.UP, sge=1000.0, comex=2400.0)
            # If historical_mode=True, must NOT hit the live fetcher
            with patch("chains.verifier.fetch_dual_close") as live_fetch:
                refreshed = verifier.verify_prediction(anchor_date, historical_mode=True)
                live_fetch.assert_not_called()
            self.assertIsNotNone(refreshed)
            self.assertTrue(refreshed.verified_correct)
            self.assertAlmostEqual(refreshed.verified_actual_close, 1010.0)


class ComputeAccuracyV2SyntheticTests(_DBBackedTest):
    def _save(self, date: str, direction: Trend, source: str, hit: bool):
        from schemas import CloseSourceStatus
        floor = 0.05
        base = max(floor, min(1 - 2 * floor, 0.6))
        other = max(floor, (1 - base) / 2)
        triple = {Trend.UP: (base, other, other),
                  Trend.DOWN: (other, base, other),
                  Trend.FLAT: (other, other, base)}[direction]
        total = sum(triple)
        prob_up, prob_down, prob_flat = (round(v / total, 4) for v in triple)
        pred = DailyPrediction(
            id=str(uuid4()),
            predicted_at=f"{date} 02:50:00",
            prediction_date=date,
            today_close_sge=1000.0,
            today_close_comex=2400.0,
            today_close_source=CloseSourceStatus.BOTH,
            today_direction=direction,
            tomorrow_direction=direction,
            tomorrow_confidence=0.6,
            prob_up=prob_up,
            prob_down=prob_down,
            prob_flat=prob_flat,
            prob_source=source,
            verified_at=f"{date} 03:10:00",
            verified_actual_close=1010.0,
            verified_actual_direction=direction,
            verified_correct=hit,
        )
        self.rm.save_daily_prediction(pred)

    def test_default_excludes_synthetic_backtest(self):
        with patch("storage.record_manager.DB_PATH", self.db_path):
            self._save("2026-05-01", Trend.UP, source="model", hit=True)
            self._save("2026-05-02", Trend.UP, source="synthetic_backtest", hit=False)
            self._save("2026-05-03", Trend.DOWN, source="reconstructed", hit=False)
            snap = self.rm.compute_accuracy_v2("30d")
            self.assertEqual(snap.verified_predictions, 1)
            self.assertEqual(
                snap.sample_count_by_source,
                {"model": 1, "synthetic_backtest": 1, "reconstructed": 1},
            )

    def test_include_synthetic_only(self):
        with patch("storage.record_manager.DB_PATH", self.db_path):
            self._save("2026-05-01", Trend.UP, source="model", hit=True)
            self._save("2026-05-02", Trend.UP, source="synthetic_backtest", hit=False)
            self._save("2026-05-03", Trend.DOWN, source="reconstructed", hit=False)
            snap = self.rm.compute_accuracy_v2("30d", include_synthetic=True)
            # model + synthetic_backtest = 2; reconstructed still excluded
            self.assertEqual(snap.verified_predictions, 2)

    def test_include_both_flags(self):
        with patch("storage.record_manager.DB_PATH", self.db_path):
            self._save("2026-05-01", Trend.UP, source="model", hit=True)
            self._save("2026-05-02", Trend.UP, source="synthetic_backtest", hit=False)
            self._save("2026-05-03", Trend.DOWN, source="reconstructed", hit=False)
            snap = self.rm.compute_accuracy_v2(
                "30d", include_synthetic=True, include_reconstructed=True,
            )
            self.assertEqual(snap.verified_predictions, 3)


if __name__ == "__main__":
    unittest.main()
