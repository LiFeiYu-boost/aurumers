"""Beijing-time market window helpers.

The live quote endpoint (tools.gold_close) ignores its date argument — it only
ever returns the price "right now". That price is a valid proxy for *today's*
close only in the post-close window: after the SGE night session settles at
02:30 Beijing and before the day session opens at 09:00. All three wall-clock
crons (02:50 predict / 03:05 lock / 03:10 verify) fall inside this window;
scheduler cold-start catch-up runs do not, so writers must gate on it.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_BJ_TZ = ZoneInfo("Asia/Shanghai")


def beijing_now() -> datetime:
    return datetime.now(tz=_BJ_TZ)


def is_post_close_window(now: datetime | None = None) -> bool:
    """True iff Beijing weekday 02:30 <= t < 09:00 — when live price == today's close."""
    bj = now.astimezone(_BJ_TZ) if now is not None else beijing_now()
    minutes = bj.hour * 60 + bj.minute
    return bj.weekday() < 5 and (2 * 60 + 30) <= minutes < 9 * 60


__all__ = ["beijing_now", "is_post_close_window"]
