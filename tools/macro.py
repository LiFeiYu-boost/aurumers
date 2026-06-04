"""Phase 2 macro indicator fetchers backed by FRED.

We use FRED instead of Yahoo Finance because (1) Yahoo's chart endpoint returns
HTTP 429/403 from the production VPS even with a browser User-Agent, and (2)
FRED is a stable, public source.

Data path: the official JSON API ``api.stlouisfed.org`` with a free
``FRED_API_KEY``. The old no-auth CSV export (``fredgraph.csv``) became
unreachable from datacenter IPs in 2026-06 — TLS completes, then the edge
RSTs the connection. Verified dead from this VPS via direct, all mihomo
nodes, and WARP; the JSON API is reachable directly.

Series:
- ``DTWEXBGS`` (Trade-Weighted USD Index, broad goods) → DXY proxy. Correlation
  with the traditional DX-Y.NYB index is ~0.92 over the last decade. Prompt
  text labels it "广义美元指数 (FRED DTWEXBGS)" so the LLM doesn't confuse it
  with the narrower DXY.
- ``DFII10`` — 10-Year Treasury Inflation-Indexed Security real yield.

Storage layout:
- ``macro_cache(key, value_json, fetched_at)`` — latest snapshot per series,
  6-hour TTL, used by the live daily run (02:50 cron).
- ``macro_history(series_id, date, value)`` — full historical series indexed
  by date, used by historical-mode backtests. Populated whenever a live fetch
  succeeds; ``INSERT OR REPLACE`` because FRED occasionally revises old values.

Failure mode: every public function returns a dict with ``missing=True`` and
``value=None`` on any error. ``logger.warning`` records why. Callers in the
prompt path render this as "数据源不可达，本次不参考"; the LLM sees the
degradation explicitly rather than the daily run crashing.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta
from typing import Iterable

from storage.record_manager import DB_PATH

logger = logging.getLogger(__name__)

_FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"
_DTWEXBGS = "DTWEXBGS"
_DFII10 = "DFII10"
_TIMEOUT = 30
_FETCH_RETRIES = 2  # total attempts = retries + 1
_RETRY_BACKOFF_SECONDS = 1.5
_CACHE_TTL = timedelta(hours=6)


def _ensure_tables() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_cache (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_history (
                series_id TEXT NOT NULL,
                date TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (series_id, date)
            )
            """
        )
        conn.commit()


def _cache_get(key: str) -> dict | None:
    _ensure_tables()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT value_json, fetched_at FROM macro_cache WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row[1])
    except ValueError:
        return None
    if datetime.utcnow() - fetched > _CACHE_TTL:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def _cache_put(key: str, value: dict) -> None:
    _ensure_tables()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO macro_cache (key, value_json, fetched_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.utcnow().isoformat()),
        )
        conn.commit()


def _persist_history(series_id: str, series: Iterable[tuple[str, float]]) -> None:
    _ensure_tables()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO macro_history (series_id, date, value) VALUES (?, ?, ?)",
            [(series_id, d, v) for d, v in series],
        )
        conn.commit()


def _fetch_fred_series(series_id: str) -> list[tuple[str, float]]:
    """Pull the full series via the FRED JSON API. Returns ascending date series.

    FRED uses ``.`` to denote missing values for non-trading days; we drop them.
    Retries with backoff on transient errors (but not on 4xx — a bad/missing
    key never heals by retrying). Raises after the final attempt; caller catches.
    """
    import time as _time
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FRED_API_KEY is not set")
    url = f"{_FRED_API_BASE}?series_id={series_id}&api_key={api_key}&file_type=json"
    for attempt in range(_FETCH_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:
                text = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            # Don't re-raise the HTTPError itself: its .url/.filename carry the
            # full request URL including api_key, one repr()/logger.exception
            # away from the logs. Replace with a sanitized error; `from None`
            # so the original object isn't kept as __cause__ either.
            if 400 <= exc.code < 500 or attempt >= _FETCH_RETRIES:
                raise RuntimeError(
                    f"FRED {series_id}: HTTP {exc.code} {exc.reason}") from None
            _time.sleep(_RETRY_BACKOFF_SECONDS * (2 ** attempt))
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if attempt < _FETCH_RETRIES:
                _time.sleep(_RETRY_BACKOFF_SECONDS * (2 ** attempt))
                continue
            raise
    observations = json.loads(text).get("observations", [])
    out: list[tuple[str, float]] = []
    for obs in observations:
        date_str, raw = (obs.get("date") or "").strip(), (obs.get("value") or "").strip()
        if not date_str or raw in ("", "."):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        out.append((date_str, value))
    if not out:
        raise RuntimeError(f"FRED {series_id}: no usable rows")
    return out


def fred_series(series_id: str) -> list[tuple[str, float]]:
    """Fetch the full FRED series and persist it to ``macro_history``.

    Public entry point shared with ``chains.trend_signal``; the history write
    is what makes the stale-data fallback there possible.
    """
    series = _fetch_fred_series(series_id)
    _persist_history(series_id, series)
    return series


def history_series(series_id: str) -> list[tuple[str, float]]:
    """Full cached series from ``macro_history``, ascending. Empty if never fetched."""
    _ensure_tables()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT date, value FROM macro_history WHERE series_id = ? ORDER BY date",
            (series_id,),
        ).fetchall()
    return [(d, v) for d, v in rows]


