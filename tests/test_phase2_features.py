"""Phase 2 tests — tools.macro / tools.technicals / chains.daily_lock /
prompt template / _build_payload integration.

Patterns mirror tests/test_phase1_metrics.py: TemporaryDirectory + DB_PATH
monkey-patching for DB-backed tests, urllib mocking for FRED, akshare
patching for daily_lock to avoid live network calls.
"""
import gc
import io
import math
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


# ---------------------------------------------------------------------------
# Shared DB harness
# ---------------------------------------------------------------------------

class _DBBackedTest(unittest.TestCase):
    """Each test gets its own temp DB; storage + indicator + macro modules
    are all rebound to it for the duration of the test."""

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "phase2.db"

        import storage.record_manager as rm
        import tools.macro as macro_mod
        import tools.technicals as tech_mod
        import chains.daily_lock as lock_mod

        self.rm = rm
        self.macro_mod = macro_mod
        self.tech_mod = tech_mod
        self.lock_mod = lock_mod

        self._origs = {
            "rm": rm.DB_PATH,
            "macro": macro_mod.DB_PATH,
            "tech": tech_mod.DB_PATH,
            "lock": lock_mod.DB_PATH,
        }
        rm.DB_PATH = self.db_path
        macro_mod.DB_PATH = self.db_path
        tech_mod.DB_PATH = self.db_path
        lock_mod.DB_PATH = self.db_path

        rm.init_storage()

    def tearDown(self):
        self.rm.DB_PATH = self._origs["rm"]
        self.macro_mod.DB_PATH = self._origs["macro"]
        self.tech_mod.DB_PATH = self._origs["tech"]
        self.lock_mod.DB_PATH = self._origs["lock"]
        gc.collect()
        time.sleep(0.05)
        if self.db_path.exists():
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def _insert_ohlc(self, date: str, source: str, *,
                     open_: float, high: float, low: float, close: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_ohlc "
                "(date, source, open, high, low, close, locked_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (date, source, open_, high, low, close, "test"),
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Technical indicators (pure-math but DB-backed)
# ---------------------------------------------------------------------------

class TechnicalIndicatorTests(_DBBackedTest):
    def test_atr14_insufficient_data(self):
        from tools.technicals import atr14
        for i in range(10):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", open_=100, high=102, low=99, close=101)
        self.assertIsNone(atr14("2026-04-30", "sge"))

    def test_atr14_known_constant_range(self):
        """If TR is constant 2.0 every day, ATR(14) must equal 2.0."""
        from tools.technicals import atr14
        # 15 rows: prev_close==close so TR = high - low = 2.0 each
        for i in range(15):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", open_=100, high=101, low=99, close=100)
        result = atr14("2026-04-15", "sge")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 2.0, places=4)

    def test_rsi14_extreme_uptrend(self):
        from tools.technicals import rsi14
        for i in range(15):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            close = 100 + i  # monotonic up
            self._insert_ohlc(day, "sge", open_=close, high=close + 1, low=close - 1, close=close)
        result = rsi14("2026-04-15", "sge")
        self.assertIsNotNone(result)
        self.assertEqual(result, 100.0)

    def test_dist_from_ma20_z_zero_sigma_returns_none(self):
        from tools.technicals import dist_from_ma20_z
        # 20 identical closes → σ = 0 → None (avoid divide-by-zero noise)
        for i in range(20):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", open_=100, high=100, low=100, close=100)
        self.assertIsNone(dist_from_ma20_z("2026-04-20", "sge"))

    def test_dist_from_ma20_z_known_value(self):
        from tools.technicals import dist_from_ma20_z
        closes = [100.0] * 19 + [110.0]   # 19 at 100, last at 110 → σ ≈ 2.179, z ≈ 4.359
        for i, c in enumerate(closes):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", open_=c, high=c, low=c, close=c)
        z = dist_from_ma20_z("2026-04-20", "sge")
        self.assertIsNotNone(z)
        self.assertGreater(z, 4.0)

    def test_realized_vol_20d_zero_for_flat(self):
        from tools.technicals import realized_vol_20d
        for i in range(21):
            day = (datetime(2026, 4, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
            self._insert_ohlc(day, "sge", open_=100, high=100, low=100, close=100)
        self.assertEqual(realized_vol_20d("2026-04-21", "sge"), 0.0)


# ---------------------------------------------------------------------------
# Macro fetchers (FRED) — mock urllib.request.urlopen
# ---------------------------------------------------------------------------

def _fake_fred_response(rows: list[tuple[str, str]]):
    csv_lines = ["DATE,DTWEXBGS"] + [f"{d},{v}" for d, v in rows]
    body = "\n".join(csv_lines).encode("utf-8")

    class _Resp:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _Resp(body)


class MacroFetcherTests(_DBBackedTest):
    def _fred_rows_decreasing(self):
        # Date asc; latest=130, 5d earlier=125 → +4% change_5d
        return [
            ("2026-05-01", "125.0"),
            ("2026-05-02", "126.0"),
            ("2026-05-03", "127.0"),
            ("2026-05-04", "128.0"),
            ("2026-05-05", "129.0"),
            ("2026-05-06", "130.0"),
        ]

    def test_dxy_cache_hit(self):
        from tools import macro
        rows = self._fred_rows_decreasing()
        with patch("urllib.request.urlopen", return_value=_fake_fred_response(rows)) as mock_fetch:
            first = macro.fetch_dxy_proxy()
            self.assertFalse(first["missing"])
            self.assertEqual(first["value"], 130.0)
            self.assertAlmostEqual(first["change_5d_pct"], (130 - 125) / 125 * 100, places=4)
            self.assertEqual(mock_fetch.call_count, 1)
            second = macro.fetch_dxy_proxy()
            # second call MUST NOT hit network (within TTL)
            self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(first["fetched_at"], second["fetched_at"])

    def test_dxy_failure_degrades_to_missing(self):
        from tools import macro
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = macro.fetch_dxy_proxy(force_refresh=True)
        self.assertTrue(result["missing"])
        self.assertIsNone(result["value"])
        self.assertIsNone(result["change_5d_pct"])
        self.assertIn("OSError", result.get("reason", ""))

    def test_historical_lookup_returns_latest_at_or_before(self):
        from tools import macro
        # Pre-populate macro_history with ≥6 rows ≤ target so change_5d_pct is computable
        macro._ensure_tables()
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO macro_history (series_id, date, value) VALUES (?, ?, ?)",
                [
                    ("DTWEXBGS", "2026-04-23", 117.0),
                    ("DTWEXBGS", "2026-04-24", 118.0),
                    ("DTWEXBGS", "2026-04-25", 119.0),
                    ("DTWEXBGS", "2026-04-26", 120.0),
                    ("DTWEXBGS", "2026-04-27", 121.0),
                    ("DTWEXBGS", "2026-04-28", 122.0),
                    ("DTWEXBGS", "2026-04-29", 123.0),
                    ("DTWEXBGS", "2026-04-30", 124.0),
                    ("DTWEXBGS", "2026-05-01", 125.0),
                ],
            )
            conn.commit()
        # Asking for 2026-04-29 should return value at 2026-04-29 = 123.0,
        # NOT the latest 125.0 — that would be lookahead leakage.
        result = macro.fetch_dxy_proxy_historical("2026-04-29")
        self.assertFalse(result["missing"])
        self.assertEqual(result["value"], 123.0)
        self.assertEqual(result["value_date"], "2026-04-29")
        # change_5d: latest 123 vs 5 trading days back (2026-04-24 = 118) → +4.24%
        self.assertAlmostEqual(result["change_5d_pct"], (123 - 118) / 118 * 100, places=2)


# ---------------------------------------------------------------------------
# daily_lock — mock akshare via patching tools.gold_history.fetch_single_day
# ---------------------------------------------------------------------------

class DailyLockTests(_DBBackedTest):
    def test_lock_idempotent(self):
        from chains import daily_lock
        fake_sge = {"date": "2026-05-08", "open": 1000.0, "high": 1010.0,
                    "low": 995.0, "close": 1005.0, "volume": None}
        fake_comex = {"date": "2026-05-08", "open": 2400.0, "high": 2420.0,
                      "low": 2395.0, "close": 2410.0, "volume": 12345.0}

        def _fake_fetch(date, source):
            return fake_sge if source == "sge" else fake_comex

        with patch("chains.daily_lock.fetch_single_day", side_effect=_fake_fetch):
            first = daily_lock.lock_daily_ohlc("2026-05-08")
            self.assertEqual(first["inserted"], {"sge": 1, "comex": 1})
            second = daily_lock.lock_daily_ohlc("2026-05-08")
            self.assertEqual(second["inserted"], {"sge": 0, "comex": 0})
            self.assertEqual(second["skipped"], {"sge": 1, "comex": 1})
            self.assertEqual(second["errors"], [])

    def test_lock_records_errors_when_upstream_empty(self):
        from chains import daily_lock
        with patch("chains.daily_lock.fetch_single_day", return_value=None):
            result = daily_lock.lock_daily_ohlc("2026-05-08")
        self.assertEqual(result["inserted"], {"sge": 0, "comex": 0})
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(all("upstream has no row" in e for e in result["errors"]))

    def test_lock_no_fallback_outside_post_close_window(self):
        """akshare miss + intraday clock (same day): the huilv live fallback is a
        mid-session quote — locking it would be permanent (INSERT OR IGNORE).
        Must record errors instead of inserting."""
        from zoneinfo import ZoneInfo
        from chains import daily_lock

        # 2026-05-08 is a Friday; 14:00 Beijing is mid day-session (outside 02:30–09:00).
        intraday = datetime(2026, 5, 8, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch("chains.daily_lock.fetch_single_day", return_value=None), \
                patch("chains.daily_lock.beijing_now", return_value=intraday), \
                patch("tools.market_time.beijing_now", return_value=intraday):
            result = daily_lock.lock_daily_ohlc("2026-05-08")

        self.assertEqual(result["inserted"], {"sge": 0, "comex": 0})
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(all("upstream has no row" in e for e in result["errors"]))
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM daily_ohlc WHERE date='2026-05-08'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_lock_uses_fallback_inside_post_close_window(self):
        """In the 02:30–09:00 window, an akshare miss for TODAY may still lock the
        huilv live quote (live price == today's close in this window)."""
        from zoneinfo import ZoneInfo
        from chains import daily_lock

        # 2026-05-08 is a Friday; 03:05 Beijing is the lock cron — inside the window.
        post_close = datetime(2026, 5, 8, 3, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch("chains.daily_lock.fetch_single_day", return_value=None), \
                patch("chains.daily_lock.beijing_now", return_value=post_close), \
                patch("tools.market_time.beijing_now", return_value=post_close), \
                patch("tools.gold_close.fetch_sge_close", return_value=1005.0), \
                patch("tools.gold_close.fetch_comex_close", return_value=2410.0):
            result = daily_lock.lock_daily_ohlc("2026-05-08")

        self.assertEqual(result["inserted"], {"sge": 1, "comex": 1})
        self.assertEqual(result["errors"], [])
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT close FROM daily_ohlc WHERE date='2026-05-08' AND source='sge'"
            ).fetchone()
        self.assertEqual(row[0], 1005.0)


# ---------------------------------------------------------------------------
# Prompt + payload integration
# ---------------------------------------------------------------------------

class PromptIntegrationTests(unittest.TestCase):
    def test_prompt_template_v4_renders_with_all_fields(self):
        """Every {placeholder} in the v4 template must be supplied; missing
        keys would raise KeyError when LangChain calls .format()."""
        from prompts.daily_prompt import build_daily_prompt, PROMPT_VERSION
        self.assertEqual(PROMPT_VERSION, "daily-v4-regime-tilt")
        template = build_daily_prompt()
        sample = {
            "prediction_date": "2026-05-10",
            "today_close_sge": "780.00 CNY/g",
            "today_close_comex": "2400.00 USD/oz",
            "close_spread": "差 +0 CNY/oz",
            "today_direction_hint": "震荡",
            "regime_label": "choppy",
            "accuracy_window_30d": "55.0%",
            "calibration_buckets": "样本不足",
            "recent_miss_pattern": "暂未识别",
            "recent_predictions": "暂无历史预测记录",
            "recent_distribution": "近 24h 无 30 分钟分析记录",
            "news_text": "无新闻",
            "dxy_value": "118.39 (截至 2026-05-08)",
            "dxy_5d_change": "+0.30%",
            "us10y_real": "1.96% (截至 2026-05-07)",
            "us10y_5d_change": "-0.05%",
            "atr14_sge": "5.2 CNY/g",
            "rsi14_sge": "52",
            "dist_ma20_z_sge": "0.34σ",
        }
        # If any field is missing, format_messages will raise KeyError.
        msgs = template.format_messages(**sample)
        self.assertGreaterEqual(len(msgs), 2)
        rendered = "".join(m.content for m in msgs)
        self.assertIn("广义美元指数", rendered)
        self.assertIn("RSI(14)", rendered)
        self.assertIn("118.39", rendered)
        # 铁律 5 + 6 + 7 must be present
        self.assertIn("铁律", rendered)
        self.assertIn("超买/超卖闸门", rendered)
        self.assertIn("Regime 倾斜", rendered)
        self.assertIn("choppy", rendered)

    def test_build_payload_includes_phase2_fields(self):
        from chains.daily_runner import _build_payload
        from schemas import AccuracySnapshot, RegimeLabel, Trend

        empty_acc = AccuracySnapshot(
            window_days=30, total_predictions=0, verified_predictions=0,
            correct_predictions=0, overall_accuracy=0.0,
        )
        payload = _build_payload(
            prediction_date="2026-05-10",
            sge=780.0,
            comex=2400.0,
            today_direction=Trend.FLAT,
            accuracy=empty_acc,
            recent_predictions=[],
            news_text="无",
            distribution_text="无",
            dxy={"value": 118.39, "change_5d_pct": 0.3, "value_date": "2026-05-08", "missing": False},
            us10y={"value": 1.96, "change_5d_pct": -0.05, "value_date": "2026-05-07", "missing": False},
            atr14_value=5.2,
            rsi14_value=52.0,
            dist_ma20_z_value=0.34,
            regime=RegimeLabel.CHOPPY,
        )
        # 11 base + 7 phase2 + 1 regime = 19
        self.assertEqual(len(payload), 19)
        for key in ("dxy_value", "dxy_5d_change", "us10y_real", "us10y_5d_change",
                    "atr14_sge", "rsi14_sge", "dist_ma20_z_sge", "regime_label"):
            self.assertIn(key, payload)
        self.assertEqual(payload["regime_label"], "choppy")

    def test_build_payload_handles_missing_macro(self):
        from chains.daily_runner import _build_payload
        from schemas import AccuracySnapshot, RegimeLabel, Trend

        empty_acc = AccuracySnapshot(
            window_days=30, total_predictions=0, verified_predictions=0,
            correct_predictions=0, overall_accuracy=0.0,
        )
        payload = _build_payload(
            prediction_date="2026-05-10",
            sge=None, comex=None,
            today_direction=Trend.UNKNOWN,
            accuracy=empty_acc,
            recent_predictions=[],
            news_text="无",
            distribution_text="无",
            dxy={"value": None, "change_5d_pct": None, "missing": True},
            us10y={"value": None, "change_5d_pct": None, "missing": True},
            atr14_value=None, rsi14_value=None, dist_ma20_z_value=None,
            regime=RegimeLabel.UNKNOWN,
        )
        self.assertEqual(payload["dxy_value"], "数据源不可达，本次不参考")
        self.assertEqual(payload["dxy_5d_change"], "数据不足")
        self.assertEqual(payload["atr14_sge"], "数据不足，本次不参考")
        self.assertEqual(payload["regime_label"], "unknown")


if __name__ == "__main__":
    unittest.main()
