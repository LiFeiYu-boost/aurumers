"""Shared SGE Au(T+D) and COMEX GC historical OHLC fetchers via akshare.

Phase 0/1.5 had this logic duplicated inside scripts/scrape_historical_ohlc.py;
Phase 2 promotes it to a tools-level module so chains/daily_lock.py (the 03:05
cron) and the scrape script share one implementation.

Lock semantics (unchanged): once a (date, source) row is in daily_ohlc, INSERT
OR IGNORE means it is never rewritten. To correct a value, delete the row via
SQL and re-fetch — there is intentionally no force flag here.
"""
from __future__ import annotations

import sqlite3
from typing import Iterable

_SGE_SYMBOL = "Au(T+D)"
_COMEX_SYMBOL = "GC"


def maybe_float(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def fetch_sge_history() -> list[dict]:
    """Full SGE Au(T+D) OHLC series from akshare (no date filter)."""
    import akshare as ak
    df = ak.spot_hist_sge(symbol=_SGE_SYMBOL)
    rows: list[dict] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "date": str(row["date"])[:10],
                "open": maybe_float(row.get("open")),
                "high": maybe_float(row.get("high")),
                "low": maybe_float(row.get("low")),
                "close": maybe_float(row.get("close")),
                "volume": None,
            }
        )
    return rows


def fetch_comex_history() -> list[dict]:
    """Full COMEX GC futures OHLC series from akshare (no date filter)."""
    import akshare as ak
    df = ak.futures_foreign_hist(symbol=_COMEX_SYMBOL)
    rows: list[dict] = []
    for _, row in df.iterrows():
        d = row["date"]
        date_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        vol_raw = maybe_float(row.get("volume"))
        rows.append(
            {
                "date": date_str,
                "open": maybe_float(row.get("open")),
                "high": maybe_float(row.get("high")),
                "low": maybe_float(row.get("low")),
                "close": maybe_float(row.get("close")),
                "volume": vol_raw if vol_raw and vol_raw > 0 else None,
            }
        )
    return rows


def fetch_history(source: str) -> list[dict]:
    if source == "sge":
        return fetch_sge_history()
    if source == "comex":
        return fetch_comex_history()
    raise ValueError(f"unknown source: {source!r}")


def fetch_single_day(date: str, source: str) -> dict | None:
    """Return one row for (date, source) if upstream has it, else None.

    Used by chains/daily_lock at 03:05 — fetches full history then picks the
    target date. akshare doesn't expose a single-day endpoint cheaply, so this
    is the same upstream call as the scraper, just filtered to one day.
    """
    rows = fetch_history(source)
    for r in rows:
        if r["date"] == date and r["close"] is not None:
            return r
    return None


def filter_rows(rows: Iterable[dict], start: str, end: str) -> list[dict]:
    return [r for r in rows if start <= r["date"] <= end and r["close"] is not None]


def load_existing_dates(conn: sqlite3.Connection, source: str) -> set[str]:
    rows = conn.execute(
        "SELECT date FROM daily_ohlc WHERE source = ?", (source,)
    ).fetchall()
    return {row["date"] for row in rows}


def insert_ohlc_row(
    conn: sqlite3.Connection, source: str, row: dict, locked_at: str
) -> None:
    """INSERT OR IGNORE into daily_ohlc. Caller is responsible for commit."""
    conn.execute(
        """
        INSERT OR IGNORE INTO daily_ohlc (date, source, open, high, low, close, volume, locked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["date"],
            source,
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["volume"],
            locked_at,
        ),
    )
