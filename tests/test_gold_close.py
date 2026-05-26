import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")

from schemas import CloseSourceStatus
from tools import gold_close


class GoldCloseTests(unittest.TestCase):
    def test_dual_close_both_sources_succeed(self):
        with patch.object(gold_close, "_is_mock", return_value=False), \
                patch.object(gold_close, "_fetch_huilv", return_value={
                    "gds_AUTD": ["1035.63", "0", "1030.10", "1036.00"],
                    "hf_GC": ["4727.370", "", "4723.300", "4723.700"],
                }):
            sge, comex, status = gold_close.fetch_dual_close("2026-05-09")
        self.assertAlmostEqual(sge, 1035.63, places=4)
        self.assertAlmostEqual(comex, 4727.37, places=2)
        self.assertIs(status, CloseSourceStatus.BOTH)

    def test_dual_close_only_comex(self):
        with patch.object(gold_close, "_is_mock", return_value=False), \
                patch.object(gold_close, "_fetch_huilv", return_value={
                    "hf_GC": ["4727.370", "", "4723.300"],
                }):
            sge, comex, status = gold_close.fetch_dual_close("2026-05-09")
        self.assertIsNone(sge)
        self.assertAlmostEqual(comex, 4727.37, places=2)
        self.assertIs(status, CloseSourceStatus.COMEX_ONLY)

    def test_dual_close_neither(self):
        with patch.object(gold_close, "_is_mock", return_value=False), \
                patch.object(gold_close, "_fetch_huilv", return_value={}):
            sge, comex, status = gold_close.fetch_dual_close("2026-05-09")
        self.assertIsNone(sge)
        self.assertIsNone(comex)
        self.assertIs(status, CloseSourceStatus.NEITHER)

    def test_parse_close_skips_zero_or_blank(self):
        self.assertIsNone(gold_close._parse_close([""]))
        self.assertIsNone(gold_close._parse_close(["0", "0", ""]))
        self.assertIsNone(gold_close._parse_close(["abc", "", "xx"]))
        self.assertEqual(gold_close._parse_close(["100.5", "", ""]), 100.5)

    def test_safe_get_returns_none_on_exception(self):
        with patch("tools.gold_close.requests.get", side_effect=ConnectionError("boom")):
            self.assertIsNone(gold_close._safe_get("https://example.test/x"))

    def test_mock_branch_returns_value(self):
        with patch.dict(os.environ, {"MOCK_LLM": "1"}):
            with patch("tools.gold_close.get_gold_price", return_value="2400.0"):
                value = gold_close.fetch_sge_close("2026-05-09")
        self.assertIsInstance(value, float)
        self.assertGreater(value, 2000)


if __name__ == "__main__":
    unittest.main()
