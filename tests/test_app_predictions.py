import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "0")
os.environ.setdefault("SCHEDULER_DAILY_ENABLED", "0")


class AppPredictionsApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import storage.record_manager as record_manager

        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app_pred.db"
        self.original_db = record_manager.DB_PATH
        record_manager.DB_PATH = self.db_path
        record_manager.init_storage()
        self.record_manager = record_manager

        from app import app
        self.client = TestClient(app)

    def tearDown(self):
        self.record_manager.DB_PATH = self.original_db
        self.temp_dir.cleanup()

    def test_today_prediction_empty(self):
        resp = self.client.get("/api/predictions/today").json()
        self.assertTrue(resp["success"])
        self.assertIsNone(resp["data"])

    def test_run_then_today_returns_record(self):
        from schemas import CloseSourceStatus
        with patch("chains.daily_runner.fetch_dual_close",
                   return_value=(2480.5, 2476.0, CloseSourceStatus.BOTH)), \
                patch("chains.daily_runner.get_gold_news", return_value=[]):
            today_iso = datetime.now().strftime("%Y-%m-%d")
            run = self.client.post(f"/api/predictions/daily/run?date={today_iso}").json()
        self.assertTrue(run["success"], run.get("error"))
        self.assertEqual(run["data"]["prediction_date"], today_iso)

        today = self.client.get("/api/predictions/today").json()
        self.assertTrue(today["success"])
        self.assertEqual(today["data"]["prediction_date"], today_iso)

    def test_accuracy_endpoint(self):
        resp = self.client.get("/api/predictions/accuracy?window=30d").json()
        self.assertTrue(resp["success"])
        self.assertEqual(resp["data"]["overall_accuracy"], 0.0)

    def test_calibration_endpoint(self):
        resp = self.client.get("/api/predictions/calibration").json()
        self.assertTrue(resp["success"])
        self.assertEqual(resp["data"], [])

    def test_channels_endpoint(self):
        resp = self.client.get("/api/notifications/channels").json()
        self.assertTrue(resp["success"])
        self.assertIn("configured", resp["data"])
        self.assertIn("available", resp["data"])

    def test_test_notification_blocked_without_flag(self):
        # ALLOW_TEST_NOTIFY default off → 403
        resp = self.client.post("/api/notifications/test")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
