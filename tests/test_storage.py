import gc
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from schemas import AnalysisRecord, AnalysisStatus, NewsItem, Trend


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"

        import storage.record_manager as record_manager

        self.record_manager = record_manager
        self.original_db_path = record_manager.DB_PATH
        record_manager.DB_PATH = self.db_path
        record_manager.init_storage()

    def tearDown(self):
        self.record_manager.DB_PATH = self.original_db_path
        gc.collect()
        time.sleep(0.05)
        if self.db_path.exists():
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def test_save_and_query_record(self):
        record = AnalysisRecord(
            id="1",
            time="2026-04-30 20:00:00",
            source="manual",
            status=AnalysisStatus.SUCCESS,
            price_raw="3300.1",
            price_value=3300.1,
            news=[NewsItem(title="黄金上涨", source="test")],
            summary="市场偏强",
            trend=Trend.UP,
            reasons=["避险需求走高"],
            advice="逢低关注",
            raw_output="{}",
            model_name="test-model",
            prompt_version="v4",
            latency_ms=123,
            error=None,
            input_snapshot={},
        )
        self.record_manager.save_record(record)
        latest = self.record_manager.get_latest_records(1)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0].summary, "市场偏强")
        self.assertEqual(latest[0].news[0].title, "黄金上涨")

    def test_dashboard_summary(self):
        record = AnalysisRecord(
            id="2",
            time="2026-04-30 20:00:00",
            source="manual",
            status=AnalysisStatus.PARTIAL,
            price_raw="N/A",
            price_value=None,
            news=[],
            summary="暂无总结",
            trend=Trend.UNKNOWN,
            reasons=[],
            advice="暂无建议",
            raw_output="",
            model_name="test-model",
            prompt_version="v4",
            latency_ms=1,
            error="抓取失败",
            input_snapshot={},
        )
        self.record_manager.save_record(record)
        summary = self.record_manager.get_dashboard_summary(limit=10)
        self.assertEqual(summary.total_records, 1)
        self.assertEqual(summary.status_counts["partial"], 1)


if __name__ == "__main__":
    unittest.main()
