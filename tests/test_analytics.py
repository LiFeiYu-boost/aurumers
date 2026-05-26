import gc
import os
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from schemas import AnalysisRecord, AnalysisStatus, NewsItem, Trend


def _record(time_offset_minutes: int, *, price: float | None = 3300.0,
            status: AnalysisStatus = AnalysisStatus.SUCCESS,
            trend: Trend = Trend.UP, latency: int = 100,
            confidence: float | None = 0.4) -> AnalysisRecord:
    when = datetime.now() - timedelta(minutes=time_offset_minutes)
    return AnalysisRecord(
        id=f"id-{time_offset_minutes}",
        time=when.strftime("%Y-%m-%d %H:%M:%S"),
        source="manual",
        status=status,
        price_raw=str(price) if price is not None else "N/A",
        price_value=price,
        news=[NewsItem(title="t", source="s")],
        summary="s",
        trend=trend,
        reasons=["r"],
        advice="a",
        raw_output="{}",
        model_name="mock",
        prompt_version="v5",
        latency_ms=latency,
        error=None,
        input_snapshot={},
        confidence=confidence,
        news_count=1,
    )


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
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

    def test_kpis_empty(self):
        kpi = self.rm.compute_kpis("24h")
        self.assertEqual(kpi.total_runs, 0)
        self.assertEqual(kpi.success_rate, 0.0)
        self.assertIsNone(kpi.avg_price)

    def test_kpis_single_record(self):
        self.rm.save_record(_record(5, price=3300.5))
        kpi = self.rm.compute_kpis("24h")
        self.assertEqual(kpi.total_runs, 1)
        self.assertEqual(kpi.success_rate, 1.0)
        self.assertEqual(kpi.avg_price, 3300.5)
        self.assertEqual(kpi.volatility, 0.0)
        self.assertEqual(kpi.latest_price, 3300.5)

    def test_kpis_multi_record(self):
        for offset, price in [(60, 3290.0), (30, 3300.0), (10, 3310.0)]:
            self.rm.save_record(_record(offset, price=price))
        # Mark one as failed for success-rate verification
        self.rm.save_record(_record(5, price=None, status=AnalysisStatus.FAILED, trend=Trend.UNKNOWN))

        kpi = self.rm.compute_kpis("24h")
        self.assertEqual(kpi.total_runs, 4)
        self.assertEqual(kpi.success_rate, 0.75)
        self.assertEqual(kpi.avg_price, 3300.0)
        self.assertGreater(kpi.volatility, 0)

    def test_timeseries_filter_by_range(self):
        self.rm.save_record(_record(60 * 24 * 5, price=3000.0))  # 5 days ago
        self.rm.save_record(_record(30, price=3300.0))            # 30 min ago
        key24, within_24h = self.rm.query_timeseries("24h")
        key7d, within_7d = self.rm.query_timeseries("7d")
        self.assertEqual(key24, "24h")
        self.assertEqual(key7d, "7d")
        self.assertEqual(len(within_24h), 1)
        self.assertEqual(within_24h[0].price, 3300.0)
        self.assertEqual(len(within_7d), 2)

    def test_timeseries_invalid_range_falls_back(self):
        _, _ = self.rm.query_timeseries("garbage")
        key, _ = self.rm.query_timeseries("garbage")
        self.assertEqual(key, "24h")

    def test_distribution_buckets(self):
        self.rm.save_record(_record(120, trend=Trend.UP))
        self.rm.save_record(_record(60, trend=Trend.UP))
        self.rm.save_record(_record(20, trend=Trend.DOWN, status=AnalysisStatus.PARTIAL))
        key, snap = self.rm.query_distribution("24h")
        self.assertEqual(key, "24h")
        self.assertEqual(snap.total_records, 3)
        self.assertEqual(snap.trend_counts["上涨"], 2)
        self.assertEqual(snap.trend_counts["下跌"], 1)
        self.assertEqual(snap.status_counts["partial"], 1)
        self.assertGreaterEqual(len(snap.hourly_status), 1)


if __name__ == "__main__":
    unittest.main()
