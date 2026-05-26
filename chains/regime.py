"""Phase 1 regime classifier — dual-source SGE + COMEX.

Classifies the market state at end_date into one of {bull, bear, choppy, transition,
unknown}. Both sources must agree on a non-transition label; if they disagree,
the regime is `transition`. If either source has fewer than 20 trading days
behind end_date in `daily_ohlc`, regime is `unknown`.

Why dual-source: the user explicitly asked for SGE + COMEX agreement to flag
intra-source disagreement (e.g., during USD/CNY shocks where one market moves
on FX rather than gold fundamentals). Single-source classification can be added
later by exposing classify_single() if needed.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from contextlib import closing

from schemas import RegimeLabel
from storage.record_manager import DB_PATH


logger = logging.getLogger(__name__)


_LONG_WINDOW = 30
_SHORT_WINDOW = 5
_MIN_SAMPLES = 20

_BULL_LONG_DRIFT = 0.05
_BULL_SHORT_DRIFT = 0.015
_BEAR_LONG_DRIFT = -0.05
_BEAR_SHORT_DRIFT = -0.015
_CHOPPY_VOL_CEILING = 0.12
_CHOPPY_DRIFT_CEILING = 0.03
_TRADING_DAYS_PER_YEAR = 252


def classify_regime(end_date: str) -> RegimeLabel:
    """Dual-source regime classification.

    SGE and COMEX must independently agree on the same label (one of bull, bear,
    choppy). Disagreement → transition. Insufficient data on either source → unknown.
    """
    sge = _classify_single(end_date, "sge")
    comex = _classify_single(end_date, "comex")
    if sge is RegimeLabel.UNKNOWN or comex is RegimeLabel.UNKNOWN:
        return RegimeLabel.UNKNOWN
    if sge == comex:
        return sge
    return RegimeLabel.TRANSITION


def _classify_single(end_date: str, source: str) -> RegimeLabel:
    closes = _fetch_closes(end_date, source, _LONG_WINDOW)
    if len(closes) < _MIN_SAMPLES:
        return RegimeLabel.UNKNOWN

    long_drift = (closes[0] - closes[-1]) / closes[-1] if closes[-1] else 0.0
    short_drift = 0.0
    if len(closes) > _SHORT_WINDOW:
        anchor = closes[_SHORT_WINDOW]
        if anchor:
            short_drift = (closes[0] - anchor) / anchor

    daily_returns: list[float] = []
    for i in range(len(closes) - 1):
        prev = closes[i + 1]
        cur = closes[i]
        if prev and cur and prev > 0 and cur > 0:
            daily_returns.append(math.log(cur / prev))

    realized_vol = 0.0
    if len(daily_returns) >= 2:
        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        realized_vol = math.sqrt(variance) * math.sqrt(_TRADING_DAYS_PER_YEAR)

    if long_drift > _BULL_LONG_DRIFT and short_drift > _BULL_SHORT_DRIFT:
        return RegimeLabel.BULL
    if long_drift < _BEAR_LONG_DRIFT and short_drift < _BEAR_SHORT_DRIFT:
        return RegimeLabel.BEAR
    if realized_vol < _CHOPPY_VOL_CEILING and abs(long_drift) < _CHOPPY_DRIFT_CEILING:
        return RegimeLabel.CHOPPY
    return RegimeLabel.TRANSITION


def _fetch_closes(end_date: str, source: str, limit: int) -> list[float]:
    """Most recent `limit` close values on or before end_date for the given source.
    Order: newest first."""
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT close FROM daily_ohlc
                 WHERE source = ? AND date <= ? AND close IS NOT NULL
                 ORDER BY date DESC
                 LIMIT ?
                """,
                (source, end_date, limit),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        # daily_ohlc may not exist yet on a fresh DB; treat as no samples.
        logger.info("regime: daily_ohlc query failed source=%s err=%s", source, exc)
        return []
    return [float(row["close"]) for row in rows if row["close"] is not None]
