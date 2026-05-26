import unittest

from chains.parser import parse_result
from schemas import Trend


class ParseResultTests(unittest.TestCase):
    def test_parse_valid_json(self):
        payload = '{"summary":"市场偏强","trend":"上涨","reasons":["避险需求上升"],"advice":"谨慎跟踪"}'
        result, error = parse_result(payload)
        self.assertIsNone(error)
        self.assertEqual(result.trend, Trend.UP)
        self.assertEqual(result.reasons, ["避险需求上升"])

    def test_parse_code_fence_json(self):
        payload = """```json
        {"summary":"市场震荡","trend":"震荡","reasons":["多空博弈"],"advice":"保持观望"}
        ```"""
        result, error = parse_result(payload)
        self.assertIsNone(error)
        self.assertEqual(result.trend, Trend.FLAT)
        self.assertEqual(result.summary, "市场震荡")

    def test_parse_invalid_json(self):
        result, error = parse_result("not-json")
        self.assertIsNotNone(error)
        self.assertEqual(result.summary, "暂无总结")

    def test_parse_reason_string(self):
        payload = '{"summary":"市场震荡","trend":"持平","reasons":"- 原因1\\n- 原因2","advice":"观望"}'
        result, error = parse_result(payload)
        self.assertIsNone(error)
        self.assertEqual(result.trend, Trend.FLAT)
        self.assertEqual(result.reasons, ["原因1", "原因2"])

    def test_parse_trend_synonym(self):
        payload = '{"summary":"市场偏弱","trend":"下降","reasons":[],"advice":"谨慎"}'
        result, error = parse_result(payload)
        self.assertIsNone(error)
        self.assertEqual(result.trend, Trend.DOWN)

    def test_parse_confidence_range(self):
        payload = '{"summary":"x","trend":"震荡","reasons":[],"advice":"y","confidence":1.4}'
        result, error = parse_result(payload)
        self.assertIsNone(error)
        self.assertEqual(result.confidence, 1.0)

    def test_parse_confidence_negative(self):
        payload = '{"summary":"x","trend":"震荡","reasons":[],"advice":"y","confidence":-0.2}'
        result, _ = parse_result(payload)
        self.assertEqual(result.confidence, 0.0)

    def test_parse_confidence_missing(self):
        payload = '{"summary":"x","trend":"震荡","reasons":[],"advice":"y"}'
        result, _ = parse_result(payload)
        self.assertIsNone(result.confidence)


if __name__ == "__main__":
    unittest.main()
