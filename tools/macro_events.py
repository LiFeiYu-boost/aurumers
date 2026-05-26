"""Macro event fetchers — akshare US/CN releases + GDELT v2 geopolitical spikes.

Why these sources
-----------------
- akshare US (FOMC, NFP, CPI, PCE, ISM PMI, jobless claims, unemployment) is
  the dominant signal for gold. All return DataFrames with the standard
  schema ``[商品, 日期, 今值, 预测值, 前值]`` so we can normalise uniformly.
- akshare CN (LPR, PMI, CPI) is weaker for gold but gives RMB-side context
  for SGE moves. ``macro_china_lpr`` has a different column layout and gets
  a dedicated branch.
- GDELT v2 ``mode=TimelineVol`` returns daily article volume per query; days
  with > 2σ volume vs rolling mean are tagged as
  ``gdelt_high_attention`` events. This is a noise-tolerant proxy for "the
  world cared more than usual that day."

Output
------
Every fetcher returns ``list[MacroEvent]``. Callers (``scripts/collect_macro_events.py``)
INSERT OR IGNORE into the ``macro_events`` table — duplicate inserts are safe.

Failure mode
------------
A single fetcher failing (akshare CDN outage, GDELT throttling) must NOT
abort the whole collection. Each fetcher catches and logs, returns ``[]``.
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)


@dataclass
class MacroEvent:
    date: str  # YYYY-MM-DD
    event_type: str
    country: str
    importance: int
    actual_value: float | None
    forecast_value: float | None
    prior_value: float | None
    label: str
    raw_payload: dict = field(default_factory=dict)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def _safe_date(value: Any) -> str | None:
    """Coerce many date representations to YYYY-MM-DD."""
    if value is None:
        return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        # pandas may give "2024-01-01 00:00:00"
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%d")
        except ValueError:
            return None
    # pandas Timestamp / datetime
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return None


def _surprise_pct(actual: float | None, forecast: float | None) -> float | None:
    if actual is None or forecast is None:
        return None
    if abs(forecast) < 1e-9:
        return None
    return (actual - forecast) / abs(forecast)


# --------------------------------------------------------------------------
# akshare US
# --------------------------------------------------------------------------

# event_type → (akshare function name, importance, default label)
_US_AK_SOURCES: list[tuple[str, str, int, str]] = [
    ("us_fomc_decision",        "macro_bank_usa_interest_rate",     3, "FOMC 利率决议"),
    ("us_nfp",                  "macro_usa_non_farm",               3, "美国非农就业"),
    ("us_unemployment_rate",    "macro_usa_unemployment_rate",      3, "美国失业率"),
    ("us_cpi_monthly",          "macro_usa_cpi_monthly",            3, "美国 CPI 月率"),
    ("us_core_cpi_monthly",     "macro_usa_core_cpi_monthly",       3, "美国核心 CPI 月率"),
    ("us_core_pce_yy",          "macro_usa_core_pce_price",         3, "美国核心 PCE 物价指数"),
    ("us_ism_pmi",              "macro_usa_ism_pmi",                2, "美国 ISM 制造业 PMI"),
    ("us_initial_jobless",      "macro_usa_initial_jobless",        2, "美国初请失业金"),
    ("us_adp_employment",       "macro_usa_adp_employment",         2, "美国 ADP 就业"),
]


def _fetch_ak_standard(
    fn_name: str,
    event_type: str,
    country: str,
    importance: int,
    default_label: str,
    start: str,
    end: str,
) -> list[MacroEvent]:
    """For akshare functions returning the standard 商品/日期/今值/预测值/前值 schema."""
    try:
        import akshare as ak  # noqa: PLC0415
    except ImportError:
        logger.error("akshare not installed; cannot fetch %s", fn_name)
        return []

    fn: Callable | None = getattr(ak, fn_name, None)
    if fn is None:
        logger.warning("akshare function not found: %s (event_type=%s)", fn_name, event_type)
        return []

    try:
        df = fn()
    except Exception as exc:  # network / upstream / decode failures
        logger.warning("akshare fetch failed for %s: %s", fn_name, exc)
        return []

    expected_cols = {"商品", "日期", "今值", "预测值", "前值"}
    if not expected_cols.issubset(df.columns):
        logger.warning(
            "schema mismatch for %s: got %s, expected superset of %s",
            fn_name, list(df.columns), expected_cols,
        )
        return []

    events: list[MacroEvent] = []
    for _, row in df.iterrows():
        date = _safe_date(row.get("日期"))
        if date is None or date < start or date > end:
            continue
        actual = _coerce_float(row.get("今值"))
        forecast = _coerce_float(row.get("预测值"))
        prior = _coerce_float(row.get("前值"))
        if actual is None and forecast is None and prior is None:
            continue
        commodity = str(row.get("商品") or default_label).strip()
        events.append(MacroEvent(
            date=date,
            event_type=event_type,
            country=country,
            importance=importance,
            actual_value=actual,
            forecast_value=forecast,
            prior_value=prior,
            label=f"{commodity}: actual={actual} forecast={forecast} prior={prior}",
            raw_payload={
                "source": "akshare",
                "fn": fn_name,
                "commodity": commodity,
            },
        ))
    return events


def fetch_us_events(start: str, end: str) -> list[MacroEvent]:
    out: list[MacroEvent] = []
    for event_type, fn_name, importance, label in _US_AK_SOURCES:
        rows = _fetch_ak_standard(fn_name, event_type, "US", importance, label, start, end)
        logger.info("akshare US: %s -> %d rows", event_type, len(rows))
        out.extend(rows)
    return out


# --------------------------------------------------------------------------
# akshare CN
# --------------------------------------------------------------------------

_CN_AK_SOURCES: list[tuple[str, str, int, str]] = [
    ("cn_pmi_mfg",       "macro_china_pmi_yearly",        2, "中国制造业 PMI"),
    ("cn_cpi_monthly",   "macro_china_cpi_monthly",       2, "中国 CPI 月率"),
    # cn_cpi_yearly intentionally NOT included: akshare publishes monthly +
    # yearly on the same date, so they double-count and produce identical
    # aggregate stats (round-1 adversarial audit H3). Keep monthly only.
    ("cn_cx_pmi",        "macro_china_cx_pmi_yearly",     2, "中国财新 PMI"),
]


def fetch_cn_lpr(start: str, end: str) -> list[MacroEvent]:
    """``macro_china_lpr`` has columns [TRADE_DATE, LPR1Y, LPR5Y, RATE_1, RATE_2]
    — different shape, so handled separately."""
    try:
        import akshare as ak  # noqa: PLC0415
    except ImportError:
        return []
    fn = getattr(ak, "macro_china_lpr", None)
    if fn is None:
        return []
    try:
        df = fn()
    except Exception as exc:
        logger.warning("macro_china_lpr fetch failed: %s", exc)
        return []
    if "TRADE_DATE" not in df.columns or "LPR1Y" not in df.columns:
        logger.warning("macro_china_lpr schema mismatch: %s", list(df.columns))
        return []
    events: list[MacroEvent] = []
    for _, row in df.iterrows():
        date = _safe_date(row.get("TRADE_DATE"))
        if date is None or date < start or date > end:
            continue
        lpr_1y = _coerce_float(row.get("LPR1Y"))
        if lpr_1y is None:
            continue
        events.append(MacroEvent(
            date=date,
            event_type="cn_lpr_1y",
            country="CN",
            importance=2,
            actual_value=lpr_1y,
            forecast_value=None,
            prior_value=_coerce_float(row.get("RATE_1")),
            label=f"中国 1Y LPR: {lpr_1y}",
            raw_payload={
                "source": "akshare",
                "fn": "macro_china_lpr",
                "lpr_5y": _coerce_float(row.get("LPR5Y")),
            },
        ))
    return events


def fetch_cn_events(start: str, end: str) -> list[MacroEvent]:
    out: list[MacroEvent] = []
    for event_type, fn_name, importance, label in _CN_AK_SOURCES:
        rows = _fetch_ak_standard(fn_name, event_type, "CN", importance, label, start, end)
        logger.info("akshare CN: %s -> %d rows", event_type, len(rows))
        out.extend(rows)
    out.extend(fetch_cn_lpr(start, end))
    logger.info("akshare CN: cn_lpr_1y -> %d rows", len([e for e in out if e.event_type == "cn_lpr_1y"]))
    return out


# --------------------------------------------------------------------------
# GDELT v2 — high-attention day detector
# --------------------------------------------------------------------------

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
# GDELT docs say 1 req / 5s but throttling fires below that empirically.
# Default pacing pads to 15s, with exponential backoff on 429 (up to 3
# retries). The whole 41-month walk takes ~10 minutes — fine for a one-shot
# collection script, and still well under any reasonable cron budget.
GDELT_RATE_LIMIT_S = 15.0
GDELT_MAX_RETRIES = 3


def _fetch_gdelt_volume(query: str, start_yyyymmdd: str, end_yyyymmdd: str) -> dict[str, int]:
    """Return {date_yyyy_mm_dd: article_count} for the given GDELT query.

    Uses ``mode=TimelineVol`` which gives a daily article-volume series.
    Empty dict on any failure (rate limit, parse, network).
    """
    url = (
        f"{GDELT_BASE}?query={query}&mode=TimelineVol&format=json"
        f"&startdatetime={start_yyyymmdd}000000&enddatetime={end_yyyymmdd}235959"
    )
    backoff = GDELT_RATE_LIMIT_S
    for attempt in range(1, GDELT_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.warning("GDELT request failed (attempt %d): %s", attempt, exc)
            time.sleep(backoff)
            backoff *= 2
            continue
        text = resp.text
        # GDELT returns plain text "Please limit requests..." with HTTP 200
        # in some cases — detect by content, not just status code.
        if "limit requests" in text.lower() or resp.status_code == 429:
            logger.info("GDELT rate-limited on attempt %d, sleeping %.0fs", attempt, backoff)
            time.sleep(backoff)
            backoff *= 2
            continue
        if resp.status_code != 200:
            logger.warning("GDELT non-200: %s -- %s", resp.status_code, text[:200])
            return {}
        try:
            body = resp.json()
        except json.JSONDecodeError:
            logger.warning("GDELT non-JSON response: %s", text[:200])
            return {}
        out: dict[str, int] = {}
        for point in body.get("timeline", [{}])[0].get("data", []):
            date = _safe_date(point.get("date"))
            value = _coerce_float(point.get("value"))
            if date and value is not None:
                out[date] = int(value)
        return out
    logger.warning("GDELT: gave up after %d retries for window %s..%s", GDELT_MAX_RETRIES, start_yyyymmdd, end_yyyymmdd)
    return {}


def fetch_gdelt_high_attention(
    start: str,
    end: str,
    *,
    query: str = "(gold OR Federal Reserve OR Iran OR Ukraine OR oil)",
    sigma_threshold: float = 2.0,
) -> list[MacroEvent]:
    """One event row per date whose article volume exceeds ``sigma_threshold * σ``
    above the rolling 30-day mean for that query.

    GDELT throttles to one request per 5 seconds, so we batch by month windows
    (37 months for 2023-01 → 2026-05) to stay under ~4 minutes total.
    """
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")

    # Walk by month so each request returns one month of data — fewest
    # round-trips that respect GDELT's 5-second-per-request throttle.
    daily_volume: dict[str, int] = {}
    cursor = datetime(start_dt.year, start_dt.month, 1)
    while cursor <= end_dt:
        next_month = datetime(
            cursor.year + (cursor.month // 12),
            (cursor.month % 12) + 1,
            1,
        )
        month_end = datetime.fromordinal(next_month.toordinal() - 1)
        if month_end > end_dt:
            month_end = end_dt
        month_start = max(cursor, start_dt)

        chunk = _fetch_gdelt_volume(
            query,
            month_start.strftime("%Y%m%d"),
            month_end.strftime("%Y%m%d"),
        )
        daily_volume.update(chunk)
        time.sleep(GDELT_RATE_LIMIT_S)
        cursor = next_month

    if not daily_volume:
        logger.warning("GDELT: empty dataset; skipping high-attention detection")
        return []

    # Compute rolling 30-day mean + std; flag dates above threshold.
    dates_sorted = sorted(daily_volume.keys())
    values = [daily_volume[d] for d in dates_sorted]
    events: list[MacroEvent] = []
    for i, date in enumerate(dates_sorted):
        if i < 30:
            continue
        window = values[i - 30:i]
        mean_v = sum(window) / len(window)
        var = sum((v - mean_v) ** 2 for v in window) / len(window)
        std = math.sqrt(var) if var > 0 else 1.0
        if values[i] > mean_v + sigma_threshold * std:
            events.append(MacroEvent(
                date=date,
                event_type="gdelt_high_attention",
                country="global",
                importance=2,
                actual_value=float(values[i]),
                forecast_value=mean_v,
                prior_value=None,
                label=f"GDELT 注意力激增：{values[i]} 篇 vs 30d 均 {mean_v:.0f}（query={query}）",
                raw_payload={
                    "source": "gdelt_v2",
                    "query": query,
                    "rolling_mean_30d": round(mean_v, 1),
                    "rolling_std_30d": round(std, 1),
                    "sigma_above_mean": round((values[i] - mean_v) / std, 2),
                },
            ))
    logger.info("GDELT high-attention: %d events flagged", len(events))
    return events


__all__ = [
    "MacroEvent",
    "fetch_us_events",
    "fetch_cn_events",
    "fetch_cn_lpr",
    "fetch_gdelt_high_attention",
]
