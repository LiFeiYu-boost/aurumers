"""Phase 2 03:05 cron — lock today's SGE + COMEX OHLC into daily_ohlc.

Why a separate cron at 03:05:
- 02:50 daily prediction runs first and reads `today_close` from huilvbiao live
  endpoint (a different source from akshare).
- 03:05 then snapshots the akshare-supplied OHLC for the same day so technical
  indicators on the next 02:50 run have a deterministic, locked-in series.
- 03:10 verifier runs after — it queries daily_ohlc for next-day close, so
  this cron must complete before then.

Lock semantics: ``INSERT OR IGNORE``. Already-locked (date, source) rows are
never overwritten. To correct a value, delete the row in SQL and re-run.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Iterable

from storage.record_manager import DB_PATH, init_storage
from tools.gold_history import (
    fetch_single_day,
    insert_ohlc_row,
    load_existing_dates,
)
from tools.market_time import beijing_now, is_post_close_window


logger = logging.getLogger(__name__)


SOURCES: tuple[str, ...] = ("sge", "comex")


def lock_daily_ohlc(
    target_date: str | None = None,
    *,
    sources: Iterable[str] = SOURCES,
) -> dict:
    """Lock the OHLC row for ``target_date`` (default today) for each source.

    Returns ``{"date": ..., "inserted": {sge: 0/1, comex: 0/1}, "skipped": {...},
    "errors": [...]}``. Network or upstream parsing errors are captured per
    source and logged but never raised — this cron must be best-effort.
    """
    target = target_date or datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.strptime(target, "%Y-%m-%d").weekday()
    if weekday >= 5:
        logger.info("daily_lock weekend skip for %s (weekday=%d)", target, weekday)
        return {
            "date": target,
            "inserted": {s: 0 for s in sources},
            "skipped": {s: 0 for s in sources},
            "errors": ["weekend_skip"],
        }
    init_storage()
    locked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted: dict[str, int] = {s: 0 for s in sources}
    skipped: dict[str, int] = {s: 0 for s in sources}
    errors: list[str] = []

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        for source in sources:
            try:
                existing = load_existing_dates(conn, source)
                if target in existing:
                    skipped[source] = 1
                    continue
                row = fetch_single_day(target, source)
                if row is None:
                    # The huilv fallback is the LIVE quote — valid as target's close
                    # only when target is today AND we're in the post-close window
                    # (weekday 02:30–09:00 Beijing). Outside that, writing it would
                    # permanently lock an intraday / wrong-day price (INSERT OR
                    # IGNORE rows are never rewritten).
                    fb_close = None
                    if target == beijing_now().strftime("%Y-%m-%d") and is_post_close_window():
                        from tools.gold_close import fetch_sge_close, fetch_comex_close
                        fb_close = fetch_sge_close(target) if source == "sge" else fetch_comex_close(target)
                    if fb_close is not None:
                        row = {"date": target, "open": None, "high": None, "low": None, "close": fb_close, "volume": None}
                        logger.warning("daily_lock %s %s: akshare miss, used huilv fallback close=%s", source, target, fb_close)
                    else:
                        errors.append(f"{source}: upstream has no row for {target}")
                        continue
                insert_ohlc_row(conn, source, row, locked_at)
                inserted[source] = 1
            except Exception as exc:
                errors.append(f"{source}: {type(exc).__name__}: {exc}")
                logger.exception("daily_lock %s for %s failed", source, target)
        conn.commit()

    result = {
        "date": target,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info("daily_lock result: %s", result)
    return result


__all__ = ["lock_daily_ohlc"]
