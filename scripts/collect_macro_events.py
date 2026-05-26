"""Collect historical macro events into the ``macro_events`` table.

Sources
-------
- ``--source us``      → akshare US releases (FOMC, NFP, CPI, PCE, ISM, jobless, ADP)
- ``--source cn``      → akshare China releases (PMI, CPI, LPR, Caixin PMI)
- ``--source gdelt``   → GDELT v2 high-attention day flagger (one row per
                        date whose article-volume exceeds 2σ above 30-day mean)
- ``--source all``     → all three (default)

Idempotent
----------
``UNIQUE(date, event_type, country)`` on the table — re-runs are a no-op for
already-inserted rows. ``INSERT OR IGNORE`` semantics inline.

Usage
-----
    python scripts/collect_macro_events.py --dry-run --start 2023-01-01 --end 2026-05-14
    python scripts/collect_macro_events.py --apply --start 2023-01-01 --end 2026-05-14
    python scripts/collect_macro_events.py --apply --source us           # US only
    python scripts/collect_macro_events.py --apply --source gdelt        # GDELT only

Time budgets
------------
- akshare US: ~30 sec (one HTTP per series, 9 series)
- akshare CN: ~10 sec (5 series, one of which is small)
- GDELT 41 months: ~15 minutes (15s pacing × 41 months × occasional retries)
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import warnings
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# akshare emits a flood of urllib3 InsecureRequestWarning + pandas FutureWarning;
# silence at script-level so the actual ROW counts stand out.
warnings.filterwarnings("ignore")

from storage.record_manager import DB_PATH, init_storage  # noqa: E402
from tools.macro_events import (  # noqa: E402
    MacroEvent,
    fetch_cn_events,
    fetch_gdelt_high_attention,
    fetch_us_events,
)


SOURCES = ("us", "cn", "gdelt")


def _gather(source: str, start: str, end: str) -> list[MacroEvent]:
    if source == "us":
        return fetch_us_events(start, end)
    if source == "cn":
        return fetch_cn_events(start, end)
    if source == "gdelt":
        return fetch_gdelt_high_attention(start, end)
    raise ValueError(f"unknown source: {source}")


def _surprise_pct(actual: float | None, forecast: float | None) -> float | None:
    if actual is None or forecast is None or abs(forecast) < 1e-9:
        return None
    return (actual - forecast) / abs(forecast)


def _insert_event(
    conn: sqlite3.Connection,
    event: MacroEvent,
    locked_at: str,
) -> bool:
    """INSERT OR IGNORE; return True if a new row was inserted."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO macro_events (
            date, event_type, country, importance,
            actual_value, forecast_value, prior_value, surprise_pct,
            label, raw_payload, locked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.date,
            event.event_type,
            event.country,
            event.importance,
            event.actual_value,
            event.forecast_value,
            event.prior_value,
            _surprise_pct(event.actual_value, event.forecast_value),
            event.label,
            json.dumps(event.raw_payload, ensure_ascii=False),
            locked_at,
        ),
    )
    return cursor.rowcount == 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist changes (default: dry-run).")
    parser.add_argument("--start", default="2023-01-01", help="Start date YYYY-MM-DD inclusive.")
    parser.add_argument(
        "--end",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD inclusive (default today).",
    )
    parser.add_argument("--source", choices=("all", *SOURCES), default="all")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    targets = SOURCES if args.source == "all" else (args.source,)
    print(f"range {args.start} → {args.end} sources={targets} apply={args.apply}")

    init_storage()
    locked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row

        all_events: list[MacroEvent] = []
        for source in targets:
            print(f"\n--- fetching {source} ---")
            events = _gather(source, args.start, args.end)
            print(f"  {source}: pulled {len(events)} events")
            all_events.extend(events)

        # Distribution preview (works in dry-run too)
        by_type: Counter[str] = Counter(e.event_type for e in all_events)
        print("\nby event_type:")
        for et, n in sorted(by_type.items()):
            print(f"  {et}: {n}")

        if not args.apply:
            print("\n[dry-run] no DB writes")
            return 0

        inserted = 0
        skipped = 0
        for event in all_events:
            if _insert_event(conn, event, locked_at):
                inserted += 1
            else:
                skipped += 1
        conn.commit()

        print(f"\napplied: {inserted} inserted, {skipped} skipped (already locked)")

        # Final tally
        rows = conn.execute(
            "SELECT event_type, COUNT(*) AS n FROM macro_events GROUP BY event_type ORDER BY 2 DESC"
        ).fetchall()
        print("\ndb-after by event_type:")
        for row in rows:
            print(f"  {row['event_type']}: {row['n']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
