import gc
import os
import sqlite3
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

        # These modules copy DB_PATH by value at import time (mirrors
        # test_phase2_features._DBBackedTest) — rebind each, or the first test
        # pins them to a temp dir that tearDown deletes and later tests crash.
        import storage.record_manager as record_manager
        import chains.baselines as baselines
        import chains.regime as regime
        import tools.macro as macro
        import tools.technicals as technicals
        self.rm = record_manager
        self._db_mods = [record_manager, baselines, regime, macro, technicals]
        self._orig_paths = [m.DB_PATH for m in self._db_mods]
        for mod in self._db_mods:
            mod.DB_PATH = self.db_path
        record_manager.init_storage()

    def tearDown(self):
        for mod, orig in zip(self._db_mods, self._orig_paths):
            mod.DB_PATH = orig
        gc.collect()
        time.sleep(0.05)
        if self.db_path.exists():
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def test_run_daily_prediction_persists_record(self):
        from chains import daily_runner

        # Most recent weekday — run_daily_prediction skips weekends (returns None).
        today = self._weekday_date(0)
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

        today = self._weekday_date(0)
        with patch("chains.daily_runner.fetch_dual_close", return_value=(None, None, CloseSourceStatus.NEITHER)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]):
            prediction = daily_runner.run_daily_prediction(today)

        # Both sources missing → placeholder, no fabricated direction.
        self.assertIs(prediction.tomorrow_direction, Trend.UNKNOWN)
        self.assertIsNone(prediction.tomorrow_confidence)
        self.assertEqual(prediction.error, "dual_close_unavailable")
        self.assertEqual(prediction.model_name, "(skipped)")

    def _weekday_date(self, days_back: int) -> str:
        """Pick a date `days_back` ago; the date itself AND the next day must be
        weekdays (run_daily_prediction skips weekends, verify needs a weekday anchor)."""
        candidate = datetime.now() - timedelta(days=days_back)
        while candidate.weekday() >= 5 or (candidate + timedelta(days=1)).weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate.strftime("%Y-%m-%d")

    @staticmethod
    def _next_day(date: str) -> str:
        nxt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
        while nxt.weekday() >= 5:  # mirror verify_prediction's weekend walk
            nxt += timedelta(days=1)
        return nxt.strftime("%Y-%m-%d")

    def _insert_ohlc(self, date: str, source: str, close: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_ohlc (date, source, open, high, low, close, locked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (date, source, close, close, close, close, "test"),
            )
            conn.commit()

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

        # next_day == today + in post-close window → live feed path (the normal 03:10 verify).
        with patch("chains.verifier._today_beijing", return_value=self._next_day(first_day)), \
                patch("chains.verifier.is_post_close_window", return_value=True), \
                patch("chains.verifier.fetch_dual_close", return_value=(2520.0, 2515.0, CloseSourceStatus.BOTH)):
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

        with patch("chains.verifier._today_beijing", return_value=self._next_day(first_day)), \
                patch("chains.verifier.is_post_close_window", return_value=True), \
                patch("chains.verifier.fetch_dual_close", return_value=(2440.0, 2435.0, CloseSourceStatus.BOTH)):
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

        # Pin today to Monday so this exercises the live-feed path (verifying
        # Friday's prediction on Monday morning), isolating the weekend-walk.
        with patch("chains.verifier._today_beijing", return_value=monday), \
                patch("chains.verifier.is_post_close_window", return_value=True), \
                patch("chains.verifier.fetch_dual_close", return_value=(2520.0, 2515.0, CloseSourceStatus.BOTH)) as mocked_fetch:
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

        with patch("chains.verifier._today_beijing", return_value=self._next_day(first_day)), \
                patch("chains.verifier.is_post_close_window", return_value=True), \
                patch("chains.verifier.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)):
            refreshed = verifier.verify_prediction(first_day)
        self.assertIsNone(refreshed.verified_correct)

    def test_verifier_catchup_past_date_uses_ohlc_not_live(self):
        """Regression: catch-up verification of an OLD prediction (next_day < today)
        must read next_day's LOCKED close from daily_ohlc, never the live feed —
        the live feed only reflects 'right now' and would compare the anchor
        against today's price, fabricating a direction."""
        from chains import daily_runner, verifier

        anchor = datetime.now() - timedelta(days=5)
        while anchor.weekday() >= 5 or (anchor + timedelta(days=1)).weekday() >= 5:
            anchor -= timedelta(days=1)
        anchor_date = anchor.strftime("%Y-%m-%d")
        next_day = self._next_day(anchor_date)

        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x", "today_direction": "上涨",
                    "tomorrow_direction": "上涨", "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y", "tomorrow_reasoning": "z",
                    "risk_factors": [], "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(anchor_date)

        # Locked OHLC for next_day shows an UP move (2480 -> 2520).
        self._insert_ohlc(next_day, "sge", 2520.0)
        self._insert_ohlc(next_day, "comex", 2515.0)

        # Live feed would (wrongly) report a DOWN move; it must NOT be consulted.
        with patch("chains.verifier.fetch_dual_close",
                   return_value=(2400.0, 2395.0, CloseSourceStatus.BOTH)) as live_fetch:
            refreshed = verifier.verify_prediction(anchor_date)
            live_fetch.assert_not_called()

        self.assertIsNotNone(refreshed)
        self.assertTrue(refreshed.verified_correct)
        self.assertEqual(refreshed.verified_actual_close, 2520.0)
        self.assertIs(refreshed.verified_actual_direction, Trend.UP)

    def test_verifier_same_day_out_of_window_uses_ohlc_not_live(self):
        """Even when next_day == today, outside the post-close window (weekday
        02:30–09:00 Beijing) the live quote is an intraday price, not the close —
        verify must read the locked daily_ohlc and never touch the live feed."""
        from chains import daily_runner, verifier

        first_day = self._weekday_date(2)
        next_day = self._next_day(first_day)
        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x", "today_direction": "上涨",
                    "tomorrow_direction": "上涨", "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y", "tomorrow_reasoning": "z",
                    "risk_factors": [], "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(first_day)

        # 03:05 lock already ran: next_day's close is locked at 2520 (UP move).
        self._insert_ohlc(next_day, "sge", 2520.0)
        self._insert_ohlc(next_day, "comex", 2515.0)

        # Live feed reports an intraday DOWN move; it must NOT be consulted.
        with patch("chains.verifier._today_beijing", return_value=next_day), \
                patch("chains.verifier.is_post_close_window", return_value=False), \
                patch("chains.verifier.fetch_dual_close",
                      return_value=(2400.0, 2395.0, CloseSourceStatus.BOTH)) as live_fetch:
            refreshed = verifier.verify_prediction(first_day)
            live_fetch.assert_not_called()

        self.assertIsNotNone(refreshed)
        self.assertTrue(refreshed.verified_correct)
        self.assertEqual(refreshed.verified_actual_close, 2520.0)

    def test_scheduler_cold_start_verify_out_of_window_skips_live(self):
        """Integration: an intraday process restart fires _verify_action(cold-start);
        with the real window math seeing an afternoon clock, the live feed must not
        be consulted and the prediction must stay unverified (no ohlc row yet)."""
        import asyncio
        from zoneinfo import ZoneInfo

        from chains import daily_runner, scheduler

        anchor = datetime.now() - timedelta(days=3)
        while anchor.weekday() >= 5 or (anchor + timedelta(days=1)).weekday() >= 5:
            anchor -= timedelta(days=1)
        anchor_date = anchor.strftime("%Y-%m-%d")
        next_day = self._next_day(anchor_date)

        with patch("chains.daily_runner.fetch_dual_close", return_value=(2480.0, 2475.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]), \
                patch("chains.daily_runner.build_daily_prediction_mock", return_value={
                    "today_summary": "x", "today_direction": "上涨",
                    "tomorrow_direction": "上涨", "tomorrow_confidence": 0.6,
                    "tomorrow_advice": "y", "tomorrow_reasoning": "z",
                    "risk_factors": [], "calibration_note": "n",
                }):
            daily_runner.run_daily_prediction(anchor_date)

        # 2026-06-03 is a Wednesday; 14:00 is mid day-session — outside 02:30–09:00.
        intraday = datetime(2026, 6, 3, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch("chains.verifier._today_beijing", return_value=next_day), \
                patch("tools.market_time.beijing_now", return_value=intraday), \
                patch("chains.verifier.fetch_dual_close",
                      return_value=(2400.0, 2395.0, CloseSourceStatus.BOTH)) as live_fetch:
            asyncio.run(scheduler._verify_action(reason="cold-start"))
            live_fetch.assert_not_called()

        refreshed = self.rm.get_daily_prediction(anchor_date)
        self.assertIsNotNone(refreshed)
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
