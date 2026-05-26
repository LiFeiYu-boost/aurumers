"""Trivial direction baselines used as honest comparators for the LLM.

Both functions return a Trend enum ('上涨' / '下跌' / '震荡' / '未知').
They are computed at predict time, persisted alongside the model prediction,
and verified by the same code path that verifies the model — so 30 days from
now we can report "Aurumers X% vs persistence Y% vs MA(5) Z%" with the same
denominator across all three.

Why these two:
- persistence ≈ "tomorrow's direction is today's direction". This is the
  honest weak-baseline: in a trending market it wins easily; in a choppy
  market it loses.
- ma(5) ≈ "today's close above/below 5-day MA implies tomorrow continuation".
  Mirror weakness: it lags trend reversals but tracks regime well.

Together they bracket what trivial logic can do, which is the right reference
for asking "does the LLM pipeline add anything?".

The threshold for FLAT is ±0.15% of the reference value, matching
chains/daily_runner.py:_decide_today_direction so the three predictions are
on equal footing.

Unit safety: ``predict_ma5`` requires the caller to pass ``source`` matching
the source of ``today_close``. SGE quotes CNY/g, COMEX quotes USD/oz — mixing
silently produces nonsense direction calls. See daily_runner._pick_same_source_anchor.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime

from schemas import Trend
from storage.record_manager import DB_PATH


_MA_WINDOW = 5
# If the freshest OHLC close is older than this many days vs prediction_date,
# the MA is computed against stale history and comparing to today's live close
# becomes apples-to-oranges → refuse to give a direction. 5 days accommodates
# a weekend + one holiday (typical post-holiday Monday/Tuesday) without
# spuriously degrading. Anything longer than that is genuinely stale data.
_MA_MAX_STALENESS_DAYS = 5


def predict_persistence(today_direction: Trend) -> Trend:
    """Tomorrow's direction = today's direction. UNKNOWN if today is unknown."""
    if today_direction is Trend.UNKNOWN:
        return Trend.UNKNOWN
    return today_direction


def _recent_closes(
    prediction_date: str, source: str, limit: int
) -> list[tuple[str, float]]:
    """Return up to ``limit`` newest (date, close) pairs strictly before prediction_date.

    Lookahead-safe: ``date < prediction_date``, **not** ``<=``. In live mode
    today's close has not been written to daily_ohlc yet, so this distinction
    is a no-op. In historical_mode the OHLC table already contains the target
    day — including it in the MA would leak today into its own baseline.
    """
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT date, close FROM daily_ohlc
                 WHERE source = ? AND date < ? AND close IS NOT NULL
                 ORDER BY date DESC
                 LIMIT ?
                """,
                (source, prediction_date, limit),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(row["date"], float(row["close"])) for row in rows]


def predict_ma5(
    today_close: float | None,
    prediction_date: str,
    *,
    source: str,
) -> Trend:
    """Direction = sign(today_close - MA(5)) with ±0.15% deadband.

    ``source`` must match the source of ``today_close`` (sge vs comex). Caller
    is responsible — mixing units silently degrades the baseline.

    Returns UNKNOWN when:
    - ``today_close`` is None
    - ``source`` is not 'sge' or 'comex'
    - fewer than 5 closes exist in daily_ohlc for ``source`` strictly before
      ``prediction_date``
    - the freshest OHLC close is more than ``_MA_MAX_STALENESS_DAYS`` (5)
      days older than ``prediction_date`` (stale fill cron → comparing live
      close vs week-old MA is meaningless)
    """
    if today_close is None or source not in {"sge", "comex"}:
        return Trend.UNKNOWN
    pairs = _recent_closes(prediction_date, source, limit=_MA_WINDOW)
    if len(pairs) < _MA_WINDOW:
        return Trend.UNKNOWN

    latest_date, _ = pairs[0]
    try:
        pred_dt = datetime.strptime(prediction_date, "%Y-%m-%d")
        latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
    except ValueError:
        return Trend.UNKNOWN
    if (pred_dt - latest_dt).days > _MA_MAX_STALENESS_DAYS:
        return Trend.UNKNOWN

    ma5 = sum(c for _, c in pairs) / _MA_WINDOW
    threshold = max(ma5 * 0.0015, 0.5)
    delta = today_close - ma5
    if delta > threshold:
        return Trend.UP
    if delta < -threshold:
        return Trend.DOWN
    return Trend.FLAT
