"""Phase 2 technical indicators computed from the locked daily_ohlc table.

All functions are lookahead-safe by construction: every query restricts rows
to ``date <= prediction_date``. The daily_ohlc table itself is INSERT OR
IGNORE only, so historical values cannot be revised by the live pipeline —
that property is what makes "yesterday's RSI" meaningful when we ask the LLM
to reason about a past day.

Public API:
- ``atr14(prediction_date, source)``           — Wilder Average True Range
- ``rsi14(prediction_date, source)``           — Wilder Relative Strength Index
- ``dist_from_ma20_z(prediction_date, source)`` — z-score of close vs MA20
- ``realized_vol_20d(prediction_date, source)`` — annualised log-return σ

Each returns ``float | None``; ``None`` means insufficient data (the daily
runner renders this as "数据不足，本次不参考" rather than crashing).
"""
from __future__ import annotations

import logging
import math
import sqlite3
from contextlib import closing
from typing import Sequence

from storage.record_manager import DB_PATH


logger = logging.getLogger(__name__)


_TRADING_DAYS_PER_YEAR = 252
_RSI_PERIOD = 14
_ATR_PERIOD = 14
_MA_WINDOW = 20


def _fetch_ohlc(
    prediction_date: str, source: str, limit: int
) -> list[tuple[str, float | None, float | None, float | None, float]]:
    """Return rows ``(date, open, high, low, close)`` newest first.

    Filters out rows where close is NULL; open/high/low may still be None and
    callers handle that. Restricts to ``date <= prediction_date``.
    """
    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT date, open, high, low, close FROM daily_ohlc
                 WHERE source = ? AND date <= ? AND close IS NOT NULL
                 ORDER BY date DESC
                 LIMIT ?
                """,
                (source, prediction_date, limit),
            ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.info("technicals: daily_ohlc query failed source=%s err=%s", source, exc)
        return []
    return [
        (
            row["date"],
            row["open"],
            row["high"],
            row["low"],
            float(row["close"]),
        )
        for row in rows
    ]


def _closes_only(prediction_date: str, source: str, limit: int) -> list[float]:
    return [r[4] for r in _fetch_ohlc(prediction_date, source, limit)]


def atr14(prediction_date: str, source: str = "sge") -> float | None:
    """Wilder ATR(14). Needs 15 OHLC rows (14 TRs + 1 prior close). Returns
    None if any high/low/close in the window is missing."""
    rows = _fetch_ohlc(prediction_date, source, _ATR_PERIOD + 1)
    if len(rows) < _ATR_PERIOD + 1:
        return None
    rows_asc = list(reversed(rows))
    true_ranges: list[float] = []
    for i in range(1, len(rows_asc)):
        _, _, hi, lo, close = rows_asc[i]
        prev_close = rows_asc[i - 1][4]
        if hi is None or lo is None or prev_close is None:
            return None
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        true_ranges.append(tr)
    if len(true_ranges) < _ATR_PERIOD:
        return None
    return round(sum(true_ranges[-_ATR_PERIOD:]) / _ATR_PERIOD, 4)


def rsi14(prediction_date: str, source: str = "sge") -> float | None:
    """Wilder RSI(14). Needs 15 closes (14 deltas)."""
    closes = _closes_only(prediction_date, source, _RSI_PERIOD + 1)
    if len(closes) < _RSI_PERIOD + 1:
        return None
    closes_asc = list(reversed(closes))
    gains = 0.0
    losses = 0.0
    for i in range(1, len(closes_asc)):
        diff = closes_asc[i] - closes_asc[i - 1]
        if diff > 0:
            gains += diff
        elif diff < 0:
            losses -= diff
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / _RSI_PERIOD) / (losses / _RSI_PERIOD)
    return round(100.0 - 100.0 / (1.0 + rs), 2)


def dist_from_ma20_z(prediction_date: str, source: str = "sge") -> float | None:
    """Z-score of latest close relative to 20-day MA and σ.

    Returns ``None`` when σ_20 ≈ 0 (degenerate flat market) — there is no
    meaningful distance to report and the prompt should fall back to the
    "data insufficient" message rather than print a misleading 0.
    """
    closes = _closes_only(prediction_date, source, _MA_WINDOW)
    if len(closes) < _MA_WINDOW:
        return None
    ma = sum(closes) / _MA_WINDOW
    var = sum((c - ma) ** 2 for c in closes) / _MA_WINDOW
    sigma = math.sqrt(var)
    if sigma <= 1e-9:
        return None
    return round((closes[0] - ma) / sigma, 3)


def atr14_percentile(
    prediction_date: str,
    source: str = "sge",
    window: int = 60,
) -> float | None:
    """Percentile rank of today's ATR(14) within the last `window` trading days.

    Returns a float in [0, 1] where 0.0 = today is the lowest ATR observed in
    the window and 1.0 = today is the highest. Used by the flat-gate to detect
    low-volatility regimes (where a "震荡" call is more defensible).

    Returns None if fewer than ``window // 2`` distinct ATR samples can be
    computed — degraded data must fall through rather than mislead the gate.
    """
    if window < 5:
        return None
    rows = _fetch_ohlc(prediction_date, source, window + _ATR_PERIOD)
    if len(rows) < _ATR_PERIOD + 2:
        return None

    # Compute the full TR series in chronological order so the rolling ATR is
    # cheap. Each TR depends on the prior close, so the first row has no TR.
    rows_asc = list(reversed(rows))
    true_ranges: list[float] = []
    for i in range(1, len(rows_asc)):
        _, _, hi, lo, close = rows_asc[i]
        prev_close = rows_asc[i - 1][4]
        if hi is None or lo is None or prev_close is None:
            return None
        true_ranges.append(max(hi - lo, abs(hi - prev_close), abs(lo - prev_close)))
    if len(true_ranges) < _ATR_PERIOD:
        return None

    atr_series: list[float] = []
    for end in range(_ATR_PERIOD, len(true_ranges) + 1):
        atr_series.append(sum(true_ranges[end - _ATR_PERIOD : end]) / _ATR_PERIOD)
    if len(atr_series) < max(5, window // 2):
        return None

    sample = atr_series[-window:]
    today_atr = sample[-1]
    # Rank: fraction of strictly-less values. Ties land mid-range via the
    # average of strict-less and less-or-equal counts.
    n = len(sample)
    less = sum(1 for v in sample if v < today_atr)
    less_eq = sum(1 for v in sample if v <= today_atr)
    return round((less + less_eq) / (2 * n), 4)


def realized_vol_20d(prediction_date: str, source: str = "sge") -> float | None:
    """20-day annualised realised volatility from log returns.

    Sample standard deviation (n-1 denominator) × √252 for an annualised %.
    Returns None if fewer than 21 closes are available (need 20 returns).
    """
    closes = _closes_only(prediction_date, source, _MA_WINDOW + 1)
    if len(closes) < _MA_WINDOW + 1:
        return None
    closes_asc = list(reversed(closes))
    log_returns: list[float] = []
    for i in range(1, len(closes_asc)):
        prev, cur = closes_asc[i - 1], closes_asc[i]
        if prev <= 0 or cur <= 0:
            return None
        log_returns.append(math.log(cur / prev))
    if len(log_returns) < 2:
        return None
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    return round(math.sqrt(variance) * math.sqrt(_TRADING_DAYS_PER_YEAR), 4)


__all__: Sequence[str] = (
    "atr14",
    "atr14_percentile",
    "rsi14",
    "dist_from_ma20_z",
    "realized_vol_20d",
)
