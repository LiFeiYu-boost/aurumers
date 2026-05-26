import os
import unittest
from datetime import datetime, time as dtime
from unittest.mock import patch

os.environ.setdefault("MOCK_LLM", "1")
os.environ.setdefault("DASHSCOPE_API_KEY", "mock")
os.environ.setdefault("DASHSCOPE_BASE_URL", "mock")

from chains import scheduler


class SchedulerWallClockTests(unittest.TestCase):
    def test_next_fire_today_when_in_future(self):
        now = datetime(2026, 5, 9, 1, 0, 0)
        target = scheduler._next_fire(dtime(2, 50), now=now)
        self.assertEqual(target.year, 2026)
        self.assertEqual(target.month, 5)
        self.assertEqual(target.day, 9)
        self.assertEqual(target.hour, 2)
        self.assertEqual(target.minute, 50)

    def test_next_fire_tomorrow_when_already_past(self):
        now = datetime(2026, 5, 9, 5, 0, 0)
        target = scheduler._next_fire(dtime(2, 50), now=now)
        self.assertEqual(target.day, 10)

    def test_next_fire_exactly_at(self):
        now = datetime(2026, 5, 9, 2, 50, 0)
        # equal -> rolls to tomorrow (we use <=)
        target = scheduler._next_fire(dtime(2, 50), now=now)
        self.assertEqual(target.day, 10)


class SchedulerNowBeijingTests(unittest.TestCase):
    def test_now_returns_aware_or_naive(self):
        now = scheduler._now_beijing()
        self.assertIsInstance(now, datetime)


if __name__ == "__main__":
    unittest.main()
