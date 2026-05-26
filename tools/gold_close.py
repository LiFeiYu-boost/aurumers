"""Dual-source gold close: SGE Au(T+D) + COMEX GC, both via the sina-mirrored
huilvbiao endpoint that is reliably reachable from mainland China.

The endpoint returns three independent JS-style strings:
- ``hq_str_gds_AUTD`` — SGE Au(T+D) (timestamp 02:30 = SGE night close)
- ``hq_str_hf_GC``    — COMEX gold futures (rolling 23h, settlement carries to next day)
- ``hq_str_hf_XAU``   — London spot (reference)

Field layout (sina convention, 0-indexed):
- 0: latest price
- 1: average price (sometimes blank for futures)
- 2: previous close
- 3: today's open
- 4: today's high
- 5: today's low
- 6: timestamp HH:MM:SS

For the 02:50 Beijing daily prediction (right after SGE night session closes),
field 0 is effectively "today's close." We therefore prefer index 0 over the
"previous close" at index 2.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Iterable

import requests

from schemas import CloseSourceStatus
from tools.gold_price import get_gold_price


logger = logging.getLogger(__name__)


_TIMEOUT = 6
_USER_AGENT = "Mozilla/5.0 (aurumers/1.1)"
_HUILV_URL = "https://www.huilvbiao.com/api/gold_indexApi"


def _is_mock() -> bool:
    raw = os.getenv("MOCK_LLM", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _safe_get(url: str, *, params: dict[str, Any] | None = None) -> requests.Response | None:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.huilvbiao.com/",
    }
    for attempt in (1, 2):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=_TIMEOUT)
            response.raise_for_status()
            return response
        except Exception as exc:
            if attempt == 2:
                logger.info("close fetch failed url=%s err=%s", url, exc)
                return None
            time.sleep(0.4)
    return None


def _fetch_huilv() -> dict[str, list[str]]:
    """Single round-trip fetching all three sina-mirror series at once."""
    response = _safe_get(_HUILV_URL, params={"t": int(time.time() * 1000)})
    if response is None:
        return {}
    text = response.text or ""
    out: dict[str, list[str]] = {}
    for match in re.finditer(r'hq_str_([a-zA-Z0-9_]+)\s*=\s*"([^"]+)"', text):
        key = match.group(1)
        fields = match.group(2).split(",")
        if fields:
            out[key] = fields
    return out


def _parse_close(fields: Iterable[str]) -> float | None:
    arr = list(fields)
    for index in (0, 2):
        if index >= len(arr):
            continue
        raw = arr[index].strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 0:
            return round(value, 4)
    return None


def fetch_sge_close(date: str | None = None) -> float | None:
    """SGE Au(T+D) close. Returns None on any failure."""
    if _is_mock():
        return _mock_close(date or datetime.now().strftime("%Y-%m-%d"), salt="sge")
    series = _fetch_huilv()
    fields = series.get("gds_AUTD")
    if not fields:
        return None
    return _parse_close(fields)


def fetch_comex_close(date: str | None = None) -> float | None:
    """COMEX gold (GC) close. Returns None on any failure."""
    if _is_mock():
        return _mock_close(date or datetime.now().strftime("%Y-%m-%d"), salt="comex")
    series = _fetch_huilv()
    fields = series.get("hf_GC")
    if not fields:
        return None
    return _parse_close(fields)


def fetch_dual_close(date: str | None = None) -> tuple[float | None, float | None, CloseSourceStatus]:
    """Single-shot fetch returning (sge, comex, status). Both sources share one
    HTTP round-trip — keeps the daily run fast and the rate limit polite.
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    if _is_mock():
        sge = _mock_close(target_date, salt="sge")
        comex = _mock_close(target_date, salt="comex")
    else:
        series = _fetch_huilv()
        sge = _parse_close(series.get("gds_AUTD") or [])
        comex = _parse_close(series.get("hf_GC") or [])

    if sge is not None and comex is not None:
        status = CloseSourceStatus.BOTH
    elif sge is not None:
        status = CloseSourceStatus.SGE_ONLY
    elif comex is not None:
        status = CloseSourceStatus.COMEX_ONLY
    else:
        status = CloseSourceStatus.NEITHER
    return sge, comex, status


def _mock_close(date: str, *, salt: str) -> float | None:
    """Deterministic pseudo-close for Mock mode based on live spot ± offset."""
    spot = get_gold_price()
    try:
        base = float(spot)
    except (TypeError, ValueError):
        base = 2400.0
    seed = int(hashlib.md5(f"{date}|{salt}".encode("utf-8")).hexdigest()[:6], 16)
    bias = (seed % 1001) / 100.0 - 5.0
    if salt == "comex":
        bias *= 0.6
    return round(base + bias, 2)


def fetch_dual_close_from_ohlc(date: str) -> tuple[float | None, float | None, CloseSourceStatus]:
    """Read SGE + COMEX close from the locked daily_ohlc table.

    Lookahead-safe: daily_ohlc is INSERT-OR-IGNORE only, never rewritten by the
    scraper, so the value is what was true at lock time and remains stable.
    Used for historical backtest pipelines and for verifier when checking past
    predictions against past closes.
    """
    import sqlite3
    from contextlib import closing

    from storage.record_manager import DB_PATH

    try:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            sge_row = conn.execute(
                "SELECT close FROM daily_ohlc WHERE date=? AND source='sge' LIMIT 1",
                (date,),
            ).fetchone()
            comex_row = conn.execute(
                "SELECT close FROM daily_ohlc WHERE date=? AND source='comex' LIMIT 1",
                (date,),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        logger.info("ohlc fetch failed date=%s err=%s", date, exc)
        return None, None, CloseSourceStatus.NEITHER

    sge = float(sge_row["close"]) if sge_row and sge_row["close"] is not None else None
    comex = float(comex_row["close"]) if comex_row and comex_row["close"] is not None else None
    if sge is not None and comex is not None:
        status = CloseSourceStatus.BOTH
    elif sge is not None:
        status = CloseSourceStatus.SGE_ONLY
    elif comex is not None:
        status = CloseSourceStatus.COMEX_ONLY
    else:
        status = CloseSourceStatus.NEITHER
    return sge, comex, status


__all__ = ["fetch_sge_close", "fetch_comex_close", "fetch_dual_close", "fetch_dual_close_from_ohlc"]
