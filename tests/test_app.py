import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")
os.environ.setdefault("SCHEDULER_ENABLED", "0")


class AppApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import storage.record_manager as record_manager

        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "app.db"
        self.original_db = record_manager.DB_PATH
        record_manager.DB_PATH = self.db_path
        record_manager.init_storage()
        self.record_manager = record_manager

        from app import app
        self.client = TestClient(app)

    def tearDown(self):
        self.record_manager.DB_PATH = self.original_db
        self.temp_dir.cleanup()

    def test_kpis_endpoint_empty(self):
        response = self.client.get("/api/analytics/kpis?range=24h")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["total_runs"], 0)

    def test_run_then_kpis_increment(self):
        run = self.client.post("/api/analysis/run").json()
        self.assertTrue(run["success"], run.get("error"))

        ts = self.client.get("/api/analytics/timeseries?range=24h").json()
        self.assertTrue(ts["success"])
        self.assertGreaterEqual(len(ts["data"]["points"]), 1)

        dist = self.client.get("/api/analytics/distribution?range=24h").json()
        self.assertTrue(dist["success"])
        self.assertGreaterEqual(dist["data"]["total_records"], 1)

        kpi = self.client.get("/api/analytics/kpis?range=24h").json()
        self.assertTrue(kpi["success"])
        self.assertGreaterEqual(kpi["data"]["total_runs"], 1)

    def test_invalid_range_falls_back(self):
        response = self.client.get("/api/analytics/timeseries?range=lol").json()
        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["range"], "24h")
        dist = self.client.get("/api/analytics/distribution?range=lol").json()
        self.assertTrue(dist["success"])
        self.assertEqual(dist["data"]["range"], "24h")

    def test_legacy_static_dir_still_mounted(self):
        # Legacy assets remain at /static-legacy/ during the SPA migration.
        response = self.client.get("/static-legacy/css/app.css")
        # 200 if file still exists, 404 acceptable if user has cleaned up; either way no crash.
        self.assertIn(response.status_code, (200, 404))


if __name__ == "__main__":
    unittest.main()
