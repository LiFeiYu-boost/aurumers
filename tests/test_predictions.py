import gc
import os
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("SCHEDULER_DAILY_ENABLED", "0")

from schemas import CloseSourceStatus, Trend


class DailyPredictionFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "predictions.db"

        import storage.record_manager as record_manager
        self.rm = record_manager
        self.original = record_manager.DB_PATH
        record_manager.DB_PATH = self.db_path
        record_manager.init_storage()

    def tearDown(self):
        self.rm.DB_PATH = self.original
        gc.collect()
        time.sleep(0.05)
        if self.db_path.exists():
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def test_run_daily_prediction_persists_record(self):
        from chains import daily_runner

        today = datetime.now().strftime("%Y-%m-%d")
        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]):
            prediction = daily_runner.run_daily_prediction(today)

        self.assertEqual(prediction.prediction_date, today)
        self.assertEqual(prediction.today_close_sge, 2480.0)
        self.assertEqual(prediction.today_close_comex, 2475.0)
        self.assertIs(prediction.today_close_source, CloseSourceStatus.BOTH)
        self.assertEqual(prediction.model_name, "mock")

        from storage.record_manager import get_daily_prediction
        roundtrip = get_daily_prediction(today)
        self.assertIsNotNone(roundtrip)
        self.assertEqual(roundtrip.tomorrow_direction, prediction.tomorrow_direction)

    def test_run_daily_prediction_dual_failure_skips_with_placeholder(self):
        from chains import daily_runner

        today = datetime.now().strftime("%Y-%m-%d")
        with patch("chains.daily_runner.fetch_dual_close", return_value=(None, None, CloseSourceStatus.NEITHER)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]):
            prediction = daily_runner.run_daily_prediction(today)

        # Both sources missing → placeholder, no fabricated direction.
        self.assertIs(prediction.tomorrow_direction, Trend.UNKNOWN)
        self.assertIsNone(prediction.tomorrow_confidence)
        self.assertEqual(prediction.error, "dual_close_unavailable")
        self.assertEqual(prediction.model_name, "(skipped)")

    def _weekday_date(self, days_back: int) -> str:
        """Pick a date `days_back` ago, but ensure NEXT day is a weekday for verify."""
        candidate = datetime.now() - timedelta(days=days_back)
        while (candidate + timedelta(days=1)).weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate.strftime("%Y-%m-%d")

    def test_verifier_marks_correct_when_direction_matches(self):
        from chains import daily_runner, verifier

        first_day = self._weekday_date(1)
        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x",
                    "today_direction": "上涨",
                    "tomorrow_direction": "上涨",
                    "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y",
                    "tomorrow_reasoning": "z",
                    "risk_factors": [],
                    "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(first_day)

        with patch("chains.verifier.fetch_dual_close", return_value=(2520.0, 2515.0, CloseSourceStatus.BOTH)):
            refreshed = verifier.verify_prediction(first_day)

        self.assertIsNotNone(refreshed)
        self.assertTrue(refreshed.verified_correct)
        self.assertEqual(refreshed.verified_actual_close, 2520.0)
        self.assertIs(refreshed.verified_actual_direction, Trend.UP)

    def test_verifier_marks_wrong_when_direction_mismatches(self):
        from chains import daily_runner, verifier

        first_day = self._weekday_date(2)
        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x",
                    "today_direction": "上涨",
                    "tomorrow_direction": "上涨",
                    "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y",
                    "tomorrow_reasoning": "z",
                    "risk_factors": [],
                    "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(first_day)

        with patch("chains.verifier.fetch_dual_close", return_value=(2440.0, 2435.0, CloseSourceStatus.BOTH)):
            refreshed = verifier.verify_prediction(first_day)

        self.assertIsNotNone(refreshed)
        self.assertFalse(refreshed.verified_correct)

    def test_verifier_advances_past_weekend_for_friday_prediction(self):
        """Friday prediction should be checked against Monday's close (skip Sat/Sun)."""
        from chains import daily_runner, verifier

        # Find a Friday in the past
        candidate = datetime.now()
        while candidate.weekday() != 4:
            candidate -= timedelta(days=1)
        if candidate >= datetime.now():
            candidate -= timedelta(days=7)
        friday = candidate.strftime("%Y-%m-%d")
        monday = (candidate + timedelta(days=3)).strftime("%Y-%m-%d")

        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x", "today_direction": "上涨",
                    "tomorrow_direction": "上涨", "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y", "tomorrow_reasoning": "z",
                    "risk_factors": [], "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(friday)

        with patch("chains.verifier.fetch_dual_close", return_value=(2520.0, 2515.0, CloseSourceStatus.BOTH)) as mocked_fetch:
            refreshed = verifier.verify_prediction(friday)
        # Should call fetch_dual_close with Monday's date (not Saturday/Sunday)
        mocked_fetch.assert_called_once()
        called_with = mocked_fetch.call_args[0][0]
        self.assertEqual(called_with, monday)
        # Friday's prediction is now verified against Monday's close
        self.assertTrue(refreshed.verified_correct)
        self.assertEqual(refreshed.verified_actual_close, 2520.0)

    def test_verifier_refuses_when_actual_equals_anchor(self):
        """If next-day quote is byte-identical to anchor, refuse (likely closed market)."""
        from chains import daily_runner, verifier

        first_day = self._weekday_date(2)
        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x", "today_direction": "上涨",
                    "tomorrow_direction": "上涨", "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y", "tomorrow_reasoning": "z",
                    "risk_factors": [], "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(first_day)

        with patch("chains.verifier.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)):
            refreshed = verifier.verify_prediction(first_day)
        self.assertIsNone(refreshed.verified_correct)


class CalibratorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "cal.db"

        import storage.record_manager as record_manager
        self.rm = record_manager
        self.original = record_manager.DB_PATH
        record_manager.DB_PATH = self.db_path
        record_manager.init_storage()

    def tearDown(self):
        self.rm.DB_PATH = self.original
        gc.collect()
        time.sleep(0.05)
        if self.db_path.exists():
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def test_compute_accuracy_empty(self):
        snap = self.rm.compute_accuracy("30d")
        self.assertEqual(snap.total_predictions, 0)
        self.assertEqual(snap.overall_accuracy, 0.0)

    def test_compute_accuracy_with_records(self):
        from schemas import DailyPrediction, Trend

        for i, (direction, correct, conf) in enumerate([
            (Trend.UP, True, 0.7),
            (Trend.UP, False, 0.65),
            (Trend.DOWN, True, 0.55),
            (Trend.FLAT, True, 0.4),
            (Trend.UP, False, 0.8),
        ]):
            date = (datetime.now() - timedelta(days=i + 1)).strftime("%Y-%m-%d")
            self.rm.save_daily_prediction(DailyPrediction(
                id=f"p{i}",
                predicted_at=date + " 02:50:00",
                prediction_date=date,
                tomorrow_direction=direction,
                tomorrow_confidence=conf,
                verified_actual_close=2500.0,
                verified_actual_direction=Trend.UP if correct and direction is Trend.UP else direction,
                verified_correct=correct,
                verified_at=date + " 03:10:00",
            ))

        snap = self.rm.compute_accuracy("30d")
        self.assertEqual(snap.verified_predictions, 5)
        self.assertEqual(snap.correct_predictions, 3)
        self.assertEqual(snap.overall_accuracy, 0.6)
        self.assertGreaterEqual(len(snap.accuracy_by_confidence), 1)


if __name__ == "__main__":
    unittest.main()