def _build_snapshot(series_id: str, source_label: str) -> dict:
    """Live fetch + persist + return snapshot dict."""
    series = fred_series(series_id)
    latest_date, latest_value = series[-1]
    change_5d_pct: float | None = None
    if len(series) >= 6:
        ref_value = series[-6][1]
        if ref_value:
            change_5d_pct = round((latest_value - ref_value) / ref_value * 100, 4)
    return {
        "value": round(latest_value, 4),
        "change_5d_pct": change_5d_pct,
        "value_date": latest_date,
        "source_label": source_label,
        "fetched_at": datetime.utcnow().isoformat(),
        "missing": False,
    }


def _missing(source_label: str, reason: str) -> dict:
    return {
        "value": None,
        "change_5d_pct": None,
        "value_date": None,
        "source_label": source_label,
        "fetched_at": datetime.utcnow().isoformat(),
        "missing": True,
        "reason": reason,
    }


def _fetch_live(
    series_id: str, source_label: str, *, cache_key: str, force_refresh: bool
) -> dict:
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
    try:
        snapshot = _build_snapshot(series_id, source_label)
    except Exception as exc:
        # Catch broadly: this path must never raise into daily_runner. Real
        # failure modes seen in prod include URLError, HTTPError, OSError,
        # TimeoutError, RuntimeError, UnicodeDecodeError (corrupt CSV),
        # sqlite3.OperationalError (transient lock when persisting history).
        logger.warning("macro fetch %s failed: %s", series_id, exc)
        return _missing(source_label, f"{type(exc).__name__}: {exc}")
    try:
        _cache_put(cache_key, snapshot)
    except Exception as exc:
        # Cache miss is not a failure — return the live snapshot anyway.
        logger.warning("macro cache put %s failed: %s", series_id, exc)
    return snapshot


def fetch_dxy_proxy(*, force_refresh: bool = False) -> dict:
    """Latest DXY proxy snapshot. Cached 6h."""
    return _fetch_live(
        _DTWEXBGS,
        "FRED DTWEXBGS (Trade-Weighted USD Index)",
        cache_key="dxy_proxy",
        force_refresh=force_refresh,
    )


def fetch_us10y_real(*, force_refresh: bool = False) -> dict:
    """Latest US 10Y real yield (TIPS) snapshot. Cached 6h."""
    return _fetch_live(
        _DFII10,
        "FRED DFII10 (10Y TIPS Real Yield)",
        cache_key="us10y_real",
        force_refresh=force_refresh,
    )


def _historical_lookup(
    series_id: str, source_label: str, target_date: str
) -> dict:
    """Find latest series value on or before ``target_date`` from macro_history.

    Lookahead-safe: only ``date <= target_date`` rows considered. If the table
    is empty for the series, we trigger one live fetch to warm it (the live
    call returns full FRED history which is itself lookahead-safe — FRED never
    pre-publishes future values).
    """
    _ensure_tables()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM macro_history WHERE series_id = ?", (series_id,)
        ).fetchone()[0]
    if existing == 0:
        try:
            fred_series(series_id)
        except Exception as exc:
            # Same broad-catch reasoning as _fetch_live above.
            logger.warning("macro warm %s failed: %s", series_id, exc)
            return _missing(source_label, f"warm-failed: {exc}")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT date, value FROM macro_history
            WHERE series_id = ? AND date <= ?
            ORDER BY date DESC LIMIT 6
            """,
            (series_id, target_date),
        ).fetchall()
    if not rows:
        return _missing(source_label, f"no-history-on-or-before:{target_date}")
    latest = rows[0]
    change_5d_pct: float | None = None
    if len(rows) >= 6 and rows[5]["value"]:
        change_5d_pct = round((latest["value"] - rows[5]["value"]) / rows[5]["value"] * 100, 4)
    return {
        "value": round(latest["value"], 4),
        "change_5d_pct": change_5d_pct,
        "value_date": latest["date"],
        "source_label": source_label,
        "fetched_at": datetime.utcnow().isoformat(),
        "missing": False,
    }


def fetch_dxy_proxy_historical(target_date: str) -> dict:
    return _historical_lookup(
        _DTWEXBGS, "FRED DTWEXBGS (Trade-Weighted USD Index)", target_date
    )


def fetch_us10y_real_historical(target_date: str) -> dict:
    return _historical_lookup(
        _DFII10, "FRED DFII10 (10Y TIPS Real Yield)", target_date
    )


__all__ = [
    "fetch_dxy_proxy",
    "fetch_us10y_real",
    "fetch_dxy_proxy_historical",
    "fetch_us10y_real_historical",
    "fred_series",
    "history_series",
]
