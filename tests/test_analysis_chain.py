import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from chains.analysis_chain import run_analysis_chain
from config import settings
from schemas import AnalysisInput, NewsItem, Trend


class AnalysisChainTests(unittest.TestCase):
    def setUp(self):
        self.analysis_input = AnalysisInput(
            price_raw="3300.5",
            price_value=3300.5,
            news=[NewsItem(title="黄金短线走强", source="test")],
        )
        self._mock_flag_original = settings.mock_llm
        settings.mock_llm = False

    def tearDown(self):
        settings.mock_llm = self._mock_flag_original

    def test_single_call_returns_valid_json(self):
        call_count = {"count": 0}

        def fake_llm(_):
            call_count["count"] += 1
            return '{"summary":"市场偏强","trend":"上涨","reasons":["避险需求上升"],"advice":"谨慎跟踪"}'

        with patch("chains.analysis_chain.build_llm", return_value=RunnableLambda(fake_llm)):
            result, raw_output, error = run_analysis_chain(self.analysis_input)

        self.assertIsNone(error)
        self.assertEqual(call_count["count"], 1)
        self.assertEqual(result.trend, Trend.UP)
        self.assertIn("市场偏强", raw_output)

    def test_single_call_parses_code_fence_json(self):
        def fake_llm(_):
            return """```json
            {"summary":"市场震荡","trend":"震荡","reasons":["多空拉锯"],"advice":"观望"}
            ```"""

        with patch("chains.analysis_chain.build_llm", return_value=RunnableLambda(fake_llm)):
            result, _, error = run_analysis_chain(self.analysis_input)

        self.assertIsNone(error)
        self.assertEqual(result.trend, Trend.FLAT)

    def test_single_call_records_parse_error(self):
        with patch("chains.analysis_chain.build_llm", return_value=RunnableLambda(lambda _: "plain text only")):
            result, raw_output, error = run_analysis_chain(self.analysis_input)

        self.assertIsNotNone(error)
        self.assertEqual(result.summary, "暂无总结")
        self.assertEqual(raw_output, "plain text only")


if __name__ == "__main__":
    unittest.main()
